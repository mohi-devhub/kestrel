"""How many replicas an endpoint should have, as pure math.

Two stages, deliberately separated the way admission and placement are in
`quota/enforcer.py`: `decide` says what the *load* wants, `clamp_to_capacity` says
what the cluster and the tenant's quota will actually allow. Load decides what you
want; capacity decides what you get.

Nothing here touches the database, Redis, or Kubernetes — every rule below is
exercised by hand-built fixtures in tests/test_phase4_autoscale_policy.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from autoscale.signal import LoadObservation

# Why a replica count changed. Recorded on every autoscale_events row.
REASON_LOAD = "load"
REASON_SCALE_TO_ZERO = "scale_to_zero"
REASON_SCALE_FROM_ZERO = "scale_from_zero"
REASON_CAPACITY_CAPPED = "capacity_capped"


@dataclass(frozen=True)
class AutoscaleConfig:
    min_replicas: int
    max_replicas: int
    target_rps_per_replica: float
    scale_to_zero_after_seconds: float
    scale_down_stabilization_seconds: float

    @property
    def scale_to_zero_enabled(self) -> bool:
        """Only an endpoint submitted with min_replicas=0 may sleep — Knative's
        minScale semantics. min_replicas=1 means "always warm", and is honoured
        even when the endpoint has been idle for hours."""
        return self.min_replicas == 0


@dataclass(frozen=True)
class Decision:
    target: int
    reason: str


def decide(
    obs: LoadObservation,
    current: int,
    config: AutoscaleConfig,
    now: datetime,
    last_event_at: datetime | None,
) -> Decision:
    """Desired replica count for the observed load.

    Scale-up is immediate. Scale-down waits out a stabilization window measured
    from the endpoint's last replica change, so a momentary dip can't flap it down
    and straight back up.
    """
    idle = obs.idle_seconds(now) >= config.scale_to_zero_after_seconds
    asleep_allowed = config.scale_to_zero_enabled and (idle or current == 0)

    wanted = math.ceil(obs.rps / config.target_rps_per_replica) if obs.rps > 0 else 0
    # A warm endpoint whose traffic has merely paused holds at one replica until
    # the idle window elapses; without this floor it would sleep the instant the
    # rolling window emptied, seconds after the last request.
    floor = 0 if asleep_allowed else max(config.min_replicas, 1)
    target = max(floor, min(config.max_replicas, wanted))

    if target == 0 and current > 0:
        reason = REASON_SCALE_TO_ZERO
    elif current == 0 and target > 0:
        reason = REASON_SCALE_FROM_ZERO
    else:
        reason = REASON_LOAD

    if target < current and not _may_scale_down(now, last_event_at, config):
        return Decision(target=current, reason=reason)
    return Decision(target=target, reason=reason)


def _may_scale_down(
    now: datetime, last_event_at: datetime | None, config: AutoscaleConfig
) -> bool:
    if last_event_at is None:
        return True
    return (now - last_event_at).total_seconds() >= config.scale_down_stabilization_seconds


def clamp_to_capacity(
    target: int,
    current: int,
    gpus_per_replica: int,
    node_free_gpus: int,
    tenant_headroom_gpus: int,
) -> int:
    """Limit a scale-up to the GPUs actually available to this endpoint.

    Every replica of a Deployment lands on the same node (the pod template pins
    nodeName), so growing means finding room on *that* node — and staying inside
    the tenant's concurrent-GPU quota, the same gate placement applies. Scaling
    down or holding needs nothing, so it always passes.
    """
    if target <= current or gpus_per_replica <= 0:
        return target
    affordable_gpus = max(0, min(node_free_gpus, tenant_headroom_gpus))
    return min(target, current + affordable_gpus // gpus_per_replica)
