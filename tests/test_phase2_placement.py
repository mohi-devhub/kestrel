"""Phase 2 integration tests against the real kind+KWOK cluster.

Requires: `bash deploy/bootstrap.sh` run, `docker compose up -d postgres redis` in
deploy/, `alembic upgrade head` from control-plane/. Stop the compose `reconciler`
service while these run — the tests drive reconcile ticks themselves so the
scenarios stay deterministic.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from api.main import app
from cluster import ClusterClient
from cluster.naming import tenant_namespace
from config import settings
from db import SessionLocal
from db.models import AutoscaleEvent, UsageEvent, Workload
from live_loops import drive_reconcile

ADMIN_HEADERS = {"X-Kestrel-Admin-Token": settings.admin_token}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def cluster() -> ClusterClient:
    return ClusterClient(kubeconfig_path=settings.kubeconfig_path)


@pytest.fixture(autouse=True)
def _first_fit_active(client: TestClient) -> None:
    resp = client.post("/admin/policy", json={"name": "first_fit"}, headers=ADMIN_HEADERS)
    assert resp.status_code == 200, resp.text


def _create_tenant(client: TestClient, max_gpus: int) -> dict:
    slug = f"t-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/admin/tenants",
        json={
            "slug": slug,
            "name": slug,
            "max_gpus": max_gpus,
            "max_workloads": 20,
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


def _submit_job(client: TestClient, key: str, gpus: int, seconds: int = 300) -> dict:
    resp = client.post(
        "/jobs",
        json={"image": "busybox", "command": ["sleep", str(seconds)], "gpus": gpus},
        headers={"X-Kestrel-Key": key},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _statuses(client: TestClient, key: str) -> dict[str, str]:
    resp = client.get("/jobs", headers={"X-Kestrel-Key": key})
    assert resp.status_code == 200
    return {w["id"]: w["status"] for w in resp.json()}


def _node_usage(client: TestClient) -> dict[str, dict]:
    resp = client.get("/cluster/nodes", headers=ADMIN_HEADERS)
    assert resp.status_code == 200, resp.text
    return {n["name"]: n for n in resp.json() if n["gpu_total"] > 0}


def _cancel_all(client: TestClient, key: str) -> None:
    for w in client.get("/jobs", headers={"X-Kestrel-Key": key}).json():
        client.delete(f"/jobs/{w['id']}", headers={"X-Kestrel-Key": key})


def test_oversubscription_queues_via_kueue_then_drains(
    client: TestClient, cluster: ClusterClient
) -> None:
    # Quota of 4 GPUs; three 2-GPU jobs: Kueue must hold the third back.
    tenant = _create_tenant(client, max_gpus=4)
    key = _issue_key(client, tenant["id"])
    jobs = [_submit_job(client, key, gpus=2, seconds=15) for _ in range(3)]
    ids = [j["id"] for j in jobs]

    try:
        drive_reconcile(
            cluster,
            until=lambda: sorted(_statuses(client, key)[i] for i in ids)
            == ["queued", "running", "running"],
        )
        # The third job is Kueue-queued (not admitted), not merely unplaced.
        drive_reconcile(
            cluster,
            until=lambda: all(
                s in {"succeeded", "running"} for s in _statuses(client, key).values()
            )
            and any(s == "succeeded" for s in _statuses(client, key).values()),
            timeout=120.0,
        )
        # Eventually everything drains.
        drive_reconcile(
            cluster,
            until=lambda: set(_statuses(client, key).values()) == {"succeeded"},
            timeout=120.0,
        )
    finally:
        _cancel_all(client, key)


def test_policy_swap_changes_placement(client: TestClient, cluster: ClusterClient) -> None:
    tenant = _create_tenant(client, max_gpus=8)
    key = _issue_key(client, tenant["id"])
    namespace = tenant_namespace(tenant["slug"])
    db = SessionLocal()

    try:
        # Seed uneven usage directly in the accounting (a "running" endpoint row
        # holding 2 GPUs on a non-first node): first-fit will prefer the wide-open
        # first node, bin-packing must prefer this tighter one.
        seed = Workload(
            tenant_id=uuid.UUID(tenant["id"]),
            kind="endpoint",
            status="running",
            spec={"image": "nginx", "gpus": 2, "min_replicas": 1, "port": 80},
            gpus_requested=2,
            priority=0,
            namespace=namespace,
            k8s_name=f"endpoint-{uuid.uuid4().hex[:8]}",
            node_name="kwok-gpu-node-2",
            created_at=datetime.now(UTC),
            admitted_at=datetime.now(UTC),
        )
        db.add(seed)
        db.commit()

        usage = _node_usage(client)
        first_fit_pick = next(n for n in sorted(usage) if usage[n]["gpu_free"] >= 1)
        fitting = [n for n in sorted(usage) if usage[n]["gpu_free"] >= 1]
        bin_packing_pick = min(fitting, key=lambda n: (usage[n]["gpu_free"], n))
        # The scenario only demonstrates anything if the two policies disagree.
        assert first_fit_pick != bin_packing_pick

        job_ff = _submit_job(client, key, gpus=1)
        drive_reconcile(cluster, until=lambda: _statuses(client, key)[job_ff["id"]] == "running")
        placed_ff = client.get(f"/jobs/{job_ff['id']}", headers={"X-Kestrel-Key": key}).json()
        assert placed_ff["node_name"] == first_fit_pick
        assert placed_ff["placement_policy"] == "first_fit"

        resp = client.post("/admin/policy", json={"name": "bin_packing"}, headers=ADMIN_HEADERS)
        assert resp.status_code == 200

        usage = _node_usage(client)
        fitting = [n for n in sorted(usage) if usage[n]["gpu_free"] >= 1]
        bin_packing_pick = min(fitting, key=lambda n: (usage[n]["gpu_free"], n))

        job_bp = _submit_job(client, key, gpus=1)
        drive_reconcile(cluster, until=lambda: _statuses(client, key)[job_bp["id"]] == "running")
        placed_bp = client.get(f"/jobs/{job_bp['id']}", headers={"X-Kestrel-Key": key}).json()
        assert placed_bp["node_name"] == bin_packing_pick
        assert placed_bp["placement_policy"] == "bin_packing"
    finally:
        _cancel_all(client, key)
        ns_workloads = select(Workload.id).where(Workload.namespace == namespace)
        db.execute(delete(AutoscaleEvent).where(AutoscaleEvent.workload_id.in_(ns_workloads)))
        db.execute(delete(UsageEvent).where(UsageEvent.workload_id.in_(ns_workloads)))
        db.execute(delete(Workload).where(Workload.namespace == namespace))
        db.commit()
        db.close()


def test_unknown_policy_rejected(client: TestClient) -> None:
    resp = client.post("/admin/policy", json={"name": "round-robin"}, headers=ADMIN_HEADERS)
    assert resp.status_code == 400


def test_multi_gpu_job_lands_on_a_single_node(
    client: TestClient, cluster: ClusterClient
) -> None:
    tenant = _create_tenant(client, max_gpus=4)
    key = _issue_key(client, tenant["id"])
    job = _submit_job(client, key, gpus=4)

    try:
        drive_reconcile(cluster, until=lambda: _statuses(client, key)[job["id"]] == "running")
        placed = client.get(f"/jobs/{job['id']}", headers={"X-Kestrel-Key": key}).json()
        assert placed["node_name"] is not None
        usage = _node_usage(client)
        assert usage[placed["node_name"]]["gpu_used"] >= 4
    finally:
        _cancel_all(client, key)
