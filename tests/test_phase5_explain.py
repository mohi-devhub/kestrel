"""GET /workloads/{id}/explain and the `scheduler.explain.explain` function it
wraps.

Real Postgres + Redis (docker compose up -d postgres redis; alembic upgrade
head), no kind/K8s needed — same convention as test_phase2_reconcile.py.
Namespaces are "fake-" prefixed and swept afterwards.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.main import app
from db import SessionLocal
from db.models import ApiKey, AutoscaleEvent, Tenant, UsageEvent, Workload
from scheduler.explain import explain
from scheduler.policies import FirstFit
from schema.cluster import NodeInfo


class FakeCluster:
    """Minimal in-memory ClusterPort — only what `explain` reads."""

    def __init__(self, nodes: dict[str, int]) -> None:
        self._nodes = nodes
        self.admitted: set[tuple[str, str]] = set()

    def admit(self, namespace: str, name: str) -> None:
        self.admitted.add((namespace, name))

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

    def create_job(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("explain must never create cluster resources")

    def create_deployment(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("explain must never create cluster resources")

    def scale_deployment(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("explain must never mutate the cluster")

    def get_job_status(self, name: str, namespace: str) -> str:
        return "running"

    def is_kueue_workload_admitted(self, name: str, namespace: str) -> bool:
        return (namespace, name) in self.admitted

    def delete_kueue_workload(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("explain must never mutate the cluster")


NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


@pytest.fixture()
def db() -> Any:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


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


def _tenant(
    db: Session, *, max_gpus: int = 8, gpu_second_budget: int | None = None
) -> Tenant:
    slug = f"t-{uuid.uuid4().hex[:8]}"
    tenant = Tenant(
        slug=slug,
        name=slug,
        max_gpus=max_gpus,
        max_workloads=10,
        gpu_second_budget=gpu_second_budget,
        price_per_gpu_hour=1.0,
        created_at=NOW,
    )
    db.add(tenant)
    db.flush()
    return tenant


def _api_key(db: Session, tenant: Tenant) -> str:
    plaintext = f"ksl_{secrets.token_urlsafe(16)}"
    db.add(
        ApiKey(
            tenant_id=tenant.id,
            key_hash=hashlib.sha256(plaintext.encode()).hexdigest(),
            created_at=NOW,
        )
    )
    db.flush()
    return plaintext


def _job(
    db: Session,
    tenant: Tenant,
    namespace: str,
    gpus: int,
    *,
    priority: int = 0,
    status: str = "admitted",
) -> Workload:
    workload = Workload(
        tenant_id=tenant.id,
        kind="job",
        status=status,
        spec={"image": "busybox", "command": ["sleep", "5"], "gpus": gpus},
        gpus_requested=gpus,
        priority=priority,
        namespace=namespace,
        k8s_name=f"job-{uuid.uuid4().hex[:8]}",
        created_at=NOW,
        admitted_at=NOW if status != "queued" else None,
    )
    db.add(workload)
    db.flush()
    return workload


def _running_endpoint(
    db: Session, tenant: Tenant, namespace: str, gpus: int, node: str
) -> Workload:
    workload = Workload(
        tenant_id=tenant.id,
        kind="endpoint",
        status="running",
        spec={"image": "nginx", "min_replicas": 1, "port": 80},
        gpus_requested=gpus,
        replicas=1,
        priority=0,
        namespace=namespace,
        k8s_name=f"endpoint-{uuid.uuid4().hex[:8]}",
        node_name=node,
        created_at=NOW,
        admitted_at=NOW,
        started_at=NOW,
    )
    db.add(workload)
    db.flush()
    return workload


def _ns() -> str:
    return f"fake-{uuid.uuid4().hex[:8]}"


# --- quota ------------------------------------------------------------------------


def test_quota_passes_for_a_workload_within_quota(db: Session) -> None:
    tenant = _tenant(db, max_gpus=8)
    ns = _ns()
    job = _job(db, tenant, ns, gpus=2)
    db.commit()

    result = explain(db, FakeCluster({"n1": 4}), FirstFit(), job, NOW)
    assert result.quota.passes is True
    assert result.quota.reason is None


def test_quota_fails_once_the_budget_is_exhausted(db: Session) -> None:
    tenant = _tenant(db, gpu_second_budget=10)
    ns = _ns()
    job = _job(db, tenant, ns, gpus=1)
    db.commit()
    # No usage recorded, budget is 10 GPU-seconds and unused -> not exhausted yet;
    # simulate exhaustion by dropping the budget to 0.
    tenant.gpu_second_budget = 0
    db.commit()

    result = explain(db, FakeCluster({"n1": 4}), FirstFit(), job, NOW)
    assert result.quota.passes is False
    assert result.quota.reason is not None and "budget" in result.quota.reason


# --- kueue --------------------------------------------------------------------------


def test_kueue_admitted_reflects_cluster_state_for_jobs(db: Session) -> None:
    tenant = _tenant(db)
    ns = _ns()
    job = _job(db, tenant, ns, gpus=1)
    db.commit()
    fake = FakeCluster({"n1": 4})

    assert explain(db, fake, FirstFit(), job, NOW).kueue_admitted is False
    fake.admit(ns, job.k8s_name)
    assert explain(db, fake, FirstFit(), job, NOW).kueue_admitted is True


def test_kueue_admitted_is_not_applicable_for_endpoints(db: Session) -> None:
    tenant = _tenant(db)
    ns = _ns()
    endpoint = _running_endpoint(db, tenant, ns, gpus=1, node="n1")
    db.commit()

    result = explain(db, FakeCluster({"n1": 4}), FirstFit(), endpoint, NOW)
    assert result.kueue_admitted is None


# --- ordering -----------------------------------------------------------------------


def test_ordering_is_none_for_a_still_queued_job(db: Session) -> None:
    tenant = _tenant(db)
    ns = _ns()
    job = _job(db, tenant, ns, gpus=1, status="queued")
    db.commit()

    result = explain(db, FakeCluster({"n1": 4}), FirstFit(), job, NOW)
    assert result.ordering is None


def test_ordering_reports_where_an_admitted_job_would_land(db: Session) -> None:
    tenant = _tenant(db)
    ns = _ns()
    job = _job(db, tenant, ns, gpus=1)
    db.commit()

    result = explain(db, FakeCluster({"n1": 4}), FirstFit(), job, NOW)
    assert result.ordering is not None
    assert result.ordering.rank == 0
    assert result.ordering.total_admitted == 1
    assert result.ordering.would_place_on == "n1"
    assert result.ordering.blocked_reason is None


def test_ordering_reports_fragmentation_block(db: Session) -> None:
    tenant = _tenant(db)
    ns = _ns()
    first = _job(db, tenant, ns, gpus=3)
    second = _job(db, tenant, ns, gpus=3)
    db.commit()
    fake = FakeCluster({"n1": 4})

    result = explain(db, fake, FirstFit(), second, NOW)
    assert result.ordering is not None
    assert result.ordering.rank == 1
    assert result.ordering.would_place_on is None
    assert result.ordering.blocked_reason == "no node currently has room for this ask"
    # First-in-order candidate is unaffected and still fits.
    assert explain(db, fake, FirstFit(), first, NOW).ordering.would_place_on == "n1"  # type: ignore[union-attr]


def test_ordering_reports_tenant_quota_block(db: Session) -> None:
    tenant = _tenant(db, max_gpus=2)
    ns = _ns()
    _running_endpoint(db, tenant, ns, gpus=2, node="n1")  # already at the tenant's cap
    job = _job(db, tenant, ns, gpus=1)
    db.commit()

    result = explain(db, FakeCluster({"n1": 4, "n2": 4}), FirstFit(), job, NOW)
    assert result.ordering is not None
    assert result.ordering.would_place_on is None
    assert result.ordering.blocked_reason == "would exceed the tenant's concurrent-GPU quota"


def test_ordering_is_none_once_running(db: Session) -> None:
    tenant = _tenant(db)
    ns = _ns()
    endpoint = _running_endpoint(db, tenant, ns, gpus=1, node="n1")
    db.commit()

    result = explain(db, FakeCluster({"n1": 4}), FirstFit(), endpoint, NOW)
    assert result.ordering is None


# --- runway -------------------------------------------------------------------------


def test_runway_is_infinite_for_an_unbudgeted_tenant(db: Session) -> None:
    tenant = _tenant(db, gpu_second_budget=None)
    ns = _ns()
    job = _job(db, tenant, ns, gpus=1)
    db.commit()

    result = explain(db, FakeCluster({"n1": 4}), FirstFit(), job, NOW)
    assert result.runway.remaining_gpu_seconds is None
    assert result.runway.runway_seconds is None
    assert result.runway_risk_tier == 0


def test_runway_reflects_current_burn(db: Session) -> None:
    tenant = _tenant(db, max_gpus=8, gpu_second_budget=1000)
    ns = _ns()
    _running_endpoint(db, tenant, ns, gpus=2, node="n1")  # burning 2 GPU-seconds/sec
    job = _job(db, tenant, ns, gpus=1)
    db.commit()

    result = explain(db, FakeCluster({"n1": 4}), FirstFit(), job, NOW)
    assert result.runway.burn_rate_gpus == 2
    assert result.runway.remaining_gpu_seconds == 1000
    assert result.runway.runway_seconds == 500  # 1000 / 2


def test_runway_is_exhausted_once_budget_is_used_up(db: Session) -> None:
    tenant = _tenant(db, gpu_second_budget=0)
    ns = _ns()
    job = _job(db, tenant, ns, gpus=1)
    db.commit()

    result = explain(db, FakeCluster({"n1": 4}), FirstFit(), job, NOW)
    assert result.runway.is_exhausted is True
    assert result.runway.runway_seconds == 0


# --- API -----------------------------------------------------------------------------


def test_explain_endpoint_requires_a_key(client: TestClient) -> None:
    resp = client.get(f"/workloads/{uuid.uuid4()}/explain")
    assert resp.status_code == 422  # missing required header


def test_explain_endpoint_404s_for_another_tenants_workload(
    db: Session, client: TestClient
) -> None:
    owner = _tenant(db)
    other = _tenant(db)
    other_key = _api_key(db, other)
    ns = _ns()
    job = _job(db, owner, ns, gpus=1)
    db.commit()

    resp = client.get(
        f"/workloads/{job.id}/explain", headers={"x-kestrel-key": other_key}
    )
    assert resp.status_code == 404


def test_explain_endpoint_returns_the_full_shape(db: Session, client: TestClient) -> None:
    # A running endpoint, not an admitted job: `explain()` skips both cluster calls
    # for this combination (endpoints skip Kueue; ordering only applies while
    # `admitted`), so this exercises the router/schema wiring without needing a
    # live cluster — the cluster-touching paths are already covered directly
    # against FakeCluster above.
    tenant = _tenant(db, max_gpus=8, gpu_second_budget=1000)
    key = _api_key(db, tenant)
    ns = _ns()
    endpoint = _running_endpoint(db, tenant, ns, gpus=1, node="n1")
    db.commit()

    resp = client.get(f"/workloads/{endpoint.id}/explain", headers={"x-kestrel-key": key})
    assert resp.status_code == 200
    body = resp.json()
    assert body["workload_id"] == str(endpoint.id)
    assert body["status"] == "running"
    assert body["kueue_admitted"] is None
    assert body["ordering"] is None
    assert set(body["quota"]) == {"passes", "reason"}
    assert set(body["runway"]) == {
        "burn_rate_gpus",
        "remaining_gpu_seconds",
        "runway_seconds",
        "risk_tier",
        "is_exhausted",
    }
