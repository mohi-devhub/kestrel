"""Tenant quota checks: admission, placement, and budget.

Belt-and-suspenders beside Kueue's own quota — and the *only* gate endpoints
get, since they skip Kueue admission entirely.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Tenant, Workload
from metering import EPOCH, MeteringStore
from scheduler.accounting import workload_gpus

# In-flight statuses: these rows occupy a slot against max_workloads.
ACTIVE_STATUSES = {"queued", "admitted", "running"}


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
        """Raise QuotaExceeded if this submission should be rejected outright.

        `gpus_requested` must be the *effective* footprint (endpoint = gpus x replicas).

        Deliberately does NOT count queued/admitted GPUs against max_gpus:
        waiting in line beyond current capacity is Kueue's queueing model, and
        the placement gate enforces concurrency when work actually starts. Only
        an ask bigger than the tenant's whole quota is rejected here — it could
        never run and would wedge in the queue forever.
        """
        active = self._active_workloads(tenant.id)
        if len(active) >= tenant.max_workloads:
            raise QuotaExceeded(
                f"workload limit reached: {len(active)}/{tenant.max_workloads} active workloads"
            )
        if gpus_requested > tenant.max_gpus:
            raise QuotaExceeded(
                f"requested {gpus_requested} GPUs but the tenant quota is"
                f" {tenant.max_gpus}; this workload could never run"
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
            held[w.tenant_id] = held.get(w.tenant_id, 0) + workload_gpus(w)
        return held

    def is_over_budget(self, tenant: Tenant, now: datetime) -> bool:
        """Lifetime metered usage (open intervals included) has crossed the budget."""
        if tenant.gpu_second_budget is None:
            return False
        usage = self.metering.usage_for(tenant.id, EPOCH, now, now)
        return usage.total_gpu_seconds >= Decimal(tenant.gpu_second_budget)
