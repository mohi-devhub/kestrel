"""Tenant quota checks: admission, placement, and budget.

Belt-and-suspenders beside Kueue's own quota — and the *only* gate endpoints
get, since they skip Kueue admission entirely.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Tenant, Workload
from metering import MeteringStore
from scheduler.accounting import effective_gpus

# Statuses that hold quota: queued/admitted rows already hold a Kueue
# reservation or queue spot, so they count toward concurrency limits.
ACTIVE_STATUSES = {"queued", "admitted", "running"}

# All-time window for lifetime budgets.
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class QuotaExceeded(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class QuotaEnforcer:
    def __init__(self, db: Session):
        self.db = db
        self.metering = MeteringStore(db)

    def _active_workloads(self, tenant_id: uuid.UUID) -> list[Workload]:
        return list(
            self.db.execute(
                select(Workload).where(
                    Workload.tenant_id == tenant_id, Workload.status.in_(ACTIVE_STATUSES)
                )
            )
            .scalars()
            .all()
        )

    def check_admission(self, tenant: Tenant, gpus_requested: int, now: datetime) -> None:
        """Raise QuotaExceeded if accepting this submission would break a limit.

        `gpus_requested` must be the *effective* footprint (endpoint = gpus x replicas).
        """
        active = self._active_workloads(tenant.id)
        if len(active) >= tenant.max_workloads:
            raise QuotaExceeded(
                f"workload limit reached: {len(active)}/{tenant.max_workloads} active workloads"
            )
        held = sum(effective_gpus(w.kind, w.gpus_requested, w.spec) for w in active)
        if held + gpus_requested > tenant.max_gpus:
            raise QuotaExceeded(
                f"GPU limit exceeded: {held} held + {gpus_requested} requested"
                f" > {tenant.max_gpus} allowed"
            )
        if self.is_over_budget(tenant, now):
            raise QuotaExceeded(
                f"GPU-second budget exhausted ({tenant.gpu_second_budget}s); "
                "new submissions are blocked"
            )

    @staticmethod
    def check_placement(max_gpus: int, running_gpus: int, gpus_needed: int) -> bool:
        """May a workload holding `gpus_needed` start running right now?"""
        return running_gpus + gpus_needed <= max_gpus

    def running_gpus_by_tenant(self) -> dict[uuid.UUID, int]:
        """Effective GPUs held by running workloads, per tenant.

        Queried once at reconcile-tick start; the loop then maintains its own
        in-memory tally as it places (the session is autoflush=False, so a
        mid-tick re-query would miss same-tick placements).
        """
        running = (
            self.db.execute(select(Workload).where(Workload.status == "running"))
            .scalars()
            .all()
        )
        held: dict[uuid.UUID, int] = {}
        for w in running:
            held[w.tenant_id] = held.get(w.tenant_id, 0) + effective_gpus(
                w.kind, w.gpus_requested, w.spec
            )
        return held

    def is_over_budget(self, tenant: Tenant, now: datetime) -> bool:
        """Lifetime metered usage (open intervals included) has crossed the budget."""
        if tenant.gpu_second_budget is None:
            return False
        usage = self.metering.usage_for(tenant.id, EPOCH, now, now)
        return usage.total_gpu_seconds >= Decimal(tenant.gpu_second_budget)
