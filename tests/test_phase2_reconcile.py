"""Reconcile-loop tests against an in-memory FakeCluster — real Postgres + Redis
(docker compose up -d postgres redis; alembic upgrade head), but no kind/K8s needed.

Namespaces here are prefixed "fake-" so leftovers from aborted runs can be swept.
Stop the compose reconciler while running tests — it would race these ticks.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from redis import Redis
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from db import SessionLocal
from db.models import Tenant, UsageEvent, Workload
from redis_client import get_redis
from scheduler.active_policy import get_active_policy_name, set_active_policy_name
from scheduler.reconcile import reconcile_once
from schema.cluster import NodeInfo


class FakeCluster:
    """In-memory ClusterPort implementation. Defensive about names it has never
    seen, so stray DB rows from other suites can't crash a tick."""

    def __init__(self, nodes: dict[str, int]) -> None:
        self._nodes = nodes
        self.admitted: set[tuple[str, str]] = set()
        self.jobs: dict[tuple[str, str], dict[str, Any]] = {}
        self.deployments: dict[tuple[str, str], dict[str, Any]] = {}
        self.job_statuses: dict[tuple[str, str], str] = {}
        self.deleted_kueue_workloads: list[tuple[str, str]] = []

    def admit(self, namespace: str, name: str) -> None:
        self.admitted.add((namespace, name))

    def finish(self, namespace: str, name: str, status: str = "succeeded") -> None:
        self.job_statuses[(namespace, name)] = status

    def list_nodes(self) -> list[NodeInfo]:
        return [
            NodeInfo(
                name=name,
                ready=True,
                gpu_capacity=gpus,
                gpu_allocatable=gpus,
                cpu_capacity="16",
                memory_capacity="64Gi",
            )
            for name, gpus in self._nodes.items()
        ]

    def create_job(
        self,
        name: str,
        namespace: str,
        image: str,
        command: list[str],
        gpus: int = 0,
        target_node: str | None = None,
    ) -> None:
        self.jobs[(namespace, name)] = {"gpus": gpus, "target_node": target_node}
        self.job_statuses[(namespace, name)] = "running"

    def create_deployment(
        self,
        name: str,
        namespace: str,
        image: str,
        port: int,
        gpus: int = 0,
        replicas: int = 1,
        target_node: str | None = None,
    ) -> None:
        self.deployments[(namespace, name)] = {
            "gpus": gpus,
            "replicas": replicas,
            "target_node": target_node,
        }

    def get_job_status(self, name: str, namespace: str) -> str:
        return self.job_statuses.get((namespace, name), "running")

    def is_kueue_workload_admitted(self, name: str, namespace: str) -> bool:
        return (namespace, name) in self.admitted

    def delete_kueue_workload(self, name: str, namespace: str) -> None:
        self.deleted_kueue_workloads.append((namespace, name))


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
        session.execute(delete(UsageEvent).where(UsageEvent.workload_id.in_(fake_workloads)))
        session.execute(delete(Workload).where(Workload.namespace.like("fake-%")))
        session.commit()
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
        created_at=datetime.now(UTC),
    )
    db.add(tenant)
    db.flush()
    return tenant


def _job(db: Session, tenant: Tenant, namespace: str, gpus: int, priority: int = 0) -> Workload:
    workload = Workload(
        tenant_id=tenant.id,
        kind="job",
        status="queued",
        spec={"image": "busybox", "command": ["sleep", "5"], "gpus": gpus, "priority": priority},
        gpus_requested=gpus,
        priority=priority,
        namespace=namespace,
        k8s_name=f"job-{uuid.uuid4().hex[:8]}",
        created_at=datetime.now(UTC),
    )
    db.add(workload)
    db.flush()
    return workload


