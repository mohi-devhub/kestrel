import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class JobCreate(BaseModel):
    image: str
    command: list[str]
    gpus: int = 0
    priority: int = 0


class EndpointCreate(BaseModel):
    image: str
    gpus: int = 0
    min_replicas: int = 1
    max_replicas: int = 1
    port: int


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
    created_at: datetime
    admitted_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None

    model_config = {"from_attributes": True}
