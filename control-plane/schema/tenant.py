import uuid
from datetime import datetime

from pydantic import BaseModel


class TenantCreate(BaseModel):
    slug: str
    name: str
    max_gpus: int
    max_workloads: int
    gpu_second_budget: int | None = None
    price_per_gpu_hour: float


class TenantOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    max_gpus: int
    max_workloads: int
    gpu_second_budget: int | None
    price_per_gpu_hour: float
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    key: str
    created_at: datetime
