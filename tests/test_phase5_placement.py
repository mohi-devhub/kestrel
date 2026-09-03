"""RunwayFair ordering. Pure unit tests — no cluster, no DB, no Redis."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from scheduler.policies import RUNWAY_STARVATION_FLOOR_SECONDS, RunwayFair
from scheduler.policy import PlacementCandidate

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _candidate(
    *,
    priority: int = 0,
    admitted_offset: float = 0,
    runway: Decimal | None = None,
) -> PlacementCandidate:
    return PlacementCandidate(
        workload_id=uuid.uuid4(),
        gpus_needed=1,
        priority=priority,
        admitted_at=T0 + timedelta(seconds=admitted_offset),
        tenant_runway_seconds=runway,
    )


def test_healthy_runway_drains_ahead_of_near_exhausted() -> None:
    safe = _candidate(runway=Decimal(100_000))  # far outside any tier
    near_exhausted = _candidate(runway=Decimal(60))  # inside the 5-minute tier
    ordered = RunwayFair().order([near_exhausted, safe], T0)
    assert ordered == [safe, near_exhausted]


def test_unbudgeted_tenant_is_treated_as_safe() -> None:
    unbudgeted = _candidate(runway=None)
    near_exhausted = _candidate(runway=Decimal(60))
    ordered = RunwayFair().order([near_exhausted, unbudgeted], T0)
    assert ordered == [unbudgeted, near_exhausted]


def test_explicit_priority_still_wins_outright() -> None:
    # Higher priority but nearly out of runway must still beat a safe low-priority one.
    urgent_and_thin = _candidate(priority=10, runway=Decimal(10))
    low_priority_safe = _candidate(priority=0, runway=Decimal(100_000))
    ordered = RunwayFair().order([low_priority_safe, urgent_and_thin], T0)
    assert ordered == [urgent_and_thin, low_priority_safe]


def test_fifo_tiebreak_within_the_same_tier() -> None:
    early = _candidate(runway=Decimal(100_000), admitted_offset=0)
    late = _candidate(runway=Decimal(90_000), admitted_offset=10)
    ordered = RunwayFair().order([late, early], T0)
    assert ordered == [early, late]


def test_starvation_floor_promotes_a_long_waiting_candidate() -> None:
    now = T0 + timedelta(seconds=RUNWAY_STARVATION_FLOOR_SECONDS + 1)
    stuck = _candidate(runway=Decimal(1), admitted_offset=0)  # waited past the floor
    fresh_and_safe = _candidate(runway=Decimal(100_000), admitted_offset=200)
    ordered = RunwayFair().order([fresh_and_safe, stuck], now)
    assert ordered == [stuck, fresh_and_safe]


def test_just_under_the_floor_is_still_deprioritized() -> None:
    now = T0 + timedelta(seconds=RUNWAY_STARVATION_FLOOR_SECONDS - 1)
    thin = _candidate(runway=Decimal(1), admitted_offset=0)
    safe = _candidate(runway=Decimal(100_000), admitted_offset=0)
    ordered = RunwayFair().order([thin, safe], now)
    assert ordered == [safe, thin]


def test_node_selection_is_plain_first_fit() -> None:
    from scheduler.policy import ClusterState

    state = ClusterState(capacity={"node-b": 4, "node-a": 4}, used={"node-a": 3})
    assert RunwayFair().select_node(state, _candidate(runway=Decimal(1))) == "node-a"
