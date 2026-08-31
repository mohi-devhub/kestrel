"""GPU-footprint accounting shared by the reconcile loop and the cluster read API."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from db.models import Workload


def effective_gpus(kind: str, gpus_requested: int, spec: dict[str, Any]) -> int:
    """Total GPUs a workload occupies on its node.

    A Deployment's pod template pins every replica to the same node, so an
    endpoint's footprint is per-replica GPUs x replicas, not the raw request.
    """
    if kind == "endpoint":
        return gpus_requested * int(spec.get("min_replicas", 1))
    return gpus_requested


def used_gpus_by_node(running: Iterable[Workload]) -> dict[str, int]:
    """Aggregate GPU usage per node over currently-running workload rows."""
    used: dict[str, int] = {}
    for w in running:
        if w.node_name is None:
            continue
        used[w.node_name] = used.get(w.node_name, 0) + effective_gpus(
            w.kind, w.gpus_requested, w.spec
        )
    return used
