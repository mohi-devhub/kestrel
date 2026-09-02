"""Which placement policy is live right now.

Stored in Redis so the API process (which switches it via POST /admin/policy) and
the reconciler process (which reads it every tick) share it without a restart.
Losing the key (e.g. a Redis flush) just falls back to first_fit — each placed
workload's `placement_policy` is recorded durably in Postgres regardless.
"""

from __future__ import annotations

from redis import Redis

from scheduler.policies import POLICIES

ACTIVE_POLICY_KEY = "kestrel:active_policy"
DEFAULT_POLICY = "first_fit"


def get_active_policy_name(redis: Redis) -> str:
    raw = redis.get(ACTIVE_POLICY_KEY)
    if raw is None:
        return DEFAULT_POLICY
    name = raw.decode() if isinstance(raw, bytes) else str(raw)
    return name if name in POLICIES else DEFAULT_POLICY


def set_active_policy_name(redis: Redis, name: str) -> None:
    if name not in POLICIES:
        raise ValueError(f"unknown placement policy: {name!r}")
    redis.set(ACTIVE_POLICY_KEY, name)
