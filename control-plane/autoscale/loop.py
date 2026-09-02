"""The autoscaler: drives endpoint replica counts from observed load.

Runs as its own process (`python -m autoscale.loop`) beside the API server and the
reconciler, on its own interval — autoscaling should be able to react faster than
placement without dragging the whole reconcile tick along with it. Both loops take
the same short Redis mutex around a tick, which keeps Phase 2's single-writer
property in effect and rules out two races that would otherwise be real: the two
loops double-booking a node's free GPUs, and both opening a usage interval for the
same endpoint.

Each tick, for every running endpoint:
  1. observe the reported load over the rolling window,
  2. decide a target replica count, then clamp it to the GPUs the node and the
     tenant's quota can actually give,
  3. if it changed: patch the Deployment, rotate the usage interval onto the new
     footprint, and append an autoscale_events row.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime

from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from autoscale.policy import (
    REASON_CAPACITY_CAPPED,
    AutoscaleConfig,
    clamp_to_capacity,
    decide,
)
from autoscale.signal import LoadSignal
from cluster.protocol import ClusterPort
from config import settings
from db.models import AutoscaleEvent, Tenant, Workload
from metering import MeteringStore
from scheduler.accounting import used_gpus_by_node, workload_gpus

logger = logging.getLogger("kestrel.autoscale")


def config_for(workload: Workload) -> AutoscaleConfig:
    """Per-endpoint knobs from the submitted spec, falling back to platform defaults."""
    spec = workload.spec
    target_rps = spec.get("target_rps_per_replica") or settings.autoscale_target_rps_per_replica
    return AutoscaleConfig(
        min_replicas=int(spec.get("min_replicas", 1)),
        max_replicas=int(spec.get("max_replicas", 1)),
        target_rps_per_replica=float(target_rps),
        scale_to_zero_after_seconds=settings.scale_to_zero_after_seconds,
        scale_down_stabilization_seconds=settings.scale_down_stabilization_seconds,
    )


def last_event_at(db: Session, workload_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    """Each endpoint's most recent replica change — the scale-down stabilization clock.

    Read from the audit trail that gets written anyway, so there's no second copy
    of this state to drift out of sync.
    """
    if not workload_ids:
        return {}
    rows = db.execute(
        select(AutoscaleEvent.workload_id, func.max(AutoscaleEvent.at))
        .where(AutoscaleEvent.workload_id.in_(workload_ids))
        .group_by(AutoscaleEvent.workload_id)
    ).all()
    return {workload_id: at for workload_id, at in rows}


def autoscale_once(
    db: Session, cluster: ClusterPort, redis: Redis, now: datetime | None = None
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    endpoints = (
        db.execute(
            select(Workload).where(Workload.kind == "endpoint", Workload.status == "running")
        )
        .scalars()
        .all()
    )
    if not endpoints:
        return {"scaled": 0}

    signal = LoadSignal(redis, settings.autoscale_window_seconds)
    metering = MeteringStore(db)

    # Capacity view, queried once then maintained in memory as we scale: the session
    # is autoflush=False, so a mid-loop re-query would miss this tick's own changes
    # (the same lesson as ClusterState.reserve and the placement loop's GPU tally).
    capacity = {n.name: n.gpu_capacity for n in cluster.list_nodes() if n.ready}
    running = db.execute(select(Workload).where(Workload.status == "running")).scalars().all()
    used_by_node = used_gpus_by_node(running)
    held: dict[uuid.UUID, int] = {}
    for w in running:
        held[w.tenant_id] = held.get(w.tenant_id, 0) + workload_gpus(w)
    tenant_ids = {w.tenant_id for w in endpoints}
    max_gpus = {
        t.id: t.max_gpus
        for t in db.execute(select(Tenant).where(Tenant.id.in_(tenant_ids))).scalars()
    }
    last_events = last_event_at(db, [w.id for w in endpoints])

    scaled = 0
    for w in endpoints:
        if w.node_name is None:
            continue
        config = config_for(w)
        current = w.replicas if w.replicas is not None else config.min_replicas
        decision = decide(
            signal.observe(w.id, now), current, config, now, last_events.get(w.id)
        )

        gpus_per_replica = w.gpus_requested
        node_free = capacity.get(w.node_name, 0) - used_by_node.get(w.node_name, 0)
        headroom = max_gpus.get(w.tenant_id, 0) - held.get(w.tenant_id, 0)
        target = clamp_to_capacity(
            decision.target, current, gpus_per_replica, node_free, headroom
        )
        if target == current:
            continue
        reason = decision.reason if target == decision.target else REASON_CAPACITY_CAPPED

        cluster.scale_deployment(w.k8s_name, w.namespace, target)
        w.replicas = target

        # Metering follows the footprint, not the replica count, so an endpoint
        # requesting 0 GPUs never grows a usage row at all.
        old_footprint = gpus_per_replica * current
        new_footprint = gpus_per_replica * target
        if new_footprint == 0:
            # Close rather than reopen at zero: cost visibly flatlines while asleep.
            metering.close_interval(w.id, now, is_partial=True)
        elif old_footprint == 0:
            metering.open_interval(w.tenant_id, w.id, new_footprint, now)
        else:
            metering.record_partial(w.id, now, gpus=new_footprint)

        db.add(
            AutoscaleEvent(
                workload_id=w.id,
                from_replicas=current,
                to_replicas=target,
                reason=reason,
                at=now,
            )
        )
        delta = new_footprint - old_footprint
        used_by_node[w.node_name] = used_by_node.get(w.node_name, 0) + delta
        held[w.tenant_id] = held.get(w.tenant_id, 0) + delta
        scaled += 1
        logger.info(
            "endpoint %s %s -> %s replicas (%s)", w.k8s_name, current, target, reason
        )

    db.commit()
    return {"scaled": scaled}


def main() -> None:
    from cluster import ClusterClient
    from db import SessionLocal
    from redis_client import control_lock, get_redis

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    cluster = ClusterClient(kubeconfig_path=settings.kubeconfig_path)
    redis = get_redis()
    logger.info("autoscaler started (interval %.1fs)", settings.autoscale_interval_seconds)

    while True:
        db = SessionLocal()
        try:
            with control_lock(redis) as acquired:
                # Not acquired means the reconciler holds it; skip and try next tick
                # rather than queueing up behind it.
                if acquired:
                    autoscale_once(db, cluster, redis)
        except Exception:
            logger.exception("autoscale tick failed")
            db.rollback()
        finally:
            db.close()
        time.sleep(settings.autoscale_interval_seconds)


if __name__ == "__main__":
    main()
