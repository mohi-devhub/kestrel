"""The concrete placement policies and their registry."""

from __future__ import annotations

from datetime import datetime

from economics.runway import risk_tier
from scheduler.policy import ClusterState, PlacementCandidate, PlacementPolicy


class FirstFit(PlacementPolicy):
    """First eligible node in stable name order."""

    name = "first_fit"

    def select_node(self, state: ClusterState, candidate: PlacementCandidate) -> str | None:
        return next(iter(state.eligible(candidate.gpus_needed, candidate.requires_gpu)), None)


class BinPacking(PlacementPolicy):
    """Tightest-fitting node: pack partially-used nodes first, keeping whole
    nodes free for large multi-GPU asks."""

    name = "bin_packing"

    def select_node(self, state: ClusterState, candidate: PlacementCandidate) -> str | None:
        fitting = state.eligible(candidate.gpus_needed, candidate.requires_gpu)
        if not fitting:
            return None
        return min(fitting, key=lambda n: (state.free(n), n))


class Priority(FirstFit):
    """Higher-priority workloads get first pick of capacity each tick; node
    selection itself is first-fit."""

    name = "priority"

    def order(
        self, candidates: list[PlacementCandidate], now: datetime
    ) -> list[PlacementCandidate]:
        return sorted(candidates, key=lambda c: (-c.priority, c.admitted_at))


# How long a candidate may be held behind healthier-runway tenants before
# RunwayFair stops discounting it: past this, it orders as if risk-tier 0
# regardless of actual runway. Runway can delay a placement, never lock it out
# indefinitely — Kueue admission and QuotaEnforcer's hard budget block are the
# only things that can do that, and neither is affected by this policy.
RUNWAY_STARVATION_FLOOR_SECONDS = 300.0


class RunwayFair(FirstFit):
    """Node selection is plain first-fit; ordering additionally weighs tenant
    budget runway.

    Explicit priority still wins outright. Among equal priority, tenants with
    healthier runway (a safer risk tier — see `economics.runway.risk_tier`)
    drain ahead of tenants close to exhausting their budget: the same "yield
    now rather than burn a slot you may not finish" tradeoff a cloud provider
    makes when throttling a near-quota customer, computed here from the
    tenant's own metered usage instead of a manual flag.
    """

    name = "runway_fair"

    def order(
        self, candidates: list[PlacementCandidate], now: datetime
    ) -> list[PlacementCandidate]:
        def sort_key(c: PlacementCandidate) -> tuple[int, int, datetime]:
            waited = (now - c.admitted_at).total_seconds()
            tier = (
                0
                if waited >= RUNWAY_STARVATION_FLOOR_SECONDS
                else risk_tier(c.tenant_runway_seconds)
            )
            return (-c.priority, tier, c.admitted_at)

        return sorted(candidates, key=sort_key)


POLICIES: dict[str, PlacementPolicy] = {
    policy.name: policy for policy in (FirstFit(), BinPacking(), Priority(), RunwayFair())
}


def get_policy(name: str) -> PlacementPolicy:
    try:
        return POLICIES[name]
    except KeyError:
        raise ValueError(f"unknown placement policy: {name!r}") from None
