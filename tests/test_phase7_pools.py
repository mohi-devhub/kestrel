"""Heterogeneous placement: a GPU pool and a CPU pool.

The pure tests here need no infrastructure. The last one exercises
`_build_cluster_state`, which reads running workloads, so it needs Postgres.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.orm import Session

from db import SessionLocal
from scheduler.policies import BinPacking, FirstFit, Priority, RunwayFair
from scheduler.policy import ClusterState, PlacementCandidate
from scheduler.reconcile import build_cluster_state
from schema.cluster import NodeInfo

T0 = datetime(2026, 1, 1, tzinfo=UTC)

ALL_POLICIES = (FirstFit(), BinPacking(), Priority(), RunwayFair())


def _candidate(gpus: int, *, requires_gpu: bool | None = None) -> PlacementCandidate:
    return PlacementCandidate(
        workload_id=uuid.uuid4(),
        gpus_needed=gpus,
        requires_gpu=gpus > 0 if requires_gpu is None else requires_gpu,
        priority=0,
        admitted_at=T0,
    )


def _mixed_fleet() -> ClusterState:
    """Two simulated GPU nodes and one real CPU node, which is the shape of the
    cluster once a `role: worker` is added beside the KWOK nodes."""
    return ClusterState(capacity={"gpu-a": 4, "gpu-b": 4, "cpu-worker": 0})


# --- pool routing ------------------------------------------------------------------


def test_cpu_only_work_goes_to_the_cpu_pool() -> None:
    state = _mixed_fleet()
    for policy in ALL_POLICIES:
        assert policy.select_node(state, _candidate(0)) == "cpu-worker", policy.name


def test_gpu_work_never_lands_on_a_cpu_node() -> None:
    # The CPU node sorts first alphabetically, so a policy that ignored pools
    # would pick it.
    state = ClusterState(capacity={"aaa-cpu": 0, "gpu-a": 4})
    for policy in ALL_POLICIES:
        assert policy.select_node(state, _candidate(2)) == "gpu-a", policy.name


def test_cpu_work_is_not_parked_on_a_gpu_node() -> None:
    """The regression this whole split exists for: a 0-GPU workload "fits" on
    every node in the fleet, so it used to land on a simulated GPU node and its
    container never executed."""
    state = _mixed_fleet()
    for policy in ALL_POLICIES:
        assert policy.select_node(state, _candidate(0)) not in {"gpu-a", "gpu-b"}, policy.name


def test_cpu_work_stays_unplaced_when_there_is_no_cpu_pool() -> None:
    # Better to leave it admitted and retry than to place it somewhere it can
    # never run.
    gpu_only = ClusterState(capacity={"gpu-a": 4, "gpu-b": 4})
    for policy in ALL_POLICIES:
        assert policy.select_node(gpu_only, _candidate(0)) is None, policy.name


def test_gpu_work_stays_unplaced_when_there_is_no_gpu_pool() -> None:
    cpu_only = ClusterState(capacity={"cpu-worker": 0})
    for policy in ALL_POLICIES:
        assert policy.select_node(cpu_only, _candidate(1)) is None, policy.name


# --- the GPU pool still behaves as it did -------------------------------------------


def test_gpu_pool_is_still_all_or_nothing() -> None:
    # 4 free in total but fragmented 2+2, and the CPU node must not rescue it.
    state = ClusterState(
        capacity={"gpu-a": 4, "gpu-b": 4, "cpu-worker": 0}, used={"gpu-a": 2, "gpu-b": 2}
    )
    for policy in ALL_POLICIES:
        assert policy.select_node(state, _candidate(3)) is None, policy.name


def test_bin_packing_still_prefers_the_tighter_gpu_node() -> None:
    state = ClusterState(capacity={"gpu-a": 4, "gpu-b": 4, "cpu-worker": 0}, used={"gpu-b": 2})
    assert FirstFit().select_node(state, _candidate(2)) == "gpu-a"
    assert BinPacking().select_node(state, _candidate(2)) == "gpu-b"


def test_reserving_cpu_work_does_not_consume_gpu_capacity() -> None:
    state = _mixed_fleet()
    node = FirstFit().select_node(state, _candidate(0))
    assert node is not None
    state.reserve(node, 0)
    # The GPU pool is untouched, and a second CPU workload can still land.
    assert state.free("gpu-a") == 4
    assert FirstFit().select_node(state, _candidate(0)) == "cpu-worker"


def test_sleeping_gpu_endpoint_stays_in_the_gpu_pool() -> None:
    """An endpoint submitted with `min_replicas: 0` asks for GPUs per replica but
    holds none until it wakes, so its footprint at placement is zero. Routing on
    the footprint would strand it in the CPU pool, unable to ever scale up."""
    state = _mixed_fleet()
    asleep = _candidate(0, requires_gpu=True)
    for policy in ALL_POLICIES:
        assert policy.select_node(state, asleep) in {"gpu-a", "gpu-b"}, policy.name


def test_a_sleeping_endpoint_fits_even_on_a_full_gpu_node() -> None:
    # Holding nothing, it needs no free capacity yet; the autoscaler's own clamp
    # is what stops it waking beyond what the node can give.
    full = ClusterState(capacity={"gpu-a": 4, "cpu-worker": 0}, used={"gpu-a": 4})
    assert FirstFit().select_node(full, _candidate(0, requires_gpu=True)) == "gpu-a"


def test_eligible_reports_the_right_pool() -> None:
    state = _mixed_fleet()
    assert state.eligible(0, requires_gpu=False) == ["cpu-worker"]
    assert state.eligible(1, requires_gpu=True) == ["gpu-a", "gpu-b"]
    assert state.eligible(0, requires_gpu=True) == ["gpu-a", "gpu-b"]


# --- control plane exclusion (needs Postgres) ----------------------------------------


class _Fleet:
    """Minimal ClusterPort: only list_nodes is reached by _build_cluster_state."""

    def __init__(self, nodes: list[NodeInfo]) -> None:
        self._nodes = nodes

    def list_nodes(self) -> list[NodeInfo]:
        return self._nodes

    def create_job(self, *a: Any, **k: Any) -> None: ...
    def create_deployment(self, *a: Any, **k: Any) -> None: ...
    def scale_deployment(self, *a: Any, **k: Any) -> None: ...
    def get_job_status(self, name: str, namespace: str) -> str:
        return "running"

    def is_kueue_workload_admitted(self, name: str, namespace: str) -> bool:
        return True

    def delete_kueue_workload(self, *a: Any, **k: Any) -> None: ...


def _node(name: str, gpus: int, *, ready: bool = True, control_plane: bool = False) -> NodeInfo:
    return NodeInfo(
        name=name,
        ready=ready,
        is_control_plane=control_plane,
        gpu_capacity=gpus,
        gpu_allocatable=gpus,
        cpu_capacity="16",
        memory_capacity="64Gi",
    )


@pytest.fixture()
def db() -> Any:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_cluster_state_admits_both_pools_but_never_the_control_plane(db: Session) -> None:
    fleet = _Fleet(
        [
            _node("kestrel-control-plane", 0, control_plane=True),
            _node("kwok-gpu-node-0", 4),
            _node("worker-0", 0),
            _node("worker-down", 0, ready=False),
        ]
    )
    state = build_cluster_state(db, fleet)

    # Assert on which nodes became candidates, which is what this function
    # decides. Free capacity is not asserted here: `used` comes from whatever is
    # actually running in the shared database, so folding it in would make this
    # test depend on unrelated rows.
    assert "kestrel-control-plane" not in state.capacity, (
        "tenant work must not run on the control plane"
    )
    assert "worker-down" not in state.capacity, "not-ready nodes are not candidates"
    assert state.capacity["worker-0"] == 0, "a GPU-less worker joins the CPU pool"
    assert state.capacity["kwok-gpu-node-0"] == 4, "a GPU node joins the GPU pool"
