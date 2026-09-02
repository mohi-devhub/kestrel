"""The autoscale loop against a FakeCluster — real Postgres + Redis, no kind/K8s.

Namespaces are "fake-" prefixed and swept afterwards. Stop the compose reconciler
and autoscaler while running these; they'd race the ticks driven here.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from test_phase2_reconcile import FakeCluster

from autoscale.loop import autoscale_once
from autoscale.policy import (
    REASON_CAPACITY_CAPPED,
    REASON_LOAD,
    REASON_SCALE_FROM_ZERO,
    REASON_SCALE_TO_ZERO,
)
from autoscale.signal import LoadSignal
from config import settings
from db import SessionLocal
from db.models import AutoscaleEvent, Tenant, UsageEvent, Workload
from metering import MeteringStore
from redis_client import get_redis

WINDOW = settings.autoscale_window_seconds


@pytest.fixture()
def db() -> Any:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def redis() -> Any:
    return get_redis()


@pytest.fixture(autouse=True)
def _sweep_fake_rows() -> Any:
    yield
    session = SessionLocal()
    try:
        fake = select(Workload.id).where(Workload.namespace.like("fake-%"))
        session.execute(delete(AutoscaleEvent).where(AutoscaleEvent.workload_id.in_(fake)))
        session.execute(delete(UsageEvent).where(UsageEvent.workload_id.in_(fake)))
        session.execute(delete(Workload).where(Workload.namespace.like("fake-%")))
        session.commit()
    finally:
        session.close()


def _tenant(db: Session, max_gpus: int = 8) -> Tenant:
    slug = f"t-{uuid.uuid4().hex[:8]}"
    tenant = Tenant(
        slug=slug,
        name=slug,
        max_gpus=max_gpus,
        max_workloads=10,
        price_per_gpu_hour=Decimal("1.0"),
        created_at=datetime.now(UTC),
    )
    db.add(tenant)
    db.flush()
    return tenant


def _endpoint(
    db: Session,
    tenant: Tenant,
    *,
    gpus: int = 1,
    min_replicas: int = 0,
    max_replicas: int = 4,
    replicas: int | None = None,
    node: str = "node-a",
    started_at: datetime | None = None,
) -> Workload:
    """A placed, running endpoint — the state the reconcile loop leaves behind."""
    now = started_at or datetime.now(UTC)
    current = replicas if replicas is not None else min_replicas
    workload = Workload(
        tenant_id=tenant.id,
        kind="endpoint",
        status="running",
        spec={
            "image": "nginx",
            "gpus": gpus,
            "min_replicas": min_replicas,
            "max_replicas": max_replicas,
            "port": 80,
        },
        gpus_requested=gpus,
        priority=0,
        namespace=f"fake-{tenant.slug}",
        k8s_name=f"endpoint-{uuid.uuid4().hex[:8]}",
        node_name=node,
        replicas=current,
        created_at=now,
        admitted_at=now,
        started_at=now,
    )
    db.add(workload)
    db.flush()
    if current * gpus > 0:
        MeteringStore(db).open_interval(tenant.id, workload.id, current * gpus, now)
    db.commit()
    return workload


def _report(redis: Any, workload: Workload, requests: int, at: datetime | None = None) -> None:
    LoadSignal(redis, WINDOW).record(workload.id, requests, at or datetime.now(UTC))


def _events(db: Session, workload: Workload) -> list[AutoscaleEvent]:
    return list(
        db.execute(
            select(AutoscaleEvent)
            .where(AutoscaleEvent.workload_id == workload.id)
            .order_by(AutoscaleEvent.at)
        )
        .scalars()
        .all()
    )


def _intervals(db: Session, workload: Workload) -> list[UsageEvent]:
    return list(
        db.execute(
            select(UsageEvent)
            .where(UsageEvent.workload_id == workload.id)
            .order_by(UsageEvent.started_at)
        )
        .scalars()
        .all()
    )


def test_load_scales_the_deployment_up(db: Session, redis: Any) -> None:
    cluster = FakeCluster({"node-a": 8})
    tenant = _tenant(db)
    endpoint = _endpoint(db, tenant, replicas=1, min_replicas=1)
    # 15 rps over the window at the default 5 rps/replica target -> 3 replicas.
    _report(redis, endpoint, int(15 * WINDOW))

    stats = autoscale_once(db, cluster, redis)

    assert stats == {"scaled": 1}
    db.refresh(endpoint)
    assert endpoint.replicas == 3
    assert cluster.deployments[(endpoint.namespace, endpoint.k8s_name)]["replicas"] == 3
    events = _events(db, endpoint)
    assert [(e.from_replicas, e.to_replicas, e.reason) for e in events] == [(1, 3, REASON_LOAD)]


def test_scaling_up_rotates_the_usage_interval_onto_the_new_footprint(
    db: Session, redis: Any
) -> None:
    cluster = FakeCluster({"node-a": 8})
    tenant = _tenant(db)
    started = datetime.now(UTC) - timedelta(seconds=10)
    endpoint = _endpoint(db, tenant, gpus=2, replicas=1, min_replicas=1, started_at=started)
    _report(redis, endpoint, int(10 * WINDOW))

    at = datetime.now(UTC)
    autoscale_once(db, cluster, redis, now=at)

    db.refresh(endpoint)
    assert endpoint.replicas == 2
    closed, open_ = _intervals(db, endpoint)
    # The first interval is closed as a partial (the workload kept running) and
    # priced at the footprint it actually held; the new one carries the new size.
    assert closed.gpus == 2 and closed.is_partial and closed.ended_at == at
    assert closed.gpu_seconds == Decimal(2) * Decimal(str((at - started).total_seconds()))
    assert open_.gpus == 4 and open_.ended_at is None and open_.started_at == at


def test_idle_endpoint_scales_to_zero_and_stops_accruing(db: Session, redis: Any) -> None:
    cluster = FakeCluster({"node-a": 8})
    tenant = _tenant(db)
    started = datetime.now(UTC) - timedelta(seconds=100)
    endpoint = _endpoint(db, tenant, gpus=2, replicas=2, min_replicas=0, started_at=started)
    # No load reported at all -> never seen a request -> idle.

    at = datetime.now(UTC)
    autoscale_once(db, cluster, redis, now=at)

    db.refresh(endpoint)
    assert endpoint.replicas == 0
    assert cluster.deployments[(endpoint.namespace, endpoint.k8s_name)]["replicas"] == 0
    assert [(e.to_replicas, e.reason) for e in _events(db, endpoint)] == [
        (0, REASON_SCALE_TO_ZERO)
    ]

    # The interval is closed, not reopened at zero: usage is frozen from here on.
    (interval,) = _intervals(db, endpoint)
    assert interval.ended_at == at and interval.is_partial
    metering = MeteringStore(db)
    later = at + timedelta(seconds=60)
    assert metering.usage_for(tenant.id, started, later, later).total_gpu_seconds == (
        metering.usage_for(tenant.id, started, at, at).total_gpu_seconds
    )


def test_first_request_wakes_a_sleeping_endpoint_and_reopens_metering(
    db: Session, redis: Any
) -> None:
    cluster = FakeCluster({"node-a": 8})
    tenant = _tenant(db)
    endpoint = _endpoint(db, tenant, gpus=2, replicas=0, min_replicas=0)
    assert _intervals(db, endpoint) == [], "a sleeping endpoint holds nothing"

    _report(redis, endpoint, 3)
    at = datetime.now(UTC)
    autoscale_once(db, cluster, redis, now=at)

    db.refresh(endpoint)
    assert endpoint.replicas == 1
    assert [(e.from_replicas, e.to_replicas, e.reason) for e in _events(db, endpoint)] == [
        (0, 1, REASON_SCALE_FROM_ZERO)
    ]
    (interval,) = _intervals(db, endpoint)
    assert interval.gpus == 2 and interval.started_at == at and interval.ended_at is None


def test_scale_up_is_capped_by_free_gpus_on_the_pinned_node(db: Session, redis: Any) -> None:
    cluster = FakeCluster({"node-a": 4})
    tenant = _tenant(db)
    # A neighbour already holds 2 of the node's 4 GPUs.
    neighbour_tenant = _tenant(db)
    _endpoint(db, neighbour_tenant, gpus=2, replicas=1, min_replicas=1, node="node-a")
    endpoint = _endpoint(db, tenant, gpus=1, replicas=1, min_replicas=1, node="node-a")
    _report(redis, endpoint, int(20 * WINDOW))  # wants 4 replicas

    autoscale_once(db, cluster, redis)

    db.refresh(endpoint)
    # 4 total - 2 (neighbour) - 1 (this endpoint) = 1 free GPU, so 1 -> 2 only.
    assert endpoint.replicas == 2
    assert [(e.to_replicas, e.reason) for e in _events(db, endpoint)] == [
        (2, REASON_CAPACITY_CAPPED)
    ]


def test_scale_up_is_capped_by_tenant_gpu_quota(db: Session, redis: Any) -> None:
    cluster = FakeCluster({"node-a": 16})
    tenant = _tenant(db, max_gpus=3)
    endpoint = _endpoint(db, tenant, gpus=1, replicas=1, min_replicas=1)
    _report(redis, endpoint, int(20 * WINDOW))  # wants 4 replicas

    autoscale_once(db, cluster, redis)

    db.refresh(endpoint)
    assert endpoint.replicas == 3, "the node has room, but the tenant's quota does not"


def test_stabilization_window_blocks_an_immediate_scale_down(db: Session, redis: Any) -> None:
    cluster = FakeCluster({"node-a": 8})
    tenant = _tenant(db)
    endpoint = _endpoint(db, tenant, replicas=4, min_replicas=1)
    now = datetime.now(UTC)
    db.add(
        AutoscaleEvent(
            workload_id=endpoint.id,
            from_replicas=1,
            to_replicas=4,
            reason=REASON_LOAD,
            at=now - timedelta(seconds=5),
        )
    )
    db.commit()
    _report(redis, endpoint, int(1 * WINDOW))  # load has collapsed to 1 rps

    assert autoscale_once(db, cluster, redis, now=now) == {"scaled": 0}
    db.refresh(endpoint)
    assert endpoint.replicas == 4

    # Past the window, the same collapsed load does scale it down.
    later = now + timedelta(seconds=settings.scale_down_stabilization_seconds + 1)
    _report(redis, endpoint, int(1 * WINDOW), at=later)
    assert autoscale_once(db, cluster, redis, now=later) == {"scaled": 1}
    db.refresh(endpoint)
    assert endpoint.replicas == 1


def test_steady_load_makes_no_changes(db: Session, redis: Any) -> None:
    cluster = FakeCluster({"node-a": 8})
    tenant = _tenant(db)
    endpoint = _endpoint(db, tenant, replicas=2, min_replicas=1)
    _report(redis, endpoint, int(10 * WINDOW))  # exactly 2 replicas' worth

    assert autoscale_once(db, cluster, redis) == {"scaled": 0}
    assert _events(db, endpoint) == []
    # No rotation either — an unchanged footprint must not churn the usage history.
    assert len(_intervals(db, endpoint)) == 1


def test_jobs_are_never_touched(db: Session, redis: Any) -> None:
    cluster = FakeCluster({"node-a": 8})
    tenant = _tenant(db)
    now = datetime.now(UTC)
    job = Workload(
        tenant_id=tenant.id,
        kind="job",
        status="running",
        spec={"image": "busybox", "command": ["sleep", "60"], "gpus": 2},
        gpus_requested=2,
        priority=0,
        namespace=f"fake-{tenant.slug}",
        k8s_name=f"job-{uuid.uuid4().hex[:8]}",
        node_name="node-a",
        created_at=now,
        started_at=now,
    )
    db.add(job)
    db.commit()

    assert autoscale_once(db, cluster, redis) == {"scaled": 0}
    db.refresh(job)
    assert job.replicas is None
