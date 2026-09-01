from __future__ import annotations

from redis import Redis

from config import settings


def get_redis() -> Redis[str]:
    return Redis.from_url(settings.redis_url, decode_responses=True)
