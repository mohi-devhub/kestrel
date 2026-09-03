"""How much runway a tenant has left, as pure math.

Runway is the same signal a budget line gives a human — how long until the money
runs out at the current rate — turned into a scheduling input. Placement
(`scheduler`'s planned `RunwayFair` policy) and autoscaling (`clamp_to_capacity`
in `autoscale/policy.py`) both read it so a near-exhausted tenant's own workloads
get throttled before `quota.QuotaEnforcer.is_over_budget` hard-blocks them, and
so they don't crowd out a healthier tenant on the way there.

Nothing here touches the database, Redis, or Kubernetes — every rule below is
exercised by hand-built fixtures in tests/test_phase5_runway.py. Callers pass in
already-fetched values (`gpu_second_budget` from `Tenant`, `used_gpu_seconds` from
`MeteringStore.usage_for`, `gpus_held` from `QuotaEnforcer.running_gpus_by_tenant`)
the same way `autoscale.policy.decide` takes a `LoadObservation` instead of
querying Redis itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# Risk-tier boundaries, ascending, in seconds: 5 minutes / 30 minutes / 6 hours.
# `risk_tier` counts down from the top as runway drops below each one, so a
# tenant closer to empty always lands in a *higher* tier. Tuned for a demo
# where budgets are small; a real deployment would pass its own thresholds.
DEFAULT_RISK_THRESHOLDS: tuple[Decimal, ...] = (Decimal(300), Decimal(1800), Decimal(21600))


@dataclass(frozen=True)
class RunwayStatus:
    """A tenant's budget position at a point in time.

    `remaining_gpu_seconds` and `runway_seconds` are both None for a tenant with
    no `gpu_second_budget` configured — unbudgeted tenants have infinite runway
    and are never throttled or reordered on this signal, only on quota/priority
    as today.
    """

    burn_rate_gpus: int
    remaining_gpu_seconds: Decimal | None
    runway_seconds: Decimal | None

    @property
    def has_budget(self) -> bool:
        return self.remaining_gpu_seconds is not None

    @property
    def is_exhausted(self) -> bool:
        """True once remaining budget has hit zero — QuotaEnforcer.is_over_budget
        blocks new submissions at this point; runway is reported as zero, not
        negative, since there's nothing left to rank a placement decision on."""
        return self.remaining_gpu_seconds is not None and self.remaining_gpu_seconds <= 0


def burn_rate(gpus_held: int) -> int:
    """GPU-seconds consumed per real second, right now.

    A tenant holding N GPUs accrues N GPU-seconds per elapsed second by
    definition (`gpu_seconds = gpus * duration` in `metering/store.py`) — burn
    rate is that same quantity, named for its role as a rate rather than a
    footprint. Never negative: a workload can't hold negative GPUs.
    """
    return max(0, gpus_held)


def remaining_budget(gpu_second_budget: int | None, used_gpu_seconds: Decimal) -> Decimal | None:
    """Budget left, in GPU-seconds. None if the tenant has no budget configured.

    Can go negative between a workload crossing the budget and the next
    admission check closing the door — callers that need "is this tenant over
    budget" as a boolean should still ask `QuotaEnforcer.is_over_budget`; this
    stays a plain subtraction so `runway_seconds` can clamp it at zero itself.
    """
    if gpu_second_budget is None:
        return None
    return Decimal(gpu_second_budget) - used_gpu_seconds


def runway_seconds(remaining: Decimal | None, rate: int) -> Decimal | None:
    """Real seconds until `remaining` hits zero at `rate` GPU-seconds/second.

    None means infinite runway: no budget configured (`remaining` is None), or
    nothing burning it right now (`rate` is zero) — an idle tenant's clock isn't
    running, however little budget remains. Already-exhausted budget returns
    zero rather than a negative number: past empty, there's no runway left to
    rank a placement decision on, only degree of overrun.
    """
    if remaining is None:
        return None
    if remaining <= 0:
        return Decimal(0)
    if rate <= 0:
        return None
    return remaining / Decimal(rate)


def runway_status(
    gpu_second_budget: int | None,
    used_gpu_seconds: Decimal,
    gpus_held: int,
) -> RunwayStatus:
    """The full runway picture for one tenant at one instant."""
    rate = burn_rate(gpus_held)
    remaining = remaining_budget(gpu_second_budget, used_gpu_seconds)
    return RunwayStatus(
        burn_rate_gpus=rate,
        remaining_gpu_seconds=remaining,
        runway_seconds=runway_seconds(remaining, rate),
    )


def budget_headroom_gpus(
    remaining_gpu_seconds: Decimal | None, current_burn_gpus: int, horizon_seconds: float
) -> int | None:
    """Extra GPUs the tenant's remaining budget can sustain for at least one
    `horizon_seconds` without hitting zero runway.

    Mirrors `clamp_to_capacity`'s `node_free_gpus`/`tenant_headroom_gpus`: a
    limit on how much a scale-*up* may grow by, not an absolute cap — it never
    shrinks what's already running. None means unconstrained (no budget
    configured), the same "infinite runway" convention `runway_seconds` uses.
    Already-thin or exhausted budget returns 0, not negative.
    """
    if remaining_gpu_seconds is None:
        return None
    if horizon_seconds <= 0:
        return 0
    sustainable_total = remaining_gpu_seconds / Decimal(str(horizon_seconds))
    extra = sustainable_total - Decimal(current_burn_gpus)
    return max(0, int(extra))


def risk_tier(
    runway: Decimal | None, thresholds: tuple[Decimal, ...] = DEFAULT_RISK_THRESHOLDS
) -> int:
    """Discretize runway into an ordering tier: 0 is safe, higher is closer to empty.

    `RunwayFair` sorts candidates on this rather than raw seconds so a momentary
    swing in burn rate can't reorder the queue mid-tier — the same reason
    `autoscale.policy.decide` waits out a stabilization window before scaling
    down instead of reacting to every dip. `thresholds` must be ascending;
    infinite runway (`None` — no budget, or currently idle) is always tier 0.
    """
    if runway is None:
        return 0
    tier_count = len(thresholds)
    for i, bound in enumerate(thresholds):
        if runway <= bound:
            return tier_count - i
    return 0
