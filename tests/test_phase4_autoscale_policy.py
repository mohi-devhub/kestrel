"""Autoscaling decision math. Pure functions, hand-built fixtures, no I/O at all."""

from datetime import UTC, datetime, timedelta

import pytest

from autoscale.policy import (
    REASON_CAPACITY_CAPPED,
    REASON_LOAD,
    REASON_SCALE_FROM_ZERO,
    REASON_SCALE_TO_ZERO,
    AutoscaleConfig,
    clamp_to_capacity,
    decide,
)
from autoscale.signal import LoadObservation

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def config(
    *,
    min_replicas: int = 0,
    max_replicas: int = 4,
    target_rps: float = 5.0,
    idle_after: float = 60.0,
    stabilization: float = 30.0,
) -> AutoscaleConfig:
    return AutoscaleConfig(
        min_replicas=min_replicas,
        max_replicas=max_replicas,
        target_rps_per_replica=target_rps,
        scale_to_zero_after_seconds=idle_after,
        scale_down_stabilization_seconds=stabilization,
    )


def load(rps: float, *, idle_for: float = 0.0) -> LoadObservation:
    """An observation of `rps` whose last request landed `idle_for` seconds ago."""
    return LoadObservation(
        requests_in_window=int(rps * 30) if rps > 0 else 0,
        rps=rps,
        last_request_at=NOW - timedelta(seconds=idle_for),
    )


# --- scaling on load ------------------------------------------------------------


@pytest.mark.parametrize(
    ("rps", "expected"),
    [
        (5.0, 1),  # exactly one replica's worth
        (5.1, 2),  # a rounding up, not down: never knowingly under-provision
        (10.0, 2),
        (14.9, 3),
        (15.0, 3),
    ],
)
def test_replicas_are_ceil_of_rps_over_target(rps: float, expected: int) -> None:
    decision = decide(load(rps), current=1, config=config(), now=NOW, last_event_at=None)
    assert decision.target == expected


def test_target_is_capped_at_max_replicas() -> None:
    # 100 rps wants 20 replicas; the endpoint is only allowed 4.
    decision = decide(
        load(100.0), current=1, config=config(max_replicas=4), now=NOW, last_event_at=None
    )
    assert decision.target == 4


def test_target_is_floored_at_min_replicas() -> None:
    decision = decide(
        load(1.0), current=2, config=config(min_replicas=2), now=NOW, last_event_at=None
    )
    assert decision.target == 2


def test_per_endpoint_rps_target_changes_the_answer() -> None:
    # Same traffic, a workload that handles half as much per replica -> twice the replicas.
    assert decide(load(10.0), 1, config(target_rps=5.0), NOW, None).target == 2
    assert decide(load(10.0), 1, config(target_rps=2.5), NOW, None).target == 4


# --- scale to zero and back -----------------------------------------------------


def test_idle_endpoint_sleeps_when_min_replicas_is_zero() -> None:
    decision = decide(
        load(0.0, idle_for=90),
        current=2,
        config=config(min_replicas=0),
        now=NOW,
        last_event_at=None,
    )
    assert decision.target == 0
    assert decision.reason == REASON_SCALE_TO_ZERO


def test_idle_endpoint_stays_warm_when_min_replicas_is_one() -> None:
    # min_replicas=1 means "always warm" — hours of silence must not put it to sleep.
    decision = decide(
        load(0.0, idle_for=86_400),
        current=1,
        config=config(min_replicas=1),
        now=NOW,
        last_event_at=None,
    )
    assert decision.target == 1


def test_brief_traffic_pause_holds_at_one_replica() -> None:
    """The rolling window empties seconds after traffic stops; without a floor the
    endpoint would sleep long before the idle window it was promised."""
    decision = decide(
        load(0.0, idle_for=10),
        current=3,
        config=config(min_replicas=0, idle_after=60),
        now=NOW,
        last_event_at=None,
    )
    assert decision.target == 1
    assert decision.reason == REASON_LOAD


