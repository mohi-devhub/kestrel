"""PlacementPolicy interface: given admitted workloads and per-node free GPUs, pick nodes.

Kueue owns *whether/when* a workload may run (admission, queueing, tenant quota).
These policies own *where* — which node an admitted workload lands on.

The GPU accounting here is the control plane's own, derived from its database,
not from Kubernetes allocatable: placements bypass kube-scheduler by setting
nodeName directly, and KWOK's fake kubelets don't enforce resource fit, so K8s
never learns how full a node "really" is.

Everything in this module is pure (no DB/K8s types) so policies are unit-testable
with hand-built fixtures.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass
class ClusterState:
    """Per-node GPU capacity and usage, mutable within one reconcile tick.

    `reserve` lets the reconcile loop claim capacity as it places candidates,
    so several placements in one pass can't double-book a node.
    """

    capacity: dict[str, int]
    used: dict[str, int] = field(default_factory=dict)

    def nodes(self) -> list[str]:
        return sorted(self.capacity)

    def free(self, node: str) -> int:
        return self.capacity[node] - self.used.get(node, 0)

    def reserve(self, node: str, gpus: int) -> None:
        self.used[node] = self.used.get(node, 0) + gpus


@dataclass(frozen=True)
class PlacementCandidate:
    """An admitted-but-unplaced workload, reduced to what placement needs.

    `tenant_runway_seconds` is the owning tenant's budget runway at the moment
    this tick's candidates were built (None: no budget configured, or currently
    idle — see `economics.runway.runway_seconds`). Only `RunwayFair` reads it;
    every other policy ignores the field entirely.
    """

    workload_id: uuid.UUID
    gpus_needed: int
    priority: int
    admitted_at: datetime
    tenant_runway_seconds: Decimal | None = None


class PlacementPolicy(ABC):
    name: str

    def order(
        self, candidates: list[PlacementCandidate], now: datetime
    ) -> list[PlacementCandidate]:
        """Order in which candidates get to claim capacity this tick (default FIFO).

        `now` is unused by the default and by `Priority` — it exists so a policy
        like `RunwayFair` can measure how long a candidate has waited without
        reading the wall clock itself, the same reason `autoscale.policy.decide`
        takes `now` as an argument instead of calling `datetime.now()`.
        """
        return sorted(candidates, key=lambda c: c.admitted_at)

    @abstractmethod
    def select_node(self, state: ClusterState, candidate: PlacementCandidate) -> str | None:
        """A node with room for the candidate's full GPU ask on it alone (all-or-nothing),
        or None to leave the candidate admitted-but-unplaced until capacity frees up."""
