import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LoadReport(BaseModel):
    """Requests the serving layer handled since its last report."""

    requests: int = Field(1, ge=1, le=10_000)


class LoadOut(BaseModel):
    """Observed load for an endpoint, plus what the autoscaler makes of it."""

    workload_id: uuid.UUID
    window_seconds: float
    requests_in_window: int
    rps: float
    last_request_at: datetime | None
    current_replicas: int
    # What the load alone calls for. The autoscaler may land lower if the node or
    # the tenant's GPU quota can't cover it — see clamp_to_capacity.
    desired_replicas: int
    min_replicas: int
    max_replicas: int
    target_rps_per_replica: float


class AutoscaleEventOut(BaseModel):
    id: uuid.UUID
    workload_id: uuid.UUID
    from_replicas: int
    to_replicas: int
    reason: str
    at: datetime

    model_config = {"from_attributes": True}
