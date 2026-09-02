"""The load signal the autoscaler reacts to.

KWOK's fake pods run no container and serve no traffic, so there is no request
stream for the control plane to observe directly. Instead the serving layer
*reports* what it handled — the same seam Knative uses, where a queue-proxy
sidecar pushes concurrency to the autoscaler rather than the autoscaler sniffing
packets. `scripts/loadgen.py` plays the reporter today; a real serving container
replaces it in Phase 6 without the autoscaler changing at all.

Storage is a Redis sorted set per endpoint, one member per reported request scored
by arrival time, which makes the window a true sliding one (exact counts, no
bucket-boundary error) and trimming a single range delete.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from redis import Redis

# The last-request stamp outlives the window on purpose: once traffic stops the
# window empties within seconds, but the idle clock that drives scale-to-zero has
# to keep counting from the real last request.
_LAST_TTL_SECONDS = 3600


def _load_key(workload_id: uuid.UUID) -> str:
    return f"kestrel:load:{workload_id}"


def _last_key(workload_id: uuid.UUID) -> str:
    return f"kestrel:load:{workload_id}:last"


def _to_ms(at: datetime) -> float:
    return at.timestamp() * 1000.0


@dataclass(frozen=True)
class LoadObservation:
    """What the endpoint's traffic looks like right now."""

    requests_in_window: int
    rps: float
    last_request_at: datetime | None

    def idle_seconds(self, now: datetime) -> float:
        """Seconds since the last reported request; infinite if none was ever seen."""
        if self.last_request_at is None:
            return float("inf")
        return max(0.0, (now - self.last_request_at).total_seconds())


class LoadSignal:
    """Records reported requests and reads back a rolling-window rate."""

    def __init__(self, redis: Redis, window_seconds: float):
        self.redis = redis
        self.window_seconds = window_seconds

    def record(self, workload_id: uuid.UUID, requests: int, at: datetime) -> None:
        if requests <= 0:
            return
        score = _to_ms(at)
        # One member per request, uniquely named so identical timestamps don't
        # collapse into a single ZSET entry and undercount the window.
        members = {f"{score:.0f}-{uuid.uuid4().hex}": score for _ in range(requests)}
        self.redis.zadd(_load_key(workload_id), members)
        self.redis.expire(_load_key(workload_id), int(self.window_seconds) + 60)
        self.redis.set(_last_key(workload_id), f"{score:.0f}", ex=_LAST_TTL_SECONDS)

    def observe(self, workload_id: uuid.UUID, now: datetime) -> LoadObservation:
        """Current window count and rate. Trims expired members as a side effect."""
        cutoff = _to_ms(now) - self.window_seconds * 1000.0
        key = _load_key(workload_id)
        self.redis.zremrangebyscore(key, "-inf", f"({cutoff}")
        # redis-py annotates its sync commands with the async client's return union,
        # so the concrete types have to be asserted back here.
        count = cast(int, self.redis.zcard(key))
        last_raw = cast("str | None", self.redis.get(_last_key(workload_id)))

        last_at = None
        if last_raw is not None:
            last_at = datetime.fromtimestamp(float(last_raw) / 1000.0, tz=UTC)
        return LoadObservation(
            requests_in_window=count,
            rps=count / self.window_seconds,
            last_request_at=last_at,
        )

    def clear(self, workload_id: uuid.UUID) -> None:
        """Drop an endpoint's signal — used on teardown so a recycled id starts clean."""
        self.redis.delete(_load_key(workload_id), _last_key(workload_id))
