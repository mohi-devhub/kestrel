"""Runway math. Pure functions, hand-built fixtures, no I/O at all."""

from decimal import Decimal

import pytest

from economics.runway import (
    budget_headroom_gpus,
    burn_rate,
    remaining_budget,
    risk_tier,
    runway_seconds,
    runway_status,
)

# --- burn_rate --------------------------------------------------------------------


@pytest.mark.parametrize(("gpus_held", "expected"), [(0, 0), (1, 1), (8, 8)])
def test_burn_rate_is_gpus_held(gpus_held: int, expected: int) -> None:
    assert burn_rate(gpus_held) == expected


def test_burn_rate_never_negative() -> None:
    assert burn_rate(-1) == 0


# --- remaining_budget ---------------------------------------------------------------


def test_no_budget_configured_is_unbounded() -> None:
    assert remaining_budget(None, used_gpu_seconds=Decimal(10_000)) is None


def test_remaining_budget_is_budget_minus_used() -> None:
    assert remaining_budget(1000, used_gpu_seconds=Decimal(400)) == Decimal(600)


def test_remaining_budget_can_go_negative() -> None:
    # A workload crossed the budget between the last usage read and now; the hard
    # block is QuotaEnforcer's job, not this function's.
    assert remaining_budget(1000, used_gpu_seconds=Decimal(1500)) == Decimal(-500)


# --- runway_seconds -----------------------------------------------------------------


def test_no_budget_is_infinite_runway() -> None:
    assert runway_seconds(None, rate=4) is None


def test_idle_tenant_has_infinite_runway_regardless_of_remaining_budget() -> None:
    assert runway_seconds(Decimal(50), rate=0) is None


def test_runway_is_remaining_over_rate() -> None:
    assert runway_seconds(Decimal(600), rate=2) == Decimal(300)


def test_exhausted_budget_is_zero_runway_not_negative() -> None:
    assert runway_seconds(Decimal(-500), rate=3) == Decimal(0)
    assert runway_seconds(Decimal(0), rate=3) == Decimal(0)


# --- runway_status --------------------------------------------------------------------


def test_status_bundles_the_full_picture() -> None:
    status = runway_status(gpu_second_budget=1000, used_gpu_seconds=Decimal(400), gpus_held=2)
    assert status.burn_rate_gpus == 2
    assert status.remaining_gpu_seconds == Decimal(600)
    assert status.runway_seconds == Decimal(300)
    assert status.has_budget is True
    assert status.is_exhausted is False


def test_status_for_unbudgeted_tenant() -> None:
    status = runway_status(gpu_second_budget=None, used_gpu_seconds=Decimal(9_999), gpus_held=4)
    assert status.has_budget is False
    assert status.runway_seconds is None
    assert status.is_exhausted is False


def test_status_reports_exhausted_once_used_reaches_budget() -> None:
    status = runway_status(gpu_second_budget=100, used_gpu_seconds=Decimal(100), gpus_held=1)
    assert status.is_exhausted is True
    assert status.runway_seconds == Decimal(0)


def test_status_for_idle_tenant_near_budget() -> None:
    # Nothing running right now: the budget isn't draining, so runway is infinite
    # even though remaining budget is thin.
    status = runway_status(gpu_second_budget=1000, used_gpu_seconds=Decimal(990), gpus_held=0)
    assert status.remaining_gpu_seconds == Decimal(10)
    assert status.runway_seconds is None
    assert status.is_exhausted is False


# --- risk_tier ------------------------------------------------------------------

THRESHOLDS = (Decimal(300), Decimal(1800), Decimal(21600))  # 5min / 30min / 6h


def test_no_budget_is_always_safe_tier() -> None:
    assert risk_tier(None, THRESHOLDS) == 0


def test_ample_runway_is_safe_tier() -> None:
    assert risk_tier(Decimal(100_000), THRESHOLDS) == 0


@pytest.mark.parametrize(
    ("runway", "expected_tier"),
    [
        (Decimal(21600), 1),  # exactly on a boundary falls into the riskier tier
        (Decimal(10_000), 1),
        (Decimal(1800), 2),
        (Decimal(600), 2),
        (Decimal(300), 3),
        (Decimal(60), 3),
        (Decimal(0), 3),
    ],
)
def test_risk_tier_climbs_as_runway_shrinks(runway: Decimal, expected_tier: int) -> None:
    assert risk_tier(runway, THRESHOLDS) == expected_tier


def test_risk_tier_uses_the_default_thresholds_when_unspecified() -> None:
    assert risk_tier(Decimal(60)) == 3
    assert risk_tier(Decimal(100_000)) == 0


# --- budget_headroom_gpus ---------------------------------------------------------


def test_no_budget_is_unconstrained_headroom() -> None:
    assert budget_headroom_gpus(None, current_burn_gpus=4, horizon_seconds=300) is None


def test_headroom_is_sustainable_total_minus_current_burn() -> None:
    # 1200 GPU-seconds remaining, a 300s horizon: sustainable total is 4 GPUs.
    # Already burning 1 -> 3 more GPUs affordable.
    assert budget_headroom_gpus(Decimal(1200), current_burn_gpus=1, horizon_seconds=300) == 3


def test_headroom_floors_fractional_gpus() -> None:
    # Sustainable total is 3.5 GPUs; burning 1 -> 2.5 extra, floored to 2.
    assert budget_headroom_gpus(Decimal(1050), current_burn_gpus=1, horizon_seconds=300) == 2


def test_headroom_is_zero_not_negative_when_already_over_budget() -> None:
    assert budget_headroom_gpus(Decimal(100), current_burn_gpus=10, horizon_seconds=300) == 0
    assert budget_headroom_gpus(Decimal(-500), current_burn_gpus=0, horizon_seconds=300) == 0


def test_zero_horizon_is_zero_headroom() -> None:
    assert budget_headroom_gpus(Decimal(10_000), current_burn_gpus=0, horizon_seconds=0) == 0