def _endpoint(
    db: Session,
    tenant: Tenant,
    namespace: str,
    gpus: int,
    min_replicas: int = 1,
    status: str = "admitted",
    node_name: str | None = None,
) -> Workload:
    now = datetime.now(UTC)
    workload = Workload(
        tenant_id=tenant.id,
        kind="endpoint",
        status=status,
        spec={"image": "nginx", "gpus": gpus, "min_replicas": min_replicas, "port": 80},
        gpus_requested=gpus,
        priority=0,
        namespace=namespace,
        k8s_name=f"endpoint-{uuid.uuid4().hex[:8]}",
        node_name=node_name,
        created_at=now,
        admitted_at=now,
    )
    db.add(workload)
    db.flush()
    return workload


def test_job_lifecycle(db: Session, redis: Redis) -> None:
    tenant = _tenant(db)
    ns = f"fake-{uuid.uuid4().hex[:8]}"
    job = _job(db, tenant, ns, gpus=2)
    db.commit()
    fake = FakeCluster({"n1": 4, "n2": 4})

    # Not admitted by Kueue yet: stays queued, no K8s Job created.
    reconcile_once(db, fake, redis)
    db.refresh(job)
    assert job.status == "queued"
    assert (ns, job.k8s_name) not in fake.jobs

    # Admission and placement land in the same tick.
    fake.admit(ns, job.k8s_name)
    reconcile_once(db, fake, redis)
    db.refresh(job)
    assert job.status == "running"
    assert job.node_name == "n1"
    assert job.placement_policy == "first_fit"
    assert job.admitted_at is not None and job.started_at is not None
    assert fake.jobs[(ns, job.k8s_name)]["target_node"] == "n1"

    # Completion closes the row and releases the Kueue quota reservation.
    fake.finish(ns, job.k8s_name, "succeeded")
    reconcile_once(db, fake, redis)
    db.refresh(job)
    assert job.status == "succeeded"
    assert job.ended_at is not None
    assert (ns, job.k8s_name) in fake.deleted_kueue_workloads


def test_oversubscription_queues_then_drains(db: Session, redis: Redis) -> None:
    tenant = _tenant(db)
    ns = f"fake-{uuid.uuid4().hex[:8]}"
    first = _job(db, tenant, ns, gpus=3)
    second = _job(db, tenant, ns, gpus=3)
    db.commit()
    fake = FakeCluster({"n1": 4})
    fake.admit(ns, first.k8s_name)
    fake.admit(ns, second.k8s_name)

    reconcile_once(db, fake, redis)
    db.refresh(first)
    db.refresh(second)
    assert first.status == "running"
    assert second.status == "admitted"  # admitted by Kueue, but no node has room

    # Freed capacity is reused within the same tick (sync runs before placement).
    fake.finish(ns, first.k8s_name, "succeeded")
    reconcile_once(db, fake, redis)
    db.refresh(first)
    db.refresh(second)
    assert first.status == "succeeded"
    assert second.status == "running"
    assert second.node_name == "n1"


def test_policy_swap_changes_node_choice(db: Session, redis: Redis) -> None:
    tenant = _tenant(db)
    ns = f"fake-{uuid.uuid4().hex[:8]}"
    # n2 partially occupied: first_fit prefers wide-open n1, bin_packing packs n2.
    _endpoint(db, tenant, ns, gpus=2, status="running", node_name="n2")
    fake = FakeCluster({"n1": 4, "n2": 4})

    job_ff = _job(db, tenant, ns, gpus=1)
    db.commit()
    fake.admit(ns, job_ff.k8s_name)
    reconcile_once(db, fake, redis)
    db.refresh(job_ff)
    assert job_ff.node_name == "n1"
    assert job_ff.placement_policy == "first_fit"

    set_active_policy_name(redis, "bin_packing")
    job_bp = _job(db, tenant, ns, gpus=1)
    db.commit()
    fake.admit(ns, job_bp.k8s_name)
    reconcile_once(db, fake, redis)
    db.refresh(job_bp)
    assert job_bp.node_name == "n2"
    assert job_bp.placement_policy == "bin_packing"


