"""The Prometheus collector, against real Postgres and an in-memory FakeCluster.

Real Postgres (docker compose up -d postgres; alembic upgrade head), no kind/K8s.
Namespaces are "fake-" prefixed and swept afterwards.

The collector reports on *every* row in the database, so these tests assert on
their own tenants' label values, or on before/after deltas, never on global
totals — other suites and leftover demo rows share the same database.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from db import SessionLocal
from db.models import AutoscaleEvent, Tenant, UsageEvent, Workload
from obs.metrics import KestrelCollector
from schema.cluster import NodeInfo

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


class FakeCluster:
    """Only list_nodes is ever reached by the collector."""

    def __init__(self, nodes: dict[str, int], ready: bool = True, fail: bool = False) -> None:
        self._nodes = nodes
        self._ready = ready
        self._fail = fail

    def list_nodes(self) -> list[NodeInfo]:
        if self._fail:
            raise ConnectionError("cluster unreachable")
        return [
            NodeInfo(
                name=name,
                ready=self._ready,
                gpu_capacity=gpus,
                gpu_allocatable=gpus,
                cpu_capacity="16",
                memory_capacity="64Gi",
            )
            for name, gpus in self._nodes.items()
        ]

    def create_job(self, *a: Any, **k: Any) -> None: ...
    def create_deployment(self, *a: Any, **k: Any) -> None: ...
    def scale_deployment(self, *a: Any, **k: Any) -> None: ...
    def get_job_status(self, name: str, namespace: str) -> str: return "running"
    def is_kueue_workload_admitted(self, name: str, namespace: str) -> bool: return True
    def delete_kueue_workload(self, *a: Any, **k: Any) -> None: ...


@pytest.fixture()
def db() -> Any:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


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


def _collector(nodes: dict[str, int] | None = None, fail: bool = False) -> KestrelCollector:
    return KestrelCollector(SessionLocal, lambda: FakeCluster(nodes or {"n1": 4}, fail=fail))


def _samples(collector: KestrelCollector) -> dict[str, dict[tuple[Any, ...], float]]:
    """Flatten collect() into {sample_name: {sorted_label_pairs: value}}."""
    out: dict[str, dict[tuple[Any, ...], float]] = {}
    for metric in collector.collect():
        for s in metric.samples:
            out.setdefault(s.name, {})[tuple(sorted(s.labels.items()))] = s.value
    return out


def _tenant(db: Session, *, budget: int | None = None, max_gpus: int = 8) -> Tenant:
    slug = f"m-{uuid.uuid4().hex[:8]}"
    tenant = Tenant(
        slug=slug,
        name=slug,
        max_gpus=max_gpus,
        max_workloads=20,
        gpu_second_budget=budget,
        price_per_gpu_hour=1.0,
        created_at=NOW,
    )
    db.add(tenant)
    db.flush()
    return tenant


def _workload(
    db: Session,
    tenant: Tenant,
    *,
    kind: str = "job",
    status: str = "queued",
    gpus: int = 1,
    node: str | None = None,
    replicas: int | None = None,
    admitted_at: datetime | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> Workload:
    spec: dict[str, Any] = (
        {"image": "busybox", "command": ["sleep", "5"]}
        if kind == "job"
        else {"image": "nginx", "port": 80, "min_replicas": 1}
    )
    workload = Workload(
        tenant_id=tenant.id,
        kind=kind,
        status=status,
        spec=spec,
        gpus_requested=gpus,
        priority=0,
        namespace=f"fake-{uuid.uuid4().hex[:8]}",
        k8s_name=f"{kind}-{uuid.uuid4().hex[:8]}",
        node_name=node,
        replicas=replicas,
        created_at=NOW,
        admitted_at=admitted_at,
        started_at=started_at,
        ended_at=ended_at,
    )
    db.add(workload)
    db.flush()
    return workload


# --- queue depth ------------------------------------------------------------------


def test_queue_depth_counts_submitted_but_not_running(db: Session) -> None:
    tenant = _tenant(db)
    _workload(db, tenant, status="queued")
    _workload(db, tenant, status="admitted")
    _workload(db, tenant, status="running", node="n1")
    db.commit()

    depth = _samples(_collector())["kestrel_queue_depth"]
    assert depth[(("tenant", tenant.slug),)] == 2


def test_queue_depth_reports_idle_tenants_as_zero(db: Session) -> None:
    # A series that vanishes when the queue drains would leave a hole in the chart
    # rather than a line falling to zero.
    tenant = _tenant(db)
    db.commit()

    depth = _samples(_collector())["kestrel_queue_depth"]
    assert depth[(("tenant", tenant.slug),)] == 0


def test_terminal_workloads_leave_the_queue(db: Session) -> None:
    tenant = _tenant(db)
    _workload(db, tenant, status="succeeded", started_at=NOW, ended_at=NOW)
    _workload(db, tenant, status="stopped")
    db.commit()

    depth = _samples(_collector())["kestrel_queue_depth"]
    assert depth[(("tenant", tenant.slug),)] == 0


# --- replicas ---------------------------------------------------------------------


def test_autoscale_replicas_reports_running_endpoints(db: Session) -> None:
    tenant = _tenant(db)
    endpoint = _workload(
        db, tenant, kind="endpoint", status="running", node="n1", replicas=3
    )
    db.commit()

    replicas = _samples(_collector())["kestrel_autoscale_replicas"]
    assert replicas[(("endpoint", endpoint.k8s_name), ("tenant", tenant.slug))] == 3


def test_sleeping_endpoint_reports_zero_not_absent(db: Session) -> None:
    tenant = _tenant(db)
    endpoint = _workload(
        db, tenant, kind="endpoint", status="running", node="n1", replicas=0
    )
    db.commit()

    replicas = _samples(_collector())["kestrel_autoscale_replicas"]
    assert replicas[(("endpoint", endpoint.k8s_name), ("tenant", tenant.slug))] == 0


def test_jobs_are_not_reported_as_endpoints(db: Session) -> None:
    tenant = _tenant(db)
    job = _workload(db, tenant, status="running", node="n1")
    db.commit()

    replicas = _samples(_collector())["kestrel_autoscale_replicas"]
    assert not any(labels[0][1] == job.k8s_name for labels in replicas)


# --- nodes ------------------------------------------------------------------------


def test_node_gpu_total_and_used(db: Session) -> None:
    tenant = _tenant(db)
    _workload(db, tenant, status="running", node="kestrel-n1", gpus=2)
    _workload(db, tenant, status="running", node="kestrel-n1", gpus=1)
    db.commit()

    s = _samples(_collector(nodes={"kestrel-n1": 4, "kestrel-n2": 4}))
    assert s["kestrel_node_gpu_total"][(("node", "kestrel-n1"),)] == 4
    assert s["kestrel_node_gpu_used"][(("node", "kestrel-n1"),)] == 3
    assert s["kestrel_node_gpu_used"][(("node", "kestrel-n2"),)] == 0


def test_endpoint_footprint_counts_replicas_on_the_node(db: Session) -> None:
    # Every replica pins to the same node, so the node holds gpus x replicas.
    tenant = _tenant(db)
    _workload(
        db, tenant, kind="endpoint", status="running", node="kestrel-n3", gpus=2, replicas=3
    )
    db.commit()

    s = _samples(_collector(nodes={"kestrel-n3": 8}))
    assert s["kestrel_node_gpu_used"][(("node", "kestrel-n3"),)] == 6


def test_gpuless_nodes_are_left_off_the_map(db: Session) -> None:
    # The kind control-plane node is ready but has no GPUs — the scheduler ignores
    # it in _build_cluster_state, and so does the GPU map.
    db.commit()

    s = _samples(_collector(nodes={"kestrel-control-plane": 0, "kwok-1": 4}))
    assert (("node", "kestrel-control-plane"),) not in s["kestrel_node_gpu_total"]
    assert s["kestrel_node_gpu_total"][(("node", "kwok-1"),)] == 4


def test_unreachable_cluster_drops_node_series_but_keeps_the_rest(db: Session) -> None:
    tenant = _tenant(db)
    _workload(db, tenant, status="queued")
    db.commit()

    s = _samples(_collector(fail=True))
    assert "kestrel_node_gpu_total" not in s
    assert s["kestrel_queue_depth"][(("tenant", tenant.slug),)] == 1


# --- tenant usage, runway -----------------------------------------------------------


def test_tenant_gpu_seconds_reflects_closed_usage(db: Session) -> None:
    tenant = _tenant(db)
    workload = _workload(db, tenant, status="succeeded")
    db.add(
        UsageEvent(
            tenant_id=tenant.id,
            workload_id=workload.id,
            gpus=2,
            started_at=NOW,
            ended_at=NOW + timedelta(seconds=30),
            gpu_seconds=Decimal(60),
            recorded_at=NOW,
        )
    )
    db.commit()

    total = _samples(_collector())["kestrel_tenant_gpu_seconds_total"]
    assert total[(("tenant", tenant.slug),)] == pytest.approx(60.0)


def test_runway_and_risk_tier_for_a_burning_tenant(db: Session) -> None:
    # 400s budget, 1 GPU held, nothing used yet -> 400s of runway, tier 2.
    tenant = _tenant(db, budget=400)
    _workload(db, tenant, status="running", node="n1", gpus=1)
    db.commit()

    s = _samples(_collector())
    assert s["kestrel_tenant_runway_seconds"][(("tenant", tenant.slug),)] == pytest.approx(400.0)
    assert s["kestrel_tenant_risk_tier"][(("tenant", tenant.slug),)] == 2


def test_unbudgeted_tenant_has_a_tier_but_no_runway_sample(db: Session) -> None:
    # Infinite runway has no number a chart could plot; tier 0 says "safe" instead.
    tenant = _tenant(db, budget=None)
    _workload(db, tenant, status="running", node="n1", gpus=1)
    db.commit()

    s = _samples(_collector())
    assert (("tenant", tenant.slug),) not in s["kestrel_tenant_runway_seconds"]
    assert s["kestrel_tenant_risk_tier"][(("tenant", tenant.slug),)] == 0


def test_idle_tenant_with_a_budget_has_no_runway_sample(db: Session) -> None:
    # Nothing burning: the clock isn't running, however little budget is left.
    tenant = _tenant(db, budget=10)
    db.commit()

    s = _samples(_collector())
    assert (("tenant", tenant.slug),) not in s["kestrel_tenant_runway_seconds"]
    assert s["kestrel_tenant_risk_tier"][(("tenant", tenant.slug),)] == 0


# --- histograms ---------------------------------------------------------------------


def test_scheduling_latency_observes_admission_to_placement(db: Session) -> None:
    collector = _collector()
    before = _samples(collector)["kestrel_scheduling_latency_seconds_count"][()]

    tenant = _tenant(db)
    _workload(
        db,
        tenant,
        status="running",
        node="n1",
        admitted_at=NOW,
        started_at=NOW + timedelta(seconds=3),
    )
    db.commit()

    after = _samples(collector)
    assert after["kestrel_scheduling_latency_seconds_count"][()] == before + 1
    # 3s lands in the 5s bucket but not the 2s one.
    assert after["kestrel_scheduling_latency_seconds_bucket"][(("le", "2.0"),)] < after[
        "kestrel_scheduling_latency_seconds_bucket"
    ][(("le", "5.0"),)]


def test_workload_duration_is_labelled_by_kind(db: Session) -> None:
    collector = _collector()
    before = _samples(collector)["kestrel_workload_duration_seconds_count"]

    tenant = _tenant(db)
    _workload(
        db,
        tenant,
        kind="job",
        status="succeeded",
        started_at=NOW,
        ended_at=NOW + timedelta(seconds=10),
    )
    db.commit()

    after = _samples(collector)["kestrel_workload_duration_seconds_count"]
    assert after[(("kind", "job"),)] == before[(("kind", "job"),)] + 1
    assert after[(("kind", "endpoint"),)] == before[(("kind", "endpoint"),)]


def test_unfinished_workloads_are_not_observed(db: Session) -> None:
    collector = _collector()
    before = _samples(collector)["kestrel_workload_duration_seconds_count"][(("kind", "job"),)]

    tenant = _tenant(db)
    _workload(db, tenant, status="running", node="n1", started_at=NOW)  # no ended_at
    db.commit()

    after = _samples(collector)["kestrel_workload_duration_seconds_count"][(("kind", "job"),)]
    assert after == before
