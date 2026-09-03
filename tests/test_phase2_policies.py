"""Pure unit tests for the placement policies — no cluster, no DB, no Redis."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from scheduler.policies import BinPacking, FirstFit, Priority, get_policy
from scheduler.policy import ClusterState, PlacementCandidate

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _candidate(gpus: int, priority: int = 0, admitted_offset: int = 0) -> PlacementCandidate:
    return PlacementCandidate(
        workload_id=uuid.uuid4(),
        gpus_needed=gpus,
        priority=priority,
        admitted_at=T0 + timedelta(seconds=admitted_offset),
    )


def test_first_fit_picks_first_fitting_node_by_name() -> None:
    state = ClusterState(capacity={"node-b": 4, "node-a": 4}, used={"node-a": 3})
    assert FirstFit().select_node(state, _candidate(1)) == "node-a"
    assert FirstFit().select_node(state, _candidate(2)) == "node-b"


def test_no_node_fits_returns_none() -> None:
    state = ClusterState(capacity={"node-a": 4, "node-b": 4}, used={"node-a": 3, "node-b": 3})
    for policy in (FirstFit(), BinPacking(), Priority()):
        assert policy.select_node(state, _candidate(2)) is None


def test_bin_packing_picks_tightest_fit_where_first_fit_differs() -> None:
    # node-a is wide open, node-b is partially used but still fits the ask.
    state = ClusterState(capacity={"node-a": 4, "node-b": 4}, used={"node-b": 2})
    candidate = _candidate(2)
    assert FirstFit().select_node(state, candidate) == "node-a"
    assert BinPacking().select_node(state, candidate) == "node-b"


def test_bin_packing_keeps_a_whole_node_free_for_a_big_ask() -> None:
    state = ClusterState(capacity={"node-a": 4, "node-b": 4}, used={"node-a": 1})
    # Packing the 2-GPU ask onto the partially-used node...
    node = BinPacking().select_node(state, _candidate(2))
    assert node == "node-a"
    state.reserve(node, 2)
    # ...leaves node-b whole for a full-node ask that FirstFit's spread would have broken.
    assert BinPacking().select_node(state, _candidate(4)) == "node-b"


def test_multi_gpu_is_all_or_nothing() -> None:
    # 4 GPUs free in total, but fragmented 2+2 — a 3-GPU ask must not be split.
    state = ClusterState(capacity={"node-a": 4, "node-b": 4}, used={"node-a": 2, "node-b": 2})
    for policy in (FirstFit(), BinPacking(), Priority()):
        assert policy.select_node(state, _candidate(3)) is None


def test_default_order_is_fifo_by_admitted_at() -> None:
    late = _candidate(1, admitted_offset=10)
    early = _candidate(1, admitted_offset=0)
    assert FirstFit().order([late, early], T0) == [early, late]


def test_priority_orders_high_priority_first_fifo_within_priority() -> None:
    low_early = _candidate(1, priority=0, admitted_offset=0)
    high_late = _candidate(1, priority=10, admitted_offset=10)
    high_early = _candidate(1, priority=10, admitted_offset=5)
    ordered = Priority().order([low_early, high_late, high_early], T0)
    assert ordered == [high_early, high_late, low_early]


def test_priority_wins_the_last_slot() -> None:
    # One free slot; the higher-priority candidate arrived later but must get it.
    state = ClusterState(capacity={"node-a": 4}, used={"node-a": 3})
    low = _candidate(1, priority=0, admitted_offset=0)
    high = _candidate(1, priority=5, admitted_offset=10)
    policy = Priority()

    placed: dict[uuid.UUID, str | None] = {}
    for candidate in policy.order([low, high], T0):
        node = policy.select_node(state, candidate)
        if node is not None:
            state.reserve(node, candidate.gpus_needed)
        placed[candidate.workload_id] = node

    assert placed[high.workload_id] == "node-a"
    assert placed[low.workload_id] is None


def test_in_tick_reservation_prevents_double_booking() -> None:
    state = ClusterState(capacity={"node-a": 4})
    first = FirstFit().select_node(state, _candidate(3))
    assert first == "node-a"
    state.reserve(first, 3)
    assert FirstFit().select_node(state, _candidate(3)) is None


def test_get_policy_registry() -> None:
    assert get_policy("first_fit").name == "first_fit"
    assert get_policy("bin_packing").name == "bin_packing"
    assert get_policy("priority").name == "priority"
    assert get_policy("runway_fair").name == "runway_fair"
    with pytest.raises(ValueError):
        get_policy("does-not-exist")
