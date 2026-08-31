"""The three concrete placement policies and their registry."""

from __future__ import annotations

from scheduler.policy import ClusterState, PlacementCandidate, PlacementPolicy


class FirstFit(PlacementPolicy):
    """First node (stable name order) with enough free GPUs."""

    name = "first_fit"

    def select_node(self, state: ClusterState, candidate: PlacementCandidate) -> str | None:
        for node in state.nodes():
            if state.free(node) >= candidate.gpus_needed:
                return node
        return None


class BinPacking(PlacementPolicy):
    """Tightest-fitting node: pack partially-used nodes first, keeping whole
    nodes free for large multi-GPU asks."""

    name = "bin_packing"

    def select_node(self, state: ClusterState, candidate: PlacementCandidate) -> str | None:
        fitting = [n for n in state.nodes() if state.free(n) >= candidate.gpus_needed]
        if not fitting:
            return None
        return min(fitting, key=lambda n: (state.free(n), n))


class Priority(FirstFit):
    """Higher-priority workloads get first pick of capacity each tick; node
    selection itself is first-fit."""

    name = "priority"

    def order(self, candidates: list[PlacementCandidate]) -> list[PlacementCandidate]:
        return sorted(candidates, key=lambda c: (-c.priority, c.admitted_at))


POLICIES: dict[str, PlacementPolicy] = {
    policy.name: policy for policy in (FirstFit(), BinPacking(), Priority())
}


def get_policy(name: str) -> PlacementPolicy:
    try:
        return POLICIES[name]
    except KeyError:
        raise ValueError(f"unknown placement policy: {name!r}") from None
