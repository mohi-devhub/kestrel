"""Driving the control loops by hand, the way the real processes do.

The live suites tick `reconcile_once`/`autoscale_once` in-process while the
compose `reconciler` and `autoscaler` services are also running against the same
database and cluster. Both production loops take a short Redis mutex per tick
precisely so two writers cannot place the same workload; a test that skipped it
raced them, and the loser's `create_job` failed with a 409 AlreadyExists once
the timing lined up.

So these helpers take the same lock. That makes them a closer imitation of the
reconciler process, not a looser one.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime

import pytest

from cluster import ClusterClient
from db import SessionLocal
from redis_client import control_lock, get_redis
from scheduler.reconcile import reconcile_once


def drive_reconcile(
    cluster: ClusterClient, until: Callable[[], bool], timeout: float = 60.0
) -> None:
    """Tick the reconcile loop until `until()` holds or the timeout expires."""
    redis = get_redis()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        db = SessionLocal()
        try:
            with control_lock(redis) as acquired:
                # Losing the race means the real reconciler is mid-tick; it may
                # well satisfy the condition on its own, so fall through to the
                # check rather than treating this as a wasted iteration.
                if acquired:
                    reconcile_once(db, cluster, redis)
        finally:
            db.close()
        if until():
            return
        time.sleep(1)
    pytest.fail("reconcile condition not reached within timeout")


def tick_autoscaler(
    cluster: ClusterClient, now: datetime | None = None
) -> dict[str, int]:
    """One autoscaler pass, holding the control lock as the real loop does.

    Unlike reconcile, a skipped tick here would silently return "nothing
    happened" and make a caller's assertion fail for the wrong reason, so this
    retries briefly until it actually gets to run.
    """
    from autoscale.loop import autoscale_once

    redis = get_redis()
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        db = SessionLocal()
        try:
            with control_lock(redis) as acquired:
                if acquired:
                    return autoscale_once(db, cluster, redis, now=now)
        finally:
            db.close()
        time.sleep(0.5)
    pytest.fail("could not acquire the control lock to tick the autoscaler")
