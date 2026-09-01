"""Per-tenant usage and billing reads.

Usage is computed live (open intervals priced to now, nothing persisted);
a billing report additionally persists an append-only snapshot row.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from billing import Billing, usage_breakdown_rows
from db import get_db
from db.models import Tenant
from metering import MeteringStore
from schema.usage import BillingReportOut, UsageOut, WorkloadUsageOut

from ..deps import require_tenant

router = APIRouter(prefix="/tenants", tags=["usage"])


def _parse_period(period: str | None, now: datetime) -> tuple[datetime, datetime]:
    """`YYYY-MM` -> [first of month, first of next month); default: current month."""
    if period is None:
        start = datetime(now.year, now.month, 1, tzinfo=UTC)
    else:
        try:
            parsed = datetime.strptime(period, "%Y-%m")
        except ValueError:
            raise HTTPException(status_code=400, detail="period must be YYYY-MM") from None
        start = parsed.replace(tzinfo=UTC)
    if start.month == 12:
        end = datetime(start.year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(start.year, start.month + 1, 1, tzinfo=UTC)
    return start, end


def _require_own_tenant(tenant_id: uuid.UUID, tenant: Tenant) -> None:
    if tenant.id != tenant_id:
        # Same convention as cross-tenant workload access: don't reveal existence.
        raise HTTPException(status_code=404, detail="tenant not found")


@router.get("/{tenant_id}/usage", response_model=UsageOut)
def get_usage(
    tenant_id: uuid.UUID,
    period: str | None = None,
    tenant: Tenant = Depends(require_tenant),
    db: Session = Depends(get_db),
) -> UsageOut:
    _require_own_tenant(tenant_id, tenant)
    now = datetime.now(UTC)
    period_start, period_end = _parse_period(period, now)

    usage = MeteringStore(db).usage_for(tenant.id, period_start, period_end, now)
    rows, total_cost = usage_breakdown_rows(db, usage, Decimal(str(tenant.price_per_gpu_hour)))
    return UsageOut(
        tenant_id=tenant.id,
        period_start=period_start,
        period_end=period_end,
        total_gpu_seconds=usage.total_gpu_seconds,
        estimated_cost=total_cost,
        workloads=[WorkloadUsageOut(**r) for r in rows],
    )


@router.get("/{tenant_id}/billing-report", response_model=BillingReportOut)
def get_billing_report(
    tenant_id: uuid.UUID,
    period: str | None = None,
    tenant: Tenant = Depends(require_tenant),
    db: Session = Depends(get_db),
) -> BillingReportOut:
    _require_own_tenant(tenant_id, tenant)
    now = datetime.now(UTC)
    period_start, period_end = _parse_period(period, now)

    snapshot = Billing(db).report(tenant, period_start, period_end, now)
    db.commit()
    db.refresh(snapshot)
    return BillingReportOut.model_validate(snapshot)