def test_priority_places_high_priority_first(db: Session, redis: Redis) -> None:
    tenant = _tenant(db)
    ns = f"fake-{uuid.uuid4().hex[:8]}"
    low = _job(db, tenant, ns, gpus=3, priority=0)
    high = _job(db, tenant, ns, gpus=3, priority=10)
    db.commit()
    fake = FakeCluster({"n1": 4})  # room for only one of the two
    fake.admit(ns, low.k8s_name)
    fake.admit(ns, high.k8s_name)

    set_active_policy_name(redis, "priority")
    reconcile_once(db, fake, redis)
    db.refresh(low)
    db.refresh(high)
    assert high.status == "running"
    assert low.status == "admitted"


def test_endpoint_replicas_accounted_per_node(db: Session, redis: Redis) -> None:
    tenant = _tenant(db)
    ns = f"fake-{uuid.uuid4().hex[:8]}"
    endpoint = _endpoint(db, tenant, ns, gpus=2, min_replicas=2)  # 4 GPUs on one node
    blocked = _job(db, tenant, ns, gpus=1)
    db.commit()
    fake = FakeCluster({"n1": 4})
    fake.admit(ns, blocked.k8s_name)

    reconcile_once(db, fake, redis)
    db.refresh(endpoint)
    db.refresh(blocked)
    assert endpoint.status == "running"
    assert fake.deployments[(ns, endpoint.k8s_name)] == {
        "gpus": 2,
        "replicas": 2,
        "target_node": "n1",
    }
    # The 2x2-GPU replicas fill the node — the 1-GPU job must wait.
    assert blocked.status == "admitted"


def test_terminal_rows_are_ignored(db: Session, redis: Redis) -> None:
    tenant = _tenant(db)
    ns = f"fake-{uuid.uuid4().hex[:8]}"
    cancelled = _job(db, tenant, ns, gpus=1)
    cancelled.status = "stopped"
    db.commit()
    fake = FakeCluster({"n1": 4})
    fake.admit(ns, cancelled.k8s_name)

    reconcile_once(db, fake, redis)
    db.refresh(cancelled)
    assert cancelled.status == "stopped"
    assert (ns, cancelled.k8s_name) not in fake.jobs


def test_fragmented_capacity_defers_multi_gpu(db: Session, redis: Redis) -> None:
    tenant = _tenant(db)
    ns = f"fake-{uuid.uuid4().hex[:8]}"
    # 1 GPU used on each node: 6 free in total, but no node has 4 free.
    filler_a = _endpoint(db, tenant, ns, gpus=1, status="running", node_name="n1")
    _endpoint(db, tenant, ns, gpus=1, status="running", node_name="n2")
    big = _job(db, tenant, ns, gpus=4)
    db.commit()
    fake = FakeCluster({"n1": 4, "n2": 4})
    fake.admit(ns, big.k8s_name)

    reconcile_once(db, fake, redis)
    db.refresh(big)
    assert big.status == "admitted"
    assert big.node_name is None

    # A whole node frees up -> the 4-GPU job lands on it, all-or-nothing.
    filler_a.status = "stopped"
    db.commit()
    reconcile_once(db, fake, redis)
    db.refresh(big)
    assert big.status == "running"
    assert big.node_name == "n1"


def test_stray_rows_never_crash_a_tick(db: Session, redis: Redis) -> None:
    tenant = _tenant(db)
    ns = f"fake-{uuid.uuid4().hex[:8]}"
    stray = _job(db, tenant, ns, gpus=1)
    stray.status = "running"
    stray.node_name = "n1"
    db.commit()
    fake = FakeCluster({"n1": 4})  # fake has never heard of this job

    reconcile_once(db, fake, redis)
    db.refresh(stray)
    assert stray.status == "running"

    rows = db.execute(select(Workload).where(Workload.namespace == ns)).scalars().all()
    assert len(rows) == 1
