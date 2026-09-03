import uuid
from decimal import Decimal

from pydantic import BaseModel


class QuotaExplainOut(BaseModel):
    passes: bool
    reason: str | None


class OrderingExplainOut(BaseModel):
    rank: int
    total_admitted: int
    would_place_on: str | None
    blocked_reason: str | None


class RunwayExplainOut(BaseModel):
    burn_rate_gpus: int
    remaining_gpu_seconds: Decimal | None
    runway_seconds: Decimal | None
    risk_tier: int
    is_exhausted: bool


class WorkloadExplainOut(BaseModel):
    workload_id: uuid.UUID
    status: str
    quota: QuotaExplainOut
    kueue_admitted: bool | None
    ordering: OrderingExplainOut | None
    runway: RunwayExplainOut
