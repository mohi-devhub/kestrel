import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from autoscale import LoadSignal, decide
from autoscale.loop import config_for, last_event_at
from cluster import ClusterClient
from cluster.naming import tenant_namespace
from config import settings
from db import get_db
from db.models import AutoscaleEvent, Tenant, Workload
from metering import MeteringStore
from quota import QuotaEnforcer, QuotaExceeded
from redis_client import get_redis
from scheduler.accounting import effective_gpus
from schema.autoscale import AutoscaleEventOut, LoadOut, LoadReport
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
    spec = body.model_dump()
    try:
        # An endpoint's footprint is gpus x replicas (all replicas pin to one node).
        QuotaEnforcer(db).check_admission(
            tenant, effective_gpus("endpoint", body.gpus, spec), datetime.now(UTC)
        )
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail=exc.reason) from None

    namespace = tenant_namespace(tenant.slug)
    k8s_name = f"endpoint-{uuid.uuid4().hex[:8]}"

    # Endpoints skip Kueue (no native Deployment integration), so there's no
    # external admission gate: born "admitted", the reconcile loop places them and
    # creates the Deployment. The namespace ResourceQuota remains the backstop.
    now = datetime.now(UTC)
    workload = Workload(
        tenant_id=tenant.id,
        kind="endpoint",
        status="admitted",
        spec=spec,
        gpus_requested=body.gpus,
        priority=0,
        namespace=namespace,
        k8s_name=k8s_name,
        created_at=now,
        admitted_at=now,
    )
    db.add(workload)
    db.commit()
    db.refresh(workload)
    return workload


@router.get("/{workload_id}", response_model=WorkloadOut)
def get_endpoint(
    workload_id: uuid.UUID,
    tenant: Tenant = Depends(require_tenant),
    db: Session = Depends(get_db),
) -> Workload:
    # Postgres is the source of truth — the reconcile loop keeps status/node in sync.
    return _get_owned_endpoint(workload_id, tenant, db)


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
    return list(workloads)


@router.delete("/{workload_id}", status_code=204)
def teardown_endpoint(
    workload_id: uuid.UUID,
    tenant: Tenant = Depends(require_tenant),
    db: Session = Depends(get_db),
) -> None:
    workload = _get_owned_endpoint(workload_id, tenant, db)
    if workload.status == "stopped":
        return

    now = datetime.now(UTC)
    if workload.status == "running":
        _cluster_client().delete_deployment(workload.k8s_name, workload.namespace)
        MeteringStore(db).close_interval(workload.id, now)
    workload.status = "stopped"
    workload.replicas = 0
    workload.ended_at = now
    db.commit()
    # Drop the rolling window so a later endpoint can't inherit stale traffic.
    LoadSignal(get_redis(), settings.autoscale_window_seconds).clear(workload.id)


def _load_view(workload: Workload, db: Session, now: datetime) -> LoadOut:
    config = config_for(workload)
    signal = LoadSignal(get_redis(), settings.autoscale_window_seconds)
    obs = signal.observe(workload.id, now)
    current = workload.replicas if workload.replicas is not None else config.min_replicas
    last_at = last_event_at(db, [workload.id]).get(workload.id)
    decision = decide(obs, current, config, now, last_at)
    return LoadOut(
        workload_id=workload.id,
        window_seconds=settings.autoscale_window_seconds,
        requests_in_window=obs.requests_in_window,
        rps=obs.rps,
        last_request_at=obs.last_request_at,
        current_replicas=current,
        desired_replicas=decision.target,
        min_replicas=config.min_replicas,
        max_replicas=config.max_replicas,
        target_rps_per_replica=config.target_rps_per_replica,
    )


@router.post("/{workload_id}/load", response_model=LoadOut)
def report_load(
    workload_id: uuid.UUID,
    body: LoadReport,
    tenant: Tenant = Depends(require_tenant),
    db: Session = Depends(get_db),
) -> LoadOut:
    """Report requests the serving layer handled — the autoscaler's input signal.

    KWOK pods serve no real traffic, so load is reported rather than sniffed; this
    is the same seam Knative uses, where the queue-proxy sidecar pushes its numbers
    to the autoscaler. scripts/loadgen.py is the reporter for the demo.
    """
    workload = _get_owned_endpoint(workload_id, tenant, db)
    now = datetime.now(UTC)
    LoadSignal(get_redis(), settings.autoscale_window_seconds).record(
        workload.id, body.requests, now
    )
    return _load_view(workload, db, now)


@router.get("/{workload_id}/load", response_model=LoadOut)
def get_load(
    workload_id: uuid.UUID,
    tenant: Tenant = Depends(require_tenant),
    db: Session = Depends(get_db),
) -> LoadOut:
    workload = _get_owned_endpoint(workload_id, tenant, db)
    return _load_view(workload, db, datetime.now(UTC))


@router.get("/{workload_id}/autoscale-events", response_model=list[AutoscaleEventOut])
def list_autoscale_events(
    workload_id: uuid.UUID,
    tenant: Tenant = Depends(require_tenant),
    db: Session = Depends(get_db),
) -> list[AutoscaleEvent]:
    workload = _get_owned_endpoint(workload_id, tenant, db)
    events = (
        db.execute(
            select(AutoscaleEvent)
            .where(AutoscaleEvent.workload_id == workload.id)
            .order_by(AutoscaleEvent.at)
        )
        .scalars()
        .all()
    )
    return list(events)
