import hashlib

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from db import get_db
from db.models import ApiKey, Tenant


def require_admin(x_foundry_admin_token: str = Header(...)) -> None:
    if x_foundry_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="invalid admin token")


def require_tenant(
    x_foundry_key: str = Header(...), db: Session = Depends(get_db)
) -> Tenant:
    key_hash = hashlib.sha256(x_foundry_key.encode()).hexdigest()
    row = db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=401, detail="invalid API key")
    tenant = db.get(Tenant, row.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=401, detail="invalid API key")
    return tenant
