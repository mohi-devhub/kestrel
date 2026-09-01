"""Phase 3 integration against the real kind+KWOK cluster: quota rejections,
live usage accrual, and billing reports through the full stack.

Requires: `bash deploy/bootstrap.sh` run, `docker compose up -d postgres redis` in
deploy/, `alembic upgrade head` from control-plane/. Stop the compose `reconciler`
service while these run — the tests drive reconcile ticks themselves.
"""

import time
import uuid
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from api.main import app
from cluster import ClusterClient
from config import settings
from db import SessionLocal
from redis_client import get_redis
from scheduler.reconcile import reconcile_once

ADMIN_HEADERS = {"X-Kestrel-Admin-Token": settings.admin_token}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def cluster() -> ClusterClient:
    return ClusterClient(kubeconfig_path=settings.kubeconfig_path)


def _create_tenant(
    client: TestClient,
    max_gpus: int,
    max_workloads: int = 20,
    gpu_second_budget: int | None = None,
) -> dict:
    slug = f"t-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/admin/tenants",
        json={
            "slug": slug,
            "name": slug,
            "max_gpus": max_gpus,
            "max_workloads": max_workloads,
            "gpu_second_budget": gpu_second_budget,
            "price_per_gpu_hour": 2.0,
        },
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _issue_key(client: TestClient, tenant_id: str) -> str:
    resp = client.post(f"/admin/tenants/{tenant_id}/api-keys", headers=ADMIN_HEADERS)
    assert resp.status_code == 201, resp.text
    return resp.json()["key"]


def _submit_job(client: TestClient, key: str, gpus: int) -> dict:
    resp = client.post(
        "/jobs",
        json={"image": "busybox", "command": ["sleep", "300"], "gpus": gpus},
        headers={"X-Kestrel-Key": key},
    )
    return resp


def _drive_reconcile(
    cluster: ClusterClient, until: Callable[[], bool], timeout: float = 60.0
) -> None:
    redis = get_redis()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        db = SessionLocal()
        try:
            reconcile_once(db, cluster, redis)
        finally:
            db.close()
        if until():
            return
        time.sleep(1)
    pytest.fail("reconcile condition not reached within timeout")


def _job_status(client: TestClient, key: str, job_id: str) -> dict:
    resp = client.get(f"/jobs/{job_id}", headers={"X-Kestrel-Key": key})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_impossible_ask_and_workload_limit_are_rejected(client: TestClient) -> None:
    tenant = _create_tenant(client, max_gpus=2, max_workloads=2)
    key = _issue_key(client, tenant["id"])

    # Bigger than the tenant's whole quota: rejected upfront, nothing persisted.
    resp = _submit_job(client, key, gpus=3)
    assert resp.status_code == 429
    assert "could never run" in resp.json()["detail"]

    # In-flight workload cap.
    assert _submit_job(client, key, gpus=1).status_code == 201
    assert _submit_job(client, key, gpus=1).status_code == 201
    resp = _submit_job(client, key, gpus=1)
    assert resp.status_code == 429
    assert "workload limit" in resp.json()["detail"]

    for w in client.get("/jobs", headers={"X-Kestrel-Key": key}).json():
        client.delete(f"/jobs/{w['id']}", headers={"X-Kestrel-Key": key})


def test_usage_accrues_and_billing_report_prices_it(
    client: TestClient, cluster: ClusterClient
) -> None:
    tenant = _create_tenant(client, max_gpus=4)
    key = _issue_key(client, tenant["id"])
    job = _submit_job(client, key, gpus=2).json()

    _drive_reconcile(
        cluster,
        until=lambda: _job_status(client, key, job["id"])["status"]
        in {"running", "succeeded"},
    )
    usage = client.get(f"/tenants/{tenant['id']}/usage", headers={"X-Kestrel-Key": key}).json()
    assert Decimal(str(usage["total_gpu_seconds"])) > 0
    assert any(w["workload_id"] == job["id"] for w in usage["workloads"])

    # Let it finish (KWOK completes fake pods quickly), then check exact math.
    _drive_reconcile(
        cluster,
        until=lambda: _job_status(client, key, job["id"])["status"] == "succeeded",
    )
    final = _job_status(client, key, job["id"])
    duration = datetime.fromisoformat(final["ended_at"]) - datetime.fromisoformat(
        final["started_at"]
    )
    expected = Decimal(2) * Decimal(str(duration.total_seconds()))

    usage = client.get(f"/tenants/{tenant['id']}/usage", headers={"X-Kestrel-Key": key}).json()
    assert Decimal(str(usage["total_gpu_seconds"])) == expected

    report = client.get(
        f"/tenants/{tenant['id']}/billing-report", headers={"X-Kestrel-Key": key}
    ).json()
    assert Decimal(str(report["total_gpu_seconds"])) == expected
    # price_per_gpu_hour=2.0, quantized to cents
    expected_cost = (expected / Decimal(3600) * Decimal(2)).quantize(Decimal("0.01"))
    assert Decimal(str(report["total_cost"])) == expected_cost
    assert any(w["workload_id"] == job["id"] for w in report["breakdown"])


def test_budget_exhaustion_blocks_new_submissions(
    client: TestClient, cluster: ClusterClient
) -> None:
    tenant = _create_tenant(client, max_gpus=4, gpu_second_budget=1)
    key = _issue_key(client, tenant["id"])
    job = _submit_job(client, key, gpus=4).json()

    # Run the whole quota's worth of GPUs so even a short KWOK-completed run
    # burns through the 1 GPU-second budget.
    _drive_reconcile(
        cluster,
        until=lambda: _job_status(client, key, job["id"])["status"] == "succeeded",
    )

    resp = _submit_job(client, key, gpus=1)
    assert resp.status_code == 429
    assert "budget" in resp.json()["detail"]


def test_usage_is_tenant_scoped(client: TestClient) -> None:
    tenant_a = _create_tenant(client, max_gpus=2)
    tenant_b = _create_tenant(client, max_gpus=2)
    key_b = _issue_key(client, tenant_b["id"])

    resp = client.get(f"/tenants/{tenant_a['id']}/usage", headers={"X-Kestrel-Key": key_b})
    assert resp.status_code == 404
