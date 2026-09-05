"""The controller: drives workloads queued -> admitted -> running -> terminal.

Runs as its own process (`python -m scheduler.reconcile`) beside the API server,
and is the single writer of workload status/node_name/timestamps after submission.
Each tick:
  1. check Kueue admissions (queued -> admitted),
  2. close finished jobs (running -> succeeded/failed), closing their usage
     intervals, freeing their GPUs and deleting their Kueue Workload so the
     quota reservation is released,
  3. place admitted workloads via the active PlacementPolicy (admitted -> running),
     using capacity freed in step 2 within the same tick — gated per tenant on
     the concurrent-GPU quota, and opening a usage interval on placement.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from cluster.protocol import ClusterPort
from db.models import Tenant, Workload
from metering import MeteringStore
from quota import QuotaEnforcer
from scheduler.accounting import used_gpus_by_node, workload_gpus
from scheduler.active_policy import get_active_policy_name
from scheduler.policies import get_policy
from scheduler.policy import ClusterState, PlacementCandidate, PlacementPolicy

logger = logging.getLogger("kestrel.reconcile")


def _check_admissions(db: Session, cluster: ClusterPort) -> int:
    queued = db.execute(select(Workload).where(Workload.status == "queued")).scalars().all()
    admitted = 0
    for w in queued:
        if cluster.is_kueue_workload_admitted(w.k8s_name, w.namespace):
            w.status = "admitted"
            w.admitted_at = datetime.now(UTC)
            admitted += 1
    return admitted


def _sync_running_jobs(db: Session, cluster: ClusterPort) -> int:
    running = (
        db.execute(
            select(Workload).where(Workload.status == "running", Workload.kind == "job")
        )
        .scalars()
        .all()
    )
    metering = MeteringStore(db)
    closed = 0
    for w in running:
        status = cluster.get_job_status(w.k8s_name, w.namespace)
        if status in {"succeeded", "failed"}:
            w.status = status
            w.ended_at = datetime.now(UTC)
            metering.close_interval(w.id, w.ended_at)
            cluster.delete_kueue_workload(w.k8s_name, w.namespace)
            closed += 1
    return closed


def build_cluster_state(db: Session, cluster: ClusterPort) -> ClusterState:
    """Both pools, not just the GPU one.

    A GPU-less node has capacity 0, which is what puts it in the CPU pool and
    keeps it out of the running for GPU work. The control plane is excluded
    outright: kind leaves it untainted and therefore schedulable, and tenant
    workloads do not belong on it.
    """
    capacity = {
        n.name: n.gpu_capacity
        for n in cluster.list_nodes()
        if n.ready and not n.is_control_plane
    }
    running = db.execute(select(Workload).where(Workload.status == "running")).scalars().all()
    return ClusterState(capacity=capacity, used=used_gpus_by_node(running))


def _place_admitted(db: Session, cluster: ClusterPort, policy: PlacementPolicy) -> int:
    rows = db.execute(select(Workload).where(Workload.status == "admitted")).scalars().all()
    if not rows:
        return 0

    now = datetime.now(UTC)
    state = build_cluster_state(db, cluster)
    by_id = {w.id: w for w in rows}

    # Per-tenant GPU tally, queried once then maintained in memory as we place:
    # the session is autoflush=False, so a mid-loop re-query would miss this
    # tick's placements (same lesson as ClusterState.reserve for nodes).
    metering = MeteringStore(db)
    held = QuotaEnforcer(db).running_gpus_by_tenant()
    tenant_ids = {w.tenant_id for w in rows}
    tenants = list(db.execute(select(Tenant).where(Tenant.id.in_(tenant_ids))).scalars())
    max_gpus = {t.id: t.max_gpus for t in tenants}
    runway_by_tenant = {
        t.id: metering.runway_for(t, held.get(t.id, 0), now).runway_seconds for t in tenants
    }

    candidates = [
        PlacementCandidate(
            workload_id=w.id,
            gpus_needed=workload_gpus(w),
            # From the request, not the footprint: a scale-to-zero endpoint asks
            # for GPUs per replica but holds none until it wakes.
            requires_gpu=w.gpus_requested > 0,
            priority=w.priority,
            admitted_at=w.admitted_at or w.created_at,
            tenant_runway_seconds=runway_by_tenant.get(w.tenant_id),
        )
        for w in rows
    ]

    placed = 0
    for candidate in policy.order(candidates, now):
        w = by_id[candidate.workload_id]
        if not QuotaEnforcer.check_placement(
            max_gpus[w.tenant_id], held.get(w.tenant_id, 0), candidate.gpus_needed
        ):
            # Would push the tenant over its concurrent-GPU quota (the only gate
            # endpoints get, since they skip Kueue) — stays admitted, retried
            # next tick once the tenant's running work frees up.
            continue
        node = policy.select_node(state, candidate)
        if node is None:
            # Doesn't fit anywhere right now (e.g. free GPUs exist but are
            # fragmented across nodes) — stays admitted, retried next tick.
            continue
        if w.kind == "job":
            cluster.create_job(
                name=w.k8s_name,
                namespace=w.namespace,
                image=w.spec["image"],
                command=w.spec["command"],
                gpus=w.gpus_requested,
                target_node=node,
            )
        else:
            replicas = int(w.spec.get("min_replicas", 1))
            cluster.create_deployment(
                name=w.k8s_name,
                namespace=w.namespace,
                image=w.spec["image"],
                port=w.spec["port"],
                gpus=w.gpus_requested,
                replicas=replicas,
                target_node=node,
            )
            # Hand the autoscaler its starting point; from here the row, not the
            # spec, is what the footprint is read from.
            w.replicas = replicas
        state.reserve(node, candidate.gpus_needed)
        held[w.tenant_id] = held.get(w.tenant_id, 0) + candidate.gpus_needed
        w.node_name = node
        w.status = "running"
        w.started_at = datetime.now(UTC)
        w.placement_policy = policy.name
        if candidate.gpus_needed > 0:
            # An endpoint placed at min_replicas=0 holds nothing yet — it accrues
            # from the moment the autoscaler wakes it, not from placement.
            metering.open_interval(w.tenant_id, w.id, candidate.gpus_needed, w.started_at)
        placed += 1
    return placed


def reconcile_once(db: Session, cluster: ClusterPort, redis: Redis) -> dict[str, int]:
    policy = get_policy(get_active_policy_name(redis))
    admitted = _check_admissions(db, cluster)
    closed = _sync_running_jobs(db, cluster)
    # The session runs with autoflush=False; flush so the placement step's queries
    # see this tick's admissions and completions (freed capacity is reused same-tick).
    db.flush()
    placed = _place_admitted(db, cluster, policy)
    db.commit()
    return {"admitted": admitted, "closed": closed, "placed": placed}


def main() -> None:
    from cluster import ClusterClient
    from config import settings
    from db import SessionLocal
    from redis_client import control_lock, get_redis

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    cluster = ClusterClient(kubeconfig_path=settings.kubeconfig_path)
    redis = get_redis()
    logger.info("reconciler started (interval %.1fs)", settings.reconcile_interval_seconds)

    while True:
        db = SessionLocal()
        try:
            with control_lock(redis) as acquired:
                # Not acquired means the autoscaler holds it; skip and try next tick
                # rather than queueing up behind it.
                if acquired:
                    stats = reconcile_once(db, cluster, redis)
                    if any(stats.values()):
                        logger.info("tick: %s", stats)
        except Exception:
            logger.exception("reconcile tick failed")
            db.rollback()
        finally:
            db.close()
        time.sleep(settings.reconcile_interval_seconds)


if __name__ == "__main__":
    main()
