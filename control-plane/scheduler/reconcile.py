"""The controller: drives workloads queued -> admitted -> running -> terminal.

Runs as its own process (`python -m scheduler.reconcile`) beside the API server,
and is the single writer of workload status/node_name/timestamps after submission.
Each tick:
  1. check Kueue admissions (queued -> admitted),
  2. close finished jobs (running -> succeeded/failed), freeing their GPUs and
     deleting their Kueue Workload so the quota reservation is released,
  3. place admitted workloads via the active PlacementPolicy (admitted -> running),
     using capacity freed in step 2 within the same tick.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from cluster.protocol import ClusterPort
from db.models import Workload
from scheduler.accounting import effective_gpus, used_gpus_by_node
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
    closed = 0
    for w in running:
        status = cluster.get_job_status(w.k8s_name, w.namespace)
        if status in {"succeeded", "failed"}:
            w.status = status
            w.ended_at = datetime.now(UTC)
            cluster.delete_kueue_workload(w.k8s_name, w.namespace)
            closed += 1
    return closed


def _build_cluster_state(db: Session, cluster: ClusterPort) -> ClusterState:
    capacity = {
        n.name: n.gpu_capacity for n in cluster.list_nodes() if n.ready and n.gpu_capacity > 0
    }
    running = db.execute(select(Workload).where(Workload.status == "running")).scalars().all()
    return ClusterState(capacity=capacity, used=used_gpus_by_node(running))


def _place_admitted(db: Session, cluster: ClusterPort, policy: PlacementPolicy) -> int:
    rows = db.execute(select(Workload).where(Workload.status == "admitted")).scalars().all()
    if not rows:
        return 0

    state = _build_cluster_state(db, cluster)
    by_id = {w.id: w for w in rows}
    candidates = [
        PlacementCandidate(
            workload_id=w.id,
            gpus_needed=effective_gpus(w.kind, w.gpus_requested, w.spec),
            priority=w.priority,
            admitted_at=w.admitted_at or w.created_at,
        )
        for w in rows
    ]

    placed = 0
    for candidate in policy.order(candidates):
        node = policy.select_node(state, candidate)
        if node is None:
            # Doesn't fit anywhere right now (e.g. free GPUs exist but are
            # fragmented across nodes) — stays admitted, retried next tick.
            continue
        w = by_id[candidate.workload_id]
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
            cluster.create_deployment(
                name=w.k8s_name,
                namespace=w.namespace,
                image=w.spec["image"],
                port=w.spec["port"],
                gpus=w.gpus_requested,
                replicas=int(w.spec.get("min_replicas", 1)),
                target_node=node,
            )
        state.reserve(node, candidate.gpus_needed)
        w.node_name = node
        w.status = "running"
        w.started_at = datetime.now(UTC)
        w.placement_policy = policy.name
        placed += 1
    return placed


def reconcile_once(db: Session, cluster: ClusterPort, redis: Redis) -> dict[str, int]:
    policy = get_policy(get_active_policy_name(redis))
    admitted = _check_admissions(db, cluster)
    closed = _sync_running_jobs(db, cluster)
    placed = _place_admitted(db, cluster, policy)
    db.commit()
    return {"admitted": admitted, "closed": closed, "placed": placed}


def main() -> None:
    from cluster import ClusterClient
    from config import settings
    from db import SessionLocal
    from redis_client import get_redis

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    cluster = ClusterClient(kubeconfig_path=settings.kubeconfig_path)
    redis = get_redis()
    logger.info("reconciler started (interval %.1fs)", settings.reconcile_interval_seconds)

    while True:
        db = SessionLocal()
        try:
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
