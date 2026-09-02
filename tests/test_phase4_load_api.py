"""The reported-load and autoscale-event APIs.

Real Postgres + Redis; tenants and keys are seeded straight into the database so
no kind cluster (and no namespace bootstrap) is needed. Namespaces are "fake-"
prefixed and swept afterwards.
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.main import app
from autoscale.policy import REASON_LOAD
from autoscale.signal import LoadSignal
from config import settings
from db import SessionLocal
from db.models import ApiKey, AutoscaleEvent, Tenant, UsageEvent, Workload
from redis_client import get_redis

WINDOW = settings.autoscale_window_seconds


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def db() -> Any:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _sweep_fake_rows() -> Any:
    yield
    session = SessionLocal()
    try:
        fake = select(Workload.id).where(Workload.namespace.like("fake-%"))
        session.execute(delete(AutoscaleEvent).where(AutoscaleEvent.workload_id.in_(fake)))
        session.execute(delete(UsageEvent).where(UsageEvent.workload_id.in_(fake)))
        session.execute(delete(Workload).where(Workload.namespace.like("fake-%")))
        session.commit()
    finally:
        session.close()


def _tenant_with_key(db: Session) -> tuple[Tenant, str]:
    slug = f"t-{uuid.uuid4().hex[:8]}"
    tenant = Tenant(
        slug=slug,
        name=slug,
        max_gpus=8,
        max_workloads=10,
        price_per_gpu_hour=Decimal("1.0"),
        created_at=datetime.now(UTC),
    )
    db.add(tenant)
    db.flush()
    key = f"kestrel-{uuid.uuid4().hex}"
    db.add(
        ApiKey(
            tenant_id=tenant.id,
            key_hash=hashlib.sha256(key.encode()).hexdigest(),
            created_at=datetime.now(UTC),
        )
    )
    db.commit()
    return tenant, key


def _endpoint(db: Session, tenant: Tenant, *, replicas: int = 1, min_replicas: int = 1) -> Workload:
    now = datetime.now(UTC)
    workload = Workload(
        tenant_id=tenant.id,
        kind="endpoint",
        status="running",
        spec={
            "image": "nginx",
            "gpus": 1,
            "min_replicas": min_replicas,
            "max_replicas": 4,
            "port": 80,
        },
        gpus_requested=1,
        priority=0,
        namespace=f"fake-{tenant.slug}",
        k8s_name=f"endpoint-{uuid.uuid4().hex[:8]}",
        node_name="node-a",
        replicas=replicas,
        created_at=now,
        admitted_at=now,
        started_at=now,
    )
    db.add(workload)
    db.commit()
    return workload


def _headers(key: str) -> dict[str, str]:
    return {"X-Kestrel-Key": key}


def test_reported_load_shows_up_in_the_window(client: TestClient, db: Session) -> None:
    tenant, key = _tenant_with_key(db)
    endpoint = _endpoint(db, tenant)
    LoadSignal(get_redis(), WINDOW).clear(endpoint.id)

    resp = client.post(
        f"/endpoints/{endpoint.id}/load", json={"requests": 60}, headers=_headers(key)
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["requests_in_window"] == 60
    assert body["rps"] == pytest.approx(60 / WINDOW)
    assert body["current_replicas"] == 1
    assert body["last_request_at"] is not None


def test_reports_accumulate_and_drive_the_desired_replica_count(
    client: TestClient, db: Session
) -> None:
    tenant, key = _tenant_with_key(db)
    endpoint = _endpoint(db, tenant)
    LoadSignal(get_redis(), WINDOW).clear(endpoint.id)

    for _ in range(3):
        body = client.post(
            f"/endpoints/{endpoint.id}/load",
            json={"requests": int(5 * WINDOW)},
            headers=_headers(key),
        ).json()

    # 15 rps sustained at the default 5 rps/replica -> the autoscaler wants 3.
    assert body["requests_in_window"] == int(15 * WINDOW)
    assert body["desired_replicas"] == 3


def test_get_load_reads_without_recording(client: TestClient, db: Session) -> None:
    tenant, key = _tenant_with_key(db)
    endpoint = _endpoint(db, tenant)
    LoadSignal(get_redis(), WINDOW).clear(endpoint.id)
    client.post(f"/endpoints/{endpoint.id}/load", json={"requests": 10}, headers=_headers(key))

    first = client.get(f"/endpoints/{endpoint.id}/load", headers=_headers(key)).json()
    second = client.get(f"/endpoints/{endpoint.id}/load", headers=_headers(key)).json()

    assert first["requests_in_window"] == second["requests_in_window"] == 10


def test_load_from_another_tenant_is_not_found(client: TestClient, db: Session) -> None:
    tenant, _ = _tenant_with_key(db)
    _, other_key = _tenant_with_key(db)
    endpoint = _endpoint(db, tenant)

    resp = client.post(
        f"/endpoints/{endpoint.id}/load", json={"requests": 1}, headers=_headers(other_key)
    )

    assert resp.status_code == 404


def test_load_requires_a_key(client: TestClient, db: Session) -> None:
    tenant, _ = _tenant_with_key(db)
    endpoint = _endpoint(db, tenant)
    assert client.post(f"/endpoints/{endpoint.id}/load", json={"requests": 1}).status_code == 422


def test_autoscale_events_are_listed_oldest_first(client: TestClient, db: Session) -> None:
    tenant, key = _tenant_with_key(db)
    endpoint = _endpoint(db, tenant)
    now = datetime.now(UTC)
    db.add_all(
        [
            AutoscaleEvent(
                workload_id=endpoint.id,
                from_replicas=1,
                to_replicas=3,
                reason=REASON_LOAD,
                at=now - timedelta(seconds=60),
            ),
            AutoscaleEvent(
                workload_id=endpoint.id,
                from_replicas=3,
                to_replicas=1,
                reason=REASON_LOAD,
                at=now,
            ),
        ]
    )
    db.commit()

    events = client.get(f"/endpoints/{endpoint.id}/autoscale-events", headers=_headers(key)).json()

    assert [(e["from_replicas"], e["to_replicas"]) for e in events] == [(1, 3), (3, 1)]


def test_endpoint_rejects_max_replicas_below_min(client: TestClient, db: Session) -> None:
    _, key = _tenant_with_key(db)
    resp = client.post(
        "/endpoints",
        json={"image": "nginx", "gpus": 1, "min_replicas": 3, "max_replicas": 1, "port": 80},
        headers=_headers(key),
    )
    assert resp.status_code == 422
