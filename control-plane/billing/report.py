"""Turn metered usage into a billing report.

cost = gpu_seconds / 3600 x price_per_gpu_hour, quantized to cents. Reports are
persisted as append-only `billing_snapshots` rows — regenerating a period adds
a new row rather than rewriting the old one.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from db.models import BillingSnapshot, Tenant, Workload
from metering import MeteringStore, UsageBreakdown

_CENTS = Decimal("0.01")
_SECONDS_PER_HOUR = Decimal(3600)


def cost_of(gpu_seconds: Decimal, price_per_gpu_hour: Decimal) -> Decimal:
    return (gpu_seconds / _SECONDS_PER_HOUR * price_per_gpu_hour).quantize(
        _CENTS, rounding=ROUND_HALF_UP
    )


def usage_breakdown_rows(
    db: Session, usage: UsageBreakdown, price_per_gpu_hour: Decimal
) -> tuple[list[dict[str, Any]], Decimal]:
    """Per-workload cost table + total cost, shared by reports and the live usage API."""
    rows = []
    total_cost = Decimal(0)
    for workload_id, gpu_seconds in sorted(usage.per_workload.items(), key=lambda i: str(i[0])):
        workload = db.get(Workload, workload_id)
        cost = cost_of(gpu_seconds, price_per_gpu_hour)
        total_cost += cost
        rows.append(
            {
                "workload_id": str(workload_id),
                "kind": workload.kind if workload else "unknown",
                "gpus_requested": workload.gpus_requested if workload else None,
                # normalize() strips float artifacts like 3600.0; :f avoids E-notation.
                "gpu_seconds": format(gpu_seconds.normalize(), "f"),
                "cost": str(cost),
            }
        )
    return rows, total_cost


class Billing:
    def __init__(self, db: Session):
        self.db = db
        self.metering = MeteringStore(db)

    def report(
        self, tenant: Tenant, period_start: datetime, period_end: datetime, now: datetime
    ) -> BillingSnapshot:
        usage = self.metering.usage_for(tenant.id, period_start, period_end, now)
        price = Decimal(str(tenant.price_per_gpu_hour))
        breakdown, total_cost = usage_breakdown_rows(self.db, usage, price)

        snapshot = BillingSnapshot(
            tenant_id=tenant.id,
            period_start=period_start,
            period_end=period_end,
            total_gpu_seconds=usage.total_gpu_seconds,
            total_cost=total_cost,
            breakdown=breakdown,
            generated_at=now,
        )
        self.db.add(snapshot)
        return snapshot
