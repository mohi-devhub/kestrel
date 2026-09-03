"""Read-only reconstruction of why a workload is in the state it's in.

Built from the same primitives the real placement path uses — `ClusterState`,
`PlacementCandidate`, the active `PlacementPolicy`, `QuotaEnforcer`,
`MeteringStore.runway_for` — so an explanation can never diverge from what
reconcile would actually decide; this just stops short of creating anything or
writing to the database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from cluster.protocol import ClusterPort
from db.models import Tenant, Workload
from economics.runway import RunwayStatus, risk_tier
from metering import MeteringStore
from quota import QuotaEnforcer, QuotaExceeded
from scheduler.accounting import used_gpus_by_node, workload_gpus
from scheduler.policy import ClusterState, PlacementCandidate, PlacementPolicy


@dataclass(frozen=True)
class QuotaExplanation:
    passes: bool
    reason: str | None


@dataclass(frozen=True)
class OrderingExplanation:
    """Only computed while the workload is still `admitted` — once it's placed
    (or terminal), `Workload.node_name`/`placement_policy` already record the
    real outcome and re-simulating the decision would just be a second, possibly
    stale opinion about something that already happened.
    """

    rank: int  # 0-based position in this tick's policy ordering
    total_admitted: int
    would_place_on: str | None
    blocked_reason: str | None


@dataclass(frozen=True)
class WorkloadExplanation:
    workload_id: uuid.UUID
    status: str
    quota: QuotaExplanation
    kueue_admitted: bool | None  # None: not applicable — endpoints skip Kueue
    ordering: OrderingExplanation | None  # None: not currently `admitted`
    runway: RunwayStatus
    runway_risk_tier: int


def explain(
    db: Session,
    cluster: ClusterPort,
    policy: PlacementPolicy,
    workload: Workload,
    now: datetime,
) -> WorkloadExplanation:
    tenant = db.get(Tenant, workload.tenant_id)
    if tenant is None:
        raise ValueError(f"workload {workload.id} references a missing tenant")

    metering = MeteringStore(db)
    quota_enforcer = QuotaEnforcer(db)
    held = quota_enforcer.running_gpus_by_tenant()
    runway = metering.runway_for(tenant, held.get(tenant.id, 0), now)

    quota = _explain_quota(quota_enforcer, tenant, workload, now)
    kueue_admitted = (
        cluster.is_kueue_workload_admitted(workload.k8s_name, workload.namespace)
        if workload.kind == "job"
        else None
    )
    ordering = (
        _explain_ordering(db, cluster, policy, workload, metering, held, now)
        if workload.status == "admitted"
        else None
    )

    return WorkloadExplanation(
        workload_id=workload.id,
        status=workload.status,
        quota=quota,
        kueue_admitted=kueue_admitted,
        ordering=ordering,
        runway=runway,
        runway_risk_tier=risk_tier(runway.runway_seconds),
    )


def _explain_quota(
    quota_enforcer: QuotaEnforcer, tenant: Tenant, workload: Workload, now: datetime
) -> QuotaExplanation:
    try:
        quota_enforcer.check_admission(tenant, workload_gpus(workload), now)
    except QuotaExceeded as exc:
        return QuotaExplanation(passes=False, reason=exc.reason)
    return QuotaExplanation(passes=True, reason=None)


def _explain_ordering(
    db: Session,
    cluster: ClusterPort,
    policy: PlacementPolicy,
    workload: Workload,
    metering: MeteringStore,
    held: dict[uuid.UUID, int],
    now: datetime,
) -> OrderingExplanation:
    """Rebuild this tick's admitted-workload candidate set and walk the active
    policy's order, applying only the read-only decision steps
    (`QuotaEnforcer.check_placement`, `policy.select_node`) up to and including
    `workload` — an exact dry run of what the next reconcile tick would do.
    `held` is mutated as we go, the same way `_place_admitted` mutates its own
    copy; this function owns its own copy so nothing here leaks back out.
    """
    held = dict(held)
    rows = db.execute(select(Workload).where(Workload.status == "admitted")).scalars().all()
    by_id = {w.id: w for w in rows}
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
            priority=w.priority,
            admitted_at=w.admitted_at or w.created_at,
            tenant_runway_seconds=runway_by_tenant.get(w.tenant_id),
        )
        for w in rows
    ]
    ordered = policy.order(candidates, now)
    rank = next(i for i, c in enumerate(ordered) if c.workload_id == workload.id)

    capacity = {
        n.name: n.gpu_capacity for n in cluster.list_nodes() if n.ready and n.gpu_capacity > 0
    }
    running = db.execute(select(Workload).where(Workload.status == "running")).scalars().all()
    state = ClusterState(capacity=capacity, used=used_gpus_by_node(running))

    would_place_on: str | None = None
    blocked_reason: str | None = None
    for candidate in ordered:
        w = by_id[candidate.workload_id]
        is_target = w.id == workload.id
        if not QuotaEnforcer.check_placement(
            max_gpus[w.tenant_id], held.get(w.tenant_id, 0), candidate.gpus_needed
        ):
            if is_target:
                blocked_reason = "would exceed the tenant's concurrent-GPU quota"
                break
            continue
        node = policy.select_node(state, candidate)
        if node is None:
            if is_target:
                blocked_reason = "no node currently has room for this ask"
                break
            continue
        state.reserve(node, candidate.gpus_needed)
        held[w.tenant_id] = held.get(w.tenant_id, 0) + candidate.gpus_needed
        if is_target:
            would_place_on = node
            break

    return OrderingExplanation(
        rank=rank,
        total_admitted=len(ordered),
        would_place_on=would_place_on,
        blocked_reason=blocked_reason,
    )
