"""GPU-footprint accounting shared by the reconcile loop and the cluster read API."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from db.models import Workload


def effective_gpus(
    kind: str, gpus_requested: int, spec: dict[str, Any], replicas: int | None = None
) -> int:
    """Total GPUs a workload occupies on its node.

    A Deployment's pod template pins every replica to the same node, so an
    endpoint's footprint is per-replica GPUs x replicas, not the raw request.
    `replicas` is the live count once the autoscaler owns it; before placement
    there isn't one yet, so the submitted min_replicas stands in.
    """
    if kind == "endpoint":
        count = replicas if replicas is not None else int(spec.get("min_replicas", 1))
        return gpus_requested * count
    return gpus_requested


def workload_gpus(w: Workload) -> int:
    """Effective GPU footprint of a persisted workload row.

    The single place that decides an endpoint's live footprint: node accounting,
    tenant quota, and metering all go through here, so a scaled endpoint can't be
    truthful in one of them and stale in another.
    """
    return effective_gpus(w.kind, w.gpus_requested, w.spec, w.replicas)


def used_gpus_by_node(running: Iterable[Workload]) -> dict[str, int]:
    """Aggregate GPU usage per node over currently-running workload rows."""
    used: dict[str, int] = {}
    for w in running:
        if w.node_name is None:
            continue
        used[w.node_name] = used.get(w.node_name, 0) + workload_gpus(w)
    return used
