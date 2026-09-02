from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from redis import Redis

from config import settings

# Held by the reconciler and the autoscaler around each of their ticks. Both write
# workload rows and usage intervals, and both budget the same pool of node GPUs, so
# serializing their ticks preserves the single-writer property Phase 2 relies on.
# Ticks take milliseconds, so contention costs nothing; the TTL means a crashed
# process can't wedge the other one.
CONTROL_LOCK_KEY = "kestrel:control-lock"
CONTROL_LOCK_TTL_MS = 30_000

# Release only if the lock is still ours: if a tick overran the TTL, someone else
# now holds the key and a blind DELETE would hand a third caller a lock two
# processes think they own.
_RELEASE_IF_MINE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


def get_redis() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


@contextmanager
def control_lock(
    redis: Redis, ttl_ms: int = CONTROL_LOCK_TTL_MS
) -> Iterator[bool]:
    """Try to take the control-loop mutex. Yields whether it was acquired.

    Non-blocking on purpose: a loop that loses the race skips this tick and comes
    back on its own interval rather than queueing up behind the other one.
    """
    token = uuid.uuid4().hex
    acquired = bool(redis.set(CONTROL_LOCK_KEY, token, nx=True, px=ttl_ms))
    try:
        yield acquired
    finally:
        if acquired:
            redis.eval(_RELEASE_IF_MINE, 1, CONTROL_LOCK_KEY, token)
