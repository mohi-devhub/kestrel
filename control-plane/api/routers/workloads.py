"""Cross-kind workload reads — currently just the decision explainer.

`/jobs` and `/endpoints` each own submission and lifecycle for their kind;
`/workloads` is deliberately thin and only for reads that apply to either kind.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from cluster import ClusterClient
from config import settings
from db import get_db
from db.models import Tenant, Workload
from redis_client import get_redis
from scheduler.active_policy import get_active_policy_name
from scheduler.explain import explain
from scheduler.policies import get_policy
from schema.explain import (
    OrderingExplainOut,
    QuotaExplainOut,
    RunwayExplainOut,
    WorkloadExplainOut,
)

from ..deps import require_tenant

router = APIRouter(prefix="/workloads", tags=["workloads"])


def _cluster_client() -> ClusterClient:
    return ClusterClient(kubeconfig_path=settings.kubeconfig_path)


@router.get("/{workload_id}/explain", response_model=WorkloadExplainOut)
def explain_workload(
    workload_id: uuid.UUID,
    tenant: Tenant = Depends(require_tenant),
    db: Session = Depends(get_db),
) -> WorkloadExplainOut:
    workload = db.get(Workload, workload_id)
    if workload is None or workload.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="workload not found")

    policy = get_policy(get_active_policy_name(get_redis()))
    result = explain(db, _cluster_client(), policy, workload, datetime.now(UTC))

    ordering = (
        OrderingExplainOut(
            rank=result.ordering.rank,
            total_admitted=result.ordering.total_admitted,
            would_place_on=result.ordering.would_place_on,
            blocked_reason=result.ordering.blocked_reason,
        )
        if result.ordering is not None
        else None
    )
    return WorkloadExplainOut(
        workload_id=result.workload_id,
        status=result.status,
        quota=QuotaExplainOut(passes=result.quota.passes, reason=result.quota.reason),
        kueue_admitted=result.kueue_admitted,
        ordering=ordering,
        runway=RunwayExplainOut(
            burn_rate_gpus=result.runway.burn_rate_gpus,
            remaining_gpu_seconds=result.runway.remaining_gpu_seconds,
            runway_seconds=result.runway.runway_seconds,
            risk_tier=result.runway_risk_tier,
            is_exhausted=result.runway.is_exhausted,
        ),
    )
