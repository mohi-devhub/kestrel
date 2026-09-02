"""Metering + quota wired through the reconcile loop, against a FakeCluster —
real Postgres + Redis needed, no kind/K8s. Namespaces are "fake-" prefixed and
swept afterwards. Stop the compose reconciler while running tests.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from test_phase2_reconcile import FakeCluster

from db import SessionLocal
from db.models import AutoscaleEvent, Tenant, UsageEvent, Workload
from metering import MeteringStore
from redis_client import get_redis
from scheduler.active_policy import get_active_policy_name, set_active_policy_name
from scheduler.reconcile import reconcile_once


@pytest.fixture()
def db() -> Any:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def redis() -> Any:
    r = get_redis()
    original = get_active_policy_name(r)
    set_active_policy_name(r, "first_fit")
    try:
        yield r
    finally:
        set_active_policy_name(r, original)


@pytest.fixture(autouse=True)
def _sweep_fake_rows() -> Any:
    yield
    session = SessionLocal()
    try:
        fake_workloads = select(Workload.id).where(Workload.namespace.like("fake-%"))
        session.execute(
            delete(AutoscaleEvent).where(AutoscaleEvent.workload_id.in_(fake_workloads))
        )
        session.execute(delete(UsageEvent).where(UsageEvent.workload_id.in_(fake_workloads)))
        session.execute(delete(Workload).where(Workload.namespace.like("fake-%")))
        session.commit()
    finally:
        session.close()


def _tenant(db: Session, max_gpus: int = 8, max_workloads: int = 10) -> Tenant:
    slug = f"t-{uuid.uuid4().hex[:8]}"
    tenant = Tenant(
        slug=slug,
        name=slug,
        max_gpus=max_gpus,
        max_workloads=max_workloads,
        price_per_gpu_hour=1.0,
        created_at=datetime.now(UTC),
    )
    db.add(tenant)
    db.flush()
    return tenant


def _job(db: Session, tenant: Tenant, namespace: str, gpus: int) -> Workload:
    workload = Workload(
        tenant_id=tenant.id,
        kind="job",
        status="queued",
        spec={"image": "busybox", "command": ["sleep", "5"], "gpus": gpus},
        gpus_requested=gpus,
        priority=0,
        namespace=namespace,
        k8s_name=f"job-{uuid.uuid4().hex[:8]}",
        created_at=datetime.now(UTC),
    )
    db.add(workload)
    db.flush()
    return workload


def _open_intervals(db: Session, workload_id: uuid.UUID) -> list[UsageEvent]:
    return list(
        db.execute(
            select(UsageEvent).where(
                UsageEvent.workload_id == workload_id, UsageEvent.ended_at.is_(None)
            )
        )
        .scalars()
        .all()
    )


def test_interval_opens_at_placement_and_closes_at_completion(db: Session, redis: Any) -> None:
    tenant = _tenant(db)
    ns = f"fake-{uuid.uuid4().hex[:8]}"
    job = _job(db, tenant, ns, gpus=2)
    db.commit()
    fake = FakeCluster({"n1": 4})

    fake.admit(ns, job.k8s_name)
    reconcile_once(db, fake, redis)
    db.refresh(job)
    assert job.status == "running"
    open_rows = _open_intervals(db, job.id)
    assert len(open_rows) == 1
    assert open_rows[0].gpus == 2
    assert open_rows[0].started_at == job.started_at

    fake.finish(ns, job.k8s_name, "succeeded")
    reconcile_once(db, fake, redis)
    db.refresh(job)
    assert job.status == "succeeded"
    assert _open_intervals(db, job.id) == []

    usage = MeteringStore(db).usage_for(
        tenant.id, job.started_at, job.ended_at, now=job.ended_at
    )
    expected = Decimal(2) * Decimal(str((job.ended_at - job.started_at).total_seconds()))
    assert usage.per_workload[job.id] == expected


def test_placement_gate_holds_tenant_at_gpu_quota(db: Session, redis: Any) -> None:
    # Cluster has plenty of room; the *tenant* quota (2 GPUs) is the constraint.
    tenant = _tenant(db, max_gpus=2)
    ns = f"fake-{uuid.uuid4().hex[:8]}"
    first = _job(db, tenant, ns, gpus=2)
    second = _job(db, tenant, ns, gpus=2)
    db.commit()
    fake = FakeCluster({"n1": 8})

    fake.admit(ns, first.k8s_name)
    fake.admit(ns, second.k8s_name)
    reconcile_once(db, fake, redis)
    db.refresh(first)
    db.refresh(second)
    statuses = sorted([first.status, second.status])
    assert statuses == ["admitted", "running"]

    # Finishing the running one frees the tenant quota; the held-back job
    # places in the same tick that closes it.
    running = first if first.status == "running" else second
    waiting = second if running is first else first
    fake.finish(ns, running.k8s_name, "succeeded")
    reconcile_once(db, fake, redis)
    db.refresh(waiting)
    assert waiting.status == "running"


def test_other_tenants_are_not_held_back(db: Session, redis: Any) -> None:
    # Tenant A is at quota; tenant B's job must still place in the same tick.
    tenant_a = _tenant(db, max_gpus=2)
    tenant_b = _tenant(db, max_gpus=4)
    ns = f"fake-{uuid.uuid4().hex[:8]}"
    a1 = _job(db, tenant_a, ns, gpus=2)
    a2 = _job(db, tenant_a, ns, gpus=2)
    b1 = _job(db, tenant_b, ns, gpus=2)
    db.commit()
    fake = FakeCluster({"n1": 8})

    for job in (a1, a2, b1):
        fake.admit(ns, job.k8s_name)
    reconcile_once(db, fake, redis)
    for job in (a1, a2, b1):
        db.refresh(job)

    assert b1.status == "running"
    assert sorted([a1.status, a2.status]) == ["admitted", "running"]
