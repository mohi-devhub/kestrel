"""QuotaEnforcer unit tests — real Postgres, rolled-back transactions, no cluster."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from db import SessionLocal
from db.models import Tenant, Workload
from metering import MeteringStore
from quota import QuotaEnforcer, QuotaExceeded

T0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
NOW = T0 + timedelta(hours=1)


@pytest.fixture()
def db() -> Any:
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


def _tenant(
    db: Session,
    max_gpus: int = 4,
    max_workloads: int = 3,
    gpu_second_budget: int | None = None,
) -> Tenant:
    slug = f"t-{uuid.uuid4().hex[:8]}"
    tenant = Tenant(
        slug=slug,
        name=slug,
        max_gpus=max_gpus,
        max_workloads=max_workloads,
        gpu_second_budget=gpu_second_budget,
        price_per_gpu_hour=1.0,
        created_at=T0,
    )
    db.add(tenant)
    db.flush()
    return tenant


def _workload(
    db: Session,
    tenant: Tenant,
    status: str = "running",
    gpus: int = 1,
    kind: str = "job",
    min_replicas: int = 1,
) -> Workload:
    spec: dict[str, Any] = {"image": "busybox", "gpus": gpus}
    if kind == "job":
        spec["command"] = ["true"]
    else:
        spec.update({"min_replicas": min_replicas, "port": 80})
    workload = Workload(
        tenant_id=tenant.id,
        kind=kind,
        status=status,
        spec=spec,
        gpus_requested=gpus,
        priority=0,
        namespace=f"fake-{uuid.uuid4().hex[:8]}",
        k8s_name=f"{kind}-{uuid.uuid4().hex[:8]}",
        created_at=T0,
    )
    db.add(workload)
    db.flush()
    return workload


def test_workload_limit_counts_all_in_flight_statuses(db: Session) -> None:
    tenant = _tenant(db, max_workloads=3)
    for status in ("queued", "admitted", "running"):
        _workload(db, tenant, status=status)

    with pytest.raises(QuotaExceeded, match="workload limit"):
        QuotaEnforcer(db).check_admission(tenant, 1, NOW)


def test_terminal_workloads_do_not_count(db: Session) -> None:
    tenant = _tenant(db, max_workloads=2)
    for status in ("succeeded", "failed", "stopped"):
        _workload(db, tenant, status=status)

    QuotaEnforcer(db).check_admission(tenant, 1, NOW)  # does not raise


def test_impossible_gpu_ask_is_rejected_upfront(db: Session) -> None:
    tenant = _tenant(db, max_gpus=4)
    with pytest.raises(QuotaExceeded, match="could never run"):
        QuotaEnforcer(db).check_admission(tenant, 5, NOW)


def test_ask_within_quota_is_admitted_even_while_busy(db: Session) -> None:
    # Waiting in line beyond current capacity is Kueue's queueing model — a
    # full tenant may still *submit*; the placement gate holds it back later.
    tenant = _tenant(db, max_gpus=4)
    _workload(db, tenant, status="running", gpus=4)

    QuotaEnforcer(db).check_admission(tenant, 4, NOW)  # does not raise


def test_check_placement_math(db: Session) -> None:
    assert QuotaEnforcer.check_placement(max_gpus=4, running_gpus=2, gpus_needed=2)
    assert not QuotaEnforcer.check_placement(max_gpus=4, running_gpus=3, gpus_needed=2)


def test_running_gpus_by_tenant_counts_endpoint_replicas(db: Session) -> None:
    tenant = _tenant(db, max_gpus=8)
    _workload(db, tenant, status="running", gpus=2, kind="endpoint", min_replicas=2)
    _workload(db, tenant, status="running", gpus=1)
    _workload(db, tenant, status="admitted", gpus=4)  # not running: not counted

    held = QuotaEnforcer(db).running_gpus_by_tenant()
    assert held[tenant.id] == 5  # 2x2 replicas + 1


def test_budget_blocks_once_crossed(db: Session) -> None:
    tenant = _tenant(db, gpu_second_budget=100)
    w = _workload(db, tenant, gpus=2)
    store = MeteringStore(db)
    store.open_interval(tenant.id, w.id, gpus=2, started_at=T0)
    db.flush()
    store.close_interval(w.id, T0 + timedelta(seconds=60))  # 120 GPU-seconds
    db.flush()

    enforcer = QuotaEnforcer(db)
    assert enforcer.is_over_budget(tenant, NOW)
    with pytest.raises(QuotaExceeded, match="budget"):
        enforcer.check_admission(tenant, 1, NOW)


def test_budget_counts_live_open_intervals(db: Session) -> None:
    tenant = _tenant(db, gpu_second_budget=100)
    w = _workload(db, tenant, gpus=1)
    MeteringStore(db).open_interval(tenant.id, w.id, gpus=1, started_at=T0)
    db.flush()

    enforcer = QuotaEnforcer(db)
    # 90s in: under budget. 120s in: the still-running interval alone crosses it.
    assert not enforcer.is_over_budget(tenant, T0 + timedelta(seconds=90))
    assert enforcer.is_over_budget(tenant, T0 + timedelta(seconds=120))


def test_no_budget_means_unlimited(db: Session) -> None:
    tenant = _tenant(db, gpu_second_budget=None)
    assert not QuotaEnforcer(db).is_over_budget(tenant, NOW)
