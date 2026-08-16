import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from cluster import ClusterClient
from cluster.naming import tenant_namespace
from config import settings
from db import get_db
from db.models import Tenant, Workload
from schema.workload import EndpointCreate, WorkloadOut

from ..deps import require_tenant

router = APIRouter(prefix="/endpoints", tags=["endpoints"])


def _cluster_client() -> ClusterClient:
    return ClusterClient(kubeconfig_path=settings.kubeconfig_path)


def _get_owned_endpoint(workload_id: uuid.UUID, tenant: Tenant, db: Session) -> Workload:
    workload = db.get(Workload, workload_id)
    if workload is None or workload.tenant_id != tenant.id or workload.kind != "endpoint":
        raise HTTPException(status_code=404, detail="endpoint not found")
    return workload


@router.post("", response_model=WorkloadOut, status_code=201)
def provision_endpoint(
    body: EndpointCreate, tenant: Tenant = Depends(require_tenant), db: Session = Depends(get_db)
) -> Workload:
    namespace = tenant_namespace(tenant.slug)
    k8s_name = f"endpoint-{uuid.uuid4().hex[:8]}"

    workload = Workload(
        tenant_id=tenant.id,
        kind="endpoint",
        status="creating",
        spec=body.model_dump(),
        gpus_requested=body.gpus,
        priority=0,
        namespace=namespace,
        k8s_name=k8s_name,
        created_at=datetime.now(UTC),
    )
    db.add(workload)
    db.flush()

    try:
        # No Kueue admission for endpoints yet — Kueue has no native Deployment
        # integration. The namespace ResourceQuota is the only guard rail this phase.
        _cluster_client().create_deployment(
            name=k8s_name,
            namespace=namespace,
            image=body.image,
            port=body.port,
            gpus=body.gpus,
            replicas=body.min_replicas,
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=502, detail="failed to provision endpoint on the cluster"
        ) from exc

    db.commit()
    db.refresh(workload)
    return workload


@router.get("/{workload_id}", response_model=WorkloadOut)
def get_endpoint(
    workload_id: uuid.UUID,
    tenant: Tenant = Depends(require_tenant),
    db: Session = Depends(get_db),
) -> Workload:
    workload = _get_owned_endpoint(workload_id, tenant, db)
    workload.status = _cluster_client().get_deployment_status(
        workload.k8s_name, workload.namespace
    )
    return workload


@router.get("", response_model=list[WorkloadOut])
def list_endpoints(
    tenant: Tenant = Depends(require_tenant), db: Session = Depends(get_db)
) -> list[Workload]:
    workloads = (
        db.execute(
            select(Workload).where(Workload.tenant_id == tenant.id, Workload.kind == "endpoint")
        )
        .scalars()
        .all()
    )
    cluster = _cluster_client()
    for workload in workloads:
        workload.status = cluster.get_deployment_status(workload.k8s_name, workload.namespace)
    return list(workloads)


@router.delete("/{workload_id}", status_code=204)
def teardown_endpoint(
    workload_id: uuid.UUID,
    tenant: Tenant = Depends(require_tenant),
    db: Session = Depends(get_db),
) -> None:
    workload = _get_owned_endpoint(workload_id, tenant, db)
    _cluster_client().delete_deployment(workload.k8s_name, workload.namespace)
    workload.status = "stopped"
    workload.ended_at = datetime.now(UTC)
    db.commit()
