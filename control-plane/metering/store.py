"""Append-only usage intervals: the source of truth for GPU-seconds.

An interval opens when the reconcile loop places a workload and closes when the
workload ends (or is rotated via `record_partial`, e.g. on a replica change).
Live cost never needs a write: `usage_for` prices open intervals up to `now`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import UsageEvent


@dataclass
class UsageBreakdown:
    period_start: datetime
    period_end: datetime
    total_gpu_seconds: Decimal = Decimal(0)
    per_workload: dict[uuid.UUID, Decimal] = field(default_factory=dict)


class MeteringStore:
    def __init__(self, db: Session):
        self.db = db

    def _open_interval_row(self, workload_id: uuid.UUID) -> UsageEvent | None:
        return self.db.execute(
            select(UsageEvent).where(
                UsageEvent.workload_id == workload_id, UsageEvent.ended_at.is_(None)
            )
        ).scalar_one_or_none()

    def open_interval(
        self,
        tenant_id: uuid.UUID,
        workload_id: uuid.UUID,
        gpus: int,
        started_at: datetime,
    ) -> UsageEvent:
        """Idempotent: a workload has at most one open interval at a time."""
        existing = self._open_interval_row(workload_id)
        if existing is not None:
            return existing
        event = UsageEvent(
            tenant_id=tenant_id,
            workload_id=workload_id,
            gpus=gpus,
            started_at=started_at,
            recorded_at=started_at,
        )
        self.db.add(event)
        return event

    def close_interval(
        self, workload_id: uuid.UUID, ended_at: datetime, *, is_partial: bool = False
    ) -> UsageEvent | None:
        """Idempotent: closing a workload with no open interval is a no-op."""
        event = self._open_interval_row(workload_id)
        if event is None:
            return None
        event.ended_at = ended_at
        event.gpu_seconds = Decimal(event.gpus) * Decimal(
            str((ended_at - event.started_at).total_seconds())
        )
        event.is_partial = is_partial
        return event

    def record_partial(self, workload_id: uuid.UUID, at: datetime) -> UsageEvent | None:
        """Rotate the open interval: close it as partial and reopen from `at`.

        Keeps every closed row immutable while a workload keeps running — the
        autoscaler uses this when a replica change alters the GPU footprint.
        """
        closed = self.close_interval(workload_id, at, is_partial=True)
        if closed is None:
            return None
        # Sessions here run with autoflush=False; without a flush the reopen's
        # open-interval lookup would still see the row we just closed as open.
        self.db.flush()
        return self.open_interval(closed.tenant_id, workload_id, closed.gpus, at)

    def usage_for(
        self,
        tenant_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
        now: datetime,
    ) -> UsageBreakdown:
        """GPU-seconds per workload within the period.

        Each interval is clipped to the period window; open intervals accrue up
        to `now`. Python-side math over the fetched rows — exact and simple at
        this scale.
        """
        rows = (
            self.db.execute(
                select(UsageEvent).where(
                    UsageEvent.tenant_id == tenant_id,
                    UsageEvent.started_at < period_end,
                )
            )
            .scalars()
            .all()
        )
        usage = UsageBreakdown(period_start=period_start, period_end=period_end)
        for row in rows:
            effective_end = row.ended_at if row.ended_at is not None else now
            overlap_start = max(row.started_at, period_start)
            overlap_end = min(effective_end, period_end)
            seconds = (overlap_end - overlap_start).total_seconds()
            if seconds <= 0:
                continue
            gpu_seconds = Decimal(row.gpus) * Decimal(str(seconds))
            usage.per_workload[row.workload_id] = (
                usage.per_workload.get(row.workload_id, Decimal(0)) + gpu_seconds
            )
            usage.total_gpu_seconds += gpu_seconds
        return usage
