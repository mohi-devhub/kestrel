import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from cluster import ClusterClient
from cluster.naming import tenant_local_queue, tenant_namespace
from config import settings
from db import get_db
from db.models import Tenant, Workload
from schema.workload import JobCreate, WorkloadOut

from ..deps import require_tenant

router = APIRouter(prefix="/jobs", tags=["jobs"])

TERMINAL_STATUSES = {"succeeded", "failed", "stopped"}


def _cluster_client() -> ClusterClient:
    return ClusterClient(kubeconfig_path=settings.kubeconfig_path)


def _get_owned_job(workload_id: uuid.UUID, tenant: Tenant, db: Session) -> Workload:
    workload = db.get(Workload, workload_id)
    if workload is None or workload.tenant_id != tenant.id or workload.kind != "job":
        raise HTTPException(status_code=404, detail="job not found")
    return workload


@router.post("", response_model=WorkloadOut, status_code=201)
def submit_job(
    body: JobCreate, tenant: Tenant = Depends(require_tenant), db: Session = Depends(get_db)
) -> Workload:
    namespace = tenant_namespace(tenant.slug)
    k8s_name = f"job-{uuid.uuid4().hex[:8]}"

    workload = Workload(
        tenant_id=tenant.id,
        kind="job",
        status="queued",
        spec=body.model_dump(),
        gpus_requested=body.gpus,
        priority=body.priority,
        namespace=namespace,
        k8s_name=k8s_name,
        created_at=datetime.now(UTC),
    )
    db.add(workload)
    db.flush()

    try:
        # Only a Kueue Workload CR is created here — no K8s Job yet. The reconcile
        # loop creates the Job after Kueue admits this, on the node the active
        # placement policy picks.
        _cluster_client().ensure_kueue_workload(
            name=k8s_name,
            namespace=namespace,
            queue_name=tenant_local_queue(tenant.slug),
            image=body.image,
            gpus=body.gpus,
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail="failed to submit job to the cluster") from exc

    db.commit()
    db.refresh(workload)
    return workload


@router.get("/{workload_id}", response_model=WorkloadOut)
def get_job(
    workload_id: uuid.UUID,
    tenant: Tenant = Depends(require_tenant),
    db: Session = Depends(get_db),
) -> Workload:
    # Postgres is the source of truth — the reconcile loop keeps status/node in sync.
    return _get_owned_job(workload_id, tenant, db)


@router.get("", response_model=list[WorkloadOut])
def list_jobs(
    tenant: Tenant = Depends(require_tenant), db: Session = Depends(get_db)
) -> list[Workload]:
    workloads = (
        db.execute(select(Workload).where(Workload.tenant_id == tenant.id, Workload.kind == "job"))
        .scalars()
        .all()
    )
    return list(workloads)


@router.delete("/{workload_id}", status_code=204)
def cancel_job(
    workload_id: uuid.UUID,
    tenant: Tenant = Depends(require_tenant),
    db: Session = Depends(get_db),
) -> None:
    workload = _get_owned_job(workload_id, tenant, db)
    if workload.status in TERMINAL_STATUSES:
        return

    cluster = _cluster_client()
    if workload.status == "running":
        cluster.delete_job(workload.k8s_name, workload.namespace)
    # Always drop the Kueue Workload (tolerates 404) — a queued/admitted job has no
    # K8s Job yet, but its Workload CR still holds a spot in Kueue's queue/quota.
    cluster.delete_kueue_workload(workload.k8s_name, workload.namespace)
    workload.status = "stopped"
    workload.ended_at = datetime.now(UTC)
    db.commit()
