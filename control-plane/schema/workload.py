import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class JobCreate(BaseModel):
    image: str
    command: list[str]
    gpus: int = 0
    priority: int = 0


class EndpointCreate(BaseModel):
    image: str
    gpus: int = 0
    # min_replicas=0 opts the endpoint into scale-to-zero (Knative's minScale
    # semantics): it starts cold, costs nothing, and wakes on first request.
    min_replicas: int = Field(1, ge=0)
    max_replicas: int = Field(1, ge=1)
    port: int
    # Per-endpoint autoscaling target; falls back to the platform default.
    target_rps_per_replica: float | None = Field(None, gt=0)

    @model_validator(mode="after")
    def _replica_range(self) -> "EndpointCreate":
        if self.max_replicas < self.min_replicas:
            raise ValueError("max_replicas must be >= min_replicas")
        return self


class WorkloadOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    kind: str
    status: str
    spec: dict[str, Any]
    gpus_requested: int
    priority: int
    namespace: str
    k8s_name: str
    node_name: str | None
    placement_policy: str | None
    replicas: int | None
    created_at: datetime
    admitted_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None

    model_config = {"from_attributes": True}
