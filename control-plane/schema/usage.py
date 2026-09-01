import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class WorkloadUsageOut(BaseModel):
    workload_id: str
    kind: str
    gpus_requested: int | None
    gpu_seconds: str
    cost: str


class UsageOut(BaseModel):
    tenant_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    total_gpu_seconds: Decimal
    estimated_cost: Decimal
    workloads: list[WorkloadUsageOut]


class BillingReportOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    total_gpu_seconds: Decimal
    total_cost: Decimal
    breakdown: list[WorkloadUsageOut]
    generated_at: datetime

    model_config = {"from_attributes": True}
