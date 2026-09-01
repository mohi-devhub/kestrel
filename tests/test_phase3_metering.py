"""MeteringStore unit tests — real Postgres (docker compose up -d postgres;
alembic upgrade head), no cluster needed. Every test runs inside one rolled-back
transaction, so nothing persists.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from db import SessionLocal
from db.models import Tenant, UsageEvent, Workload
from metering import MeteringStore

T0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture()
def db() -> Any:
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


def _tenant(db: Session) -> Tenant:
    slug = f"t-{uuid.uuid4().hex[:8]}"
    tenant = Tenant(
        slug=slug,
        name=slug,
        max_gpus=8,
        max_workloads=10,
        price_per_gpu_hour=1.0,
        created_at=T0,
    )
    db.add(tenant)
    db.flush()
    return tenant


def _workload(db: Session, tenant: Tenant, gpus: int = 1) -> Workload:
    workload = Workload(
        tenant_id=tenant.id,
        kind="job",
        status="running",
        spec={"image": "busybox", "command": ["true"], "gpus": gpus},
        gpus_requested=gpus,
        priority=0,
        namespace=f"fake-{uuid.uuid4().hex[:8]}",
        k8s_name=f"job-{uuid.uuid4().hex[:8]}",
        created_at=T0,
    )
    db.add(workload)
    db.flush()
    return workload


def test_open_then_close_computes_gpu_seconds(db: Session) -> None:
    tenant = _tenant(db)
    w = _workload(db, tenant, gpus=2)
    store = MeteringStore(db)

    store.open_interval(tenant.id, w.id, gpus=2, started_at=T0)
    db.flush()
    closed = store.close_interval(w.id, T0 + timedelta(seconds=90))

    assert closed is not None
    assert closed.gpu_seconds == Decimal(180)
    assert closed.ended_at == T0 + timedelta(seconds=90)
    assert closed.is_partial is False


def test_open_is_idempotent(db: Session) -> None:
    tenant = _tenant(db)
    w = _workload(db, tenant)
    store = MeteringStore(db)

    first = store.open_interval(tenant.id, w.id, gpus=1, started_at=T0)
    db.flush()
    second = store.open_interval(tenant.id, w.id, gpus=1, started_at=T0 + timedelta(seconds=5))

    assert second is first
    rows = db.execute(select(UsageEvent).where(UsageEvent.workload_id == w.id)).scalars().all()
    assert len(rows) == 1


def test_close_without_open_is_noop(db: Session) -> None:
    tenant = _tenant(db)
    w = _workload(db, tenant)
    assert MeteringStore(db).close_interval(w.id, T0) is None


def test_double_close_is_noop(db: Session) -> None:
    tenant = _tenant(db)
    w = _workload(db, tenant)
    store = MeteringStore(db)
    store.open_interval(tenant.id, w.id, gpus=1, started_at=T0)
    db.flush()

    first = store.close_interval(w.id, T0 + timedelta(seconds=10))
    # No flush in between — the DB snapshot still shows the row as open; the
    # store must trust instance state and refuse to close it again.
    second = store.close_interval(w.id, T0 + timedelta(seconds=60))

    assert first is not None and second is None
    assert first.gpu_seconds == Decimal(10)


def test_record_partial_rotates_the_interval(db: Session) -> None:
    tenant = _tenant(db)
    w = _workload(db, tenant, gpus=3)
    store = MeteringStore(db)
    store.open_interval(tenant.id, w.id, gpus=3, started_at=T0)
    db.flush()

    reopened = store.record_partial(w.id, T0 + timedelta(seconds=60))
    db.flush()

    assert reopened is not None
    assert reopened.started_at == T0 + timedelta(seconds=60)
    assert reopened.gpus == 3 and reopened.ended_at is None
    rows = (
        db.execute(
            select(UsageEvent).where(UsageEvent.workload_id == w.id).order_by(UsageEvent.started_at)
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert rows[0].is_partial is True and rows[0].gpu_seconds == Decimal(180)

    # The rotation is seamless: total usage across both rows is continuous.
    usage = store.usage_for(
        tenant.id, T0, T0 + timedelta(seconds=120), now=T0 + timedelta(seconds=120)
    )
    assert usage.total_gpu_seconds == Decimal(360)


def test_usage_clips_intervals_to_the_period(db: Session) -> None:
    tenant = _tenant(db)
    w = _workload(db, tenant)
    store = MeteringStore(db)
    # One GPU held from Sep 1 12:00 for 48 hours, queried for a window that
    # starts 24h in: only the second day lands in the window.
    store.open_interval(tenant.id, w.id, gpus=1, started_at=T0)
    db.flush()
    store.close_interval(w.id, T0 + timedelta(hours=48))

    window_start = T0 + timedelta(hours=24)
    window_end = T0 + timedelta(hours=72)
    usage = store.usage_for(tenant.id, window_start, window_end, now=window_end)
    assert usage.total_gpu_seconds == Decimal(24 * 3600)


def test_open_interval_accrues_to_now(db: Session) -> None:
    tenant = _tenant(db)
    w = _workload(db, tenant, gpus=2)
    store = MeteringStore(db)
    store.open_interval(tenant.id, w.id, gpus=2, started_at=T0)
    db.flush()

    usage = store.usage_for(
        tenant.id, T0, T0 + timedelta(hours=1), now=T0 + timedelta(seconds=300)
    )
    assert usage.total_gpu_seconds == Decimal(600)


def test_breakdown_is_per_workload(db: Session) -> None:
    tenant = _tenant(db)
    w1 = _workload(db, tenant, gpus=1)
    w2 = _workload(db, tenant, gpus=4)
    store = MeteringStore(db)
    store.open_interval(tenant.id, w1.id, gpus=1, started_at=T0)
    store.open_interval(tenant.id, w2.id, gpus=4, started_at=T0)
    db.flush()
    store.close_interval(w1.id, T0 + timedelta(seconds=100))
    store.close_interval(w2.id, T0 + timedelta(seconds=50))
    db.flush()

    usage = store.usage_for(tenant.id, T0, T0 + timedelta(hours=1), now=T0 + timedelta(hours=1))
    assert usage.per_workload[w1.id] == Decimal(100)
    assert usage.per_workload[w2.id] == Decimal(200)
    assert usage.total_gpu_seconds == Decimal(300)


def test_usage_ignores_other_tenants(db: Session) -> None:
    tenant_a, tenant_b = _tenant(db), _tenant(db)
    w = _workload(db, tenant_a, gpus=2)
    store = MeteringStore(db)
    store.open_interval(tenant_a.id, w.id, gpus=2, started_at=T0)
    db.flush()

    usage = store.usage_for(
        tenant_b.id, T0, T0 + timedelta(hours=1), now=T0 + timedelta(hours=1)
    )
    assert usage.total_gpu_seconds == Decimal(0)
    assert usage.per_workload == {}