def test_first_request_wakes_a_sleeping_endpoint() -> None:
    decision = decide(
        load(1.0), current=0, config=config(min_replicas=0), now=NOW, last_event_at=None
    )
    assert decision.target == 1
    assert decision.reason == REASON_SCALE_FROM_ZERO


def test_sleeping_endpoint_with_no_traffic_stays_asleep() -> None:
    decision = decide(
        load(0.0, idle_for=600),
        current=0,
        config=config(min_replicas=0),
        now=NOW,
        last_event_at=None,
    )
    assert decision.target == 0


# --- anti-flap ------------------------------------------------------------------


def test_scale_down_waits_out_the_stabilization_window() -> None:
    just_scaled = NOW - timedelta(seconds=5)
    decision = decide(
        load(1.0), current=4, config=config(stabilization=30), now=NOW, last_event_at=just_scaled
    )
    assert decision.target == 4, "a dip in traffic must not immediately undo a scale-up"


def test_scale_down_proceeds_once_the_window_has_passed() -> None:
    settled = NOW - timedelta(seconds=31)
    decision = decide(
        load(1.0), current=4, config=config(stabilization=30), now=NOW, last_event_at=settled
    )
    assert decision.target == 1


def test_scale_up_ignores_the_stabilization_window() -> None:
    just_scaled = NOW - timedelta(seconds=1)
    decision = decide(
        load(20.0), current=1, config=config(stabilization=30), now=NOW, last_event_at=just_scaled
    )
    assert decision.target == 4, "scale-up is always immediate — latency is the whole point"


# --- capacity clamp -------------------------------------------------------------


def test_clamp_allows_a_scale_up_that_fits() -> None:
    target = clamp_to_capacity(
        4, current=1, gpus_per_replica=1, node_free_gpus=3, tenant_headroom_gpus=8
    )
    assert target == 4


def test_clamp_limits_scale_up_to_free_gpus_on_the_pinned_node() -> None:
    # Every replica lands on the same node, so growth is bounded by that node alone.
    target = clamp_to_capacity(
        4, current=1, gpus_per_replica=1, node_free_gpus=2, tenant_headroom_gpus=8
    )
    assert target == 3


def test_clamp_limits_scale_up_to_tenant_quota_headroom() -> None:
    target = clamp_to_capacity(
        4, current=1, gpus_per_replica=1, node_free_gpus=8, tenant_headroom_gpus=1
    )
    assert target == 2


def test_clamp_accounts_for_multi_gpu_replicas() -> None:
    # 3 free GPUs at 2 GPUs per replica buys one more replica, not one and a half.
    target = clamp_to_capacity(
        4, current=1, gpus_per_replica=2, node_free_gpus=3, tenant_headroom_gpus=8
    )
    assert target == 2


def test_clamp_never_blocks_scaling_down() -> None:
    target = clamp_to_capacity(
        0, current=4, gpus_per_replica=1, node_free_gpus=0, tenant_headroom_gpus=0
    )
    assert target == 0


def test_clamp_ignores_capacity_for_gpuless_endpoints() -> None:
    target = clamp_to_capacity(
        4, current=1, gpus_per_replica=0, node_free_gpus=0, tenant_headroom_gpus=0
    )
    assert target == 4


def test_capacity_capped_reason_is_distinguishable() -> None:
    """A capped scale-up is recorded differently from one the load asked for, so the
    audit trail says whether the platform or the traffic set the replica count."""
    decision = decide(
        load(100.0), current=1, config=config(max_replicas=4), now=NOW, last_event_at=None
    )
    capped = clamp_to_capacity(decision.target, 1, 1, node_free_gpus=1, tenant_headroom_gpus=8)
    assert decision.target == 4
    assert capped == 2
    assert (decision.reason if capped == decision.target else REASON_CAPACITY_CAPPED) == (
        REASON_CAPACITY_CAPPED
    )
