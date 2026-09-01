"""Billing unit tests — real Postgres, rolled-back transactions, no cluster."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from billing import Billing, cost_of
from db import SessionLocal
from db.models import BillingSnapshot, Tenant, Workload
from metering import MeteringStore

T0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
PERIOD_START = datetime(2026, 9, 1, tzinfo=UTC)
PERIOD_END = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture()
def db() -> Any:
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


def _tenant(db: Session, price_per_gpu_hour: float = 2.5) -> Tenant:
    slug = f"t-{uuid.uuid4().hex[:8]}"
    tenant = Tenant(
        slug=slug,
        name=slug,
        max_gpus=8,
        max_workloads=10,
        price_per_gpu_hour=price_per_gpu_hour,
        created_at=T0,
    )
    db.add(tenant)
    db.flush()
    return tenant


def _finished_workload(db: Session, tenant: Tenant, gpus: int, seconds: int) -> Workload:
    workload = Workload(
        tenant_id=tenant.id,
        kind="job",
        status="succeeded",
        spec={"image": "busybox", "command": ["true"], "gpus": gpus},
        gpus_requested=gpus,
        priority=0,
        namespace=f"fake-{uuid.uuid4().hex[:8]}",
        k8s_name=f"job-{uuid.uuid4().hex[:8]}",
        created_at=T0,
    )
    db.add(workload)
    db.flush()
    store = MeteringStore(db)
    store.open_interval(tenant.id, workload.id, gpus=gpus, started_at=T0)
    db.flush()
    store.close_interval(workload.id, T0 + timedelta(seconds=seconds))
    db.flush()
    return workload


def test_cost_of_basic_math() -> None:
    # 1 GPU-hour at 2.50/h.
    assert cost_of(Decimal(3600), Decimal("2.5")) == Decimal("2.50")


def test_cost_of_rounds_half_up_to_cents() -> None:
    # 100 GPU-seconds at 1.00/h = 0.02777... -> 0.03
    assert cost_of(Decimal(100), Decimal("1")) == Decimal("0.03")


def test_report_prices_the_breakdown(db: Session) -> None:
    tenant = _tenant(db, price_per_gpu_hour=2.5)
    w = _finished_workload(db, tenant, gpus=2, seconds=1800)  # 3600 GPU-seconds

    snapshot = Billing(db).report(tenant, PERIOD_START, PERIOD_END, now=PERIOD_END)

    assert snapshot.total_gpu_seconds == Decimal(3600)
    assert snapshot.total_cost == Decimal("2.50")
    assert len(snapshot.breakdown) == 1
    row = snapshot.breakdown[0]
    assert row["workload_id"] == str(w.id)
    assert row["kind"] == "job"
    assert row["gpu_seconds"] == "3600"
    assert row["cost"] == "2.50"


def test_report_totals_sum_over_workloads(db: Session) -> None:
    tenant = _tenant(db, price_per_gpu_hour=1.0)
    _finished_workload(db, tenant, gpus=1, seconds=3600)  # 1.00
    _finished_workload(db, tenant, gpus=4, seconds=900)  # 1.00

    snapshot = Billing(db).report(tenant, PERIOD_START, PERIOD_END, now=PERIOD_END)

    assert snapshot.total_gpu_seconds == Decimal(7200)
    assert snapshot.total_cost == Decimal("2.00")
    assert len(snapshot.breakdown) == 2


def test_reports_are_append_only(db: Session) -> None:
    tenant = _tenant(db)
    _finished_workload(db, tenant, gpus=1, seconds=60)

    billing = Billing(db)
    billing.report(tenant, PERIOD_START, PERIOD_END, now=PERIOD_END)
    billing.report(tenant, PERIOD_START, PERIOD_END, now=PERIOD_END)
    db.flush()

    rows = (
        db.execute(select(BillingSnapshot).where(BillingSnapshot.tenant_id == tenant.id))
        .scalars()
        .all()
    )
    assert len(rows) == 2


def test_empty_period_bills_zero(db: Session) -> None:
    tenant = _tenant(db)
    snapshot = Billing(db).report(tenant, PERIOD_START, PERIOD_END, now=PERIOD_END)
    assert snapshot.total_gpu_seconds == Decimal(0)
    assert snapshot.total_cost == Decimal(0)
    assert snapshot.breakdown == []
