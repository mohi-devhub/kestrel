import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from cluster import ClusterClient
from cluster.naming import tenant_cluster_queue, tenant_local_queue, tenant_namespace
from config import settings
from db import get_db
from db.models import ApiKey, Tenant
from redis_client import get_redis
from scheduler.active_policy import get_active_policy_name, set_active_policy_name
from scheduler.policies import POLICIES
from schema.scheduler import ActivePolicyOut, PolicySwitchRequest
from schema.tenant import ApiKeyOut, TenantCreate, TenantOut

from ..deps import require_admin

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


def _cluster_client() -> ClusterClient:
    return ClusterClient(kubeconfig_path=settings.kubeconfig_path)


@router.post("/tenants", response_model=TenantOut, status_code=201)
def create_tenant(body: TenantCreate, db: Session = Depends(get_db)) -> Tenant:
    tenant = Tenant(
        slug=body.slug,
        name=body.name,
        max_gpus=body.max_gpus,
        max_workloads=body.max_workloads,
        gpu_second_budget=body.gpu_second_budget,
        price_per_gpu_hour=body.price_per_gpu_hour,
        created_at=datetime.now(UTC),
    )
    db.add(tenant)
    db.flush()

    namespace = tenant_namespace(tenant.slug)
    cluster_queue = tenant_cluster_queue(tenant.slug)
    local_queue = tenant_local_queue(tenant.slug)
    try:
        cluster = _cluster_client()
        cluster.ensure_namespace(namespace)
        cluster.ensure_resource_quota(namespace, tenant.max_gpus, tenant.max_workloads)
        cluster.ensure_resource_flavor()
        cluster.ensure_cluster_queue(cluster_queue, tenant.max_gpus)
        cluster.ensure_local_queue(namespace, local_queue, cluster_queue)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=502, detail="failed to bootstrap tenant on the cluster"
        ) from exc

    db.commit()
    db.refresh(tenant)
    return tenant


@router.get("/tenants", response_model=list[TenantOut])
def list_tenants(db: Session = Depends(get_db)) -> list[Tenant]:
    """Every tenant, for the operator console's tenant switcher.

    Deliberately admin-only and deliberately not mirrored on the tenant API: a
    tenant has no business enumerating its neighbours.
    """
    return list(db.execute(select(Tenant).order_by(Tenant.slug)).scalars().all())


@router.post("/tenants/{tenant_id}/api-keys", response_model=ApiKeyOut, status_code=201)
def create_api_key(tenant_id: uuid.UUID, db: Session = Depends(get_db)) -> ApiKeyOut:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")

    plaintext = f"ksl_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    api_key = ApiKey(tenant_id=tenant.id, key_hash=key_hash, created_at=datetime.now(UTC))
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    return ApiKeyOut(
        id=api_key.id, tenant_id=tenant.id, key=plaintext, created_at=api_key.created_at
    )


@router.get("/policy", response_model=ActivePolicyOut)
def get_active_policy() -> ActivePolicyOut:
    return ActivePolicyOut(name=get_active_policy_name(get_redis()))


@router.post("/policy", response_model=ActivePolicyOut)
def switch_active_policy(body: PolicySwitchRequest) -> ActivePolicyOut:
    if body.name not in POLICIES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown policy {body.name!r}; valid: {sorted(POLICIES)}",
        )
    set_active_policy_name(get_redis(), body.name)
    return ActivePolicyOut(name=body.name)
