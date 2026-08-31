"""Integration tests for Phase 1 (tenants, API keys, isolation), run against the real
kind cluster and the real docker-compose Postgres — same style as test_phase0_cluster.py.

Requires: `bash deploy/bootstrap.sh` already run, `docker compose up -d postgres redis`
in deploy/, and `alembic upgrade head` applied from control-plane/. ADMIN_TOKEN,
DATABASE_URL, REDIS_URL, KUBECONFIG_PATH must be set (control-plane/.env, copied from
.env.example, covers this for local runs).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import app
from cluster import ClusterClient
from cluster.naming import tenant_local_queue, tenant_namespace
from config import settings

ADMIN_HEADERS = {"X-Kestrel-Admin-Token": settings.admin_token}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def cluster() -> ClusterClient:
    return ClusterClient(kubeconfig_path=settings.kubeconfig_path)


def _create_tenant(client: TestClient, max_gpus: int = 4) -> dict:
    slug = f"t-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/admin/tenants",
        json={
            "slug": slug,
            "name": slug,
            "max_gpus": max_gpus,
            "max_workloads": 10,
            "price_per_gpu_hour": 1.0,
        },
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _issue_key(client: TestClient, tenant_id: str) -> str:
    resp = client.post(f"/admin/tenants/{tenant_id}/api-keys", headers=ADMIN_HEADERS)
    assert resp.status_code == 201, resp.text
    return resp.json()["key"]


def test_tenant_creation_bootstraps_cluster_resources(
    client: TestClient, cluster: ClusterClient
) -> None:
    tenant = _create_tenant(client)
    namespace = tenant_namespace(tenant["slug"])

    ns = cluster.core.read_namespace(namespace)
    assert ns.metadata.name == namespace

    quota = cluster.core.read_namespaced_resource_quota("kestrel-quota", namespace)
    assert quota.spec.hard["requests.nvidia.com/gpu"] == "4"

    local_queue = cluster.custom.get_namespaced_custom_object(
        "kueue.x-k8s.io",
        "v1beta2",
        namespace,
        "localqueues",
        tenant_local_queue(tenant["slug"]),
    )
    assert local_queue["spec"]["clusterQueue"] == f"cq-{tenant['slug']}"


def test_job_submission_and_tenant_isolation(client: TestClient) -> None:
    tenant_a = _create_tenant(client)
    tenant_b = _create_tenant(client)
    key_a = _issue_key(client, tenant_a["id"])
    key_b = _issue_key(client, tenant_b["id"])

    resp = client.post(
        "/jobs",
        json={"image": "busybox", "command": ["sleep", "30"], "gpus": 1},
        headers={"X-Kestrel-Key": key_a},
    )
    assert resp.status_code == 201, resp.text
    job = resp.json()

    try:
        # Tenant A can read its own job; status comes from Postgres, which the
        # reconcile loop keeps in sync with Kueue and the cluster.
        resp = client.get(f"/jobs/{job['id']}", headers={"X-Kestrel-Key": key_a})
        assert resp.status_code == 200
        assert resp.json()["status"] in {"queued", "admitted", "running", "succeeded"}

        resp = client.get("/jobs", headers={"X-Kestrel-Key": key_a})
        assert resp.status_code == 200
        assert any(w["id"] == job["id"] for w in resp.json())

        # Tenant B gets 404, both by id and absence from its own list — no leakage.
        resp = client.get(f"/jobs/{job['id']}", headers={"X-Kestrel-Key": key_b})
        assert resp.status_code == 404

        resp = client.get("/jobs", headers={"X-Kestrel-Key": key_b})
        assert resp.status_code == 200
        assert all(w["id"] != job["id"] for w in resp.json())
    finally:
        client.delete(f"/jobs/{job['id']}", headers={"X-Kestrel-Key": key_a})


def test_invalid_api_key_rejected(client: TestClient) -> None:
    resp = client.get("/jobs", headers={"X-Kestrel-Key": "ksl_not-a-real-key"})
    assert resp.status_code == 401


def test_admin_routes_require_admin_token(client: TestClient) -> None:
    resp = client.post(
        "/admin/tenants",
        json={
            "slug": "should-fail",
            "name": "should-fail",
            "max_gpus": 1,
            "max_workloads": 1,
            "price_per_gpu_hour": 1.0,
        },
        headers={"X-Kestrel-Admin-Token": "wrong-token"},
    )
    assert resp.status_code == 401
