"""Phase 4 integration against the real kind+KWOK cluster: an endpoint that wakes
under reported load and sleeps again when it stops, verified against the real
Deployment's replica count rather than the control plane's own bookkeeping.

Requires: `bash deploy/bootstrap.sh` run, `docker compose up -d postgres redis` in
deploy/, `alembic upgrade head` from control-plane/. Stop the compose `reconciler`
and `autoscaler` services while these run — the tests drive both loops themselves.

Elapsed time is simulated by passing an explicit `now` into autoscale_once rather
than sleeping out the 60s idle window: the load signal's timestamps are real, so a
future `now` is genuinely indistinguishable from having waited.
"""

import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from api.main import app
from autoscale.loop import autoscale_once
from autoscale.policy import REASON_SCALE_FROM_ZERO, REASON_SCALE_TO_ZERO
from cluster import ClusterClient
from config import settings
from db import SessionLocal
from redis_client import get_redis
from scheduler.reconcile import reconcile_once

ADMIN_HEADERS = {"X-Kestrel-Admin-Token": settings.admin_token}
WINDOW = settings.autoscale_window_seconds


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def cluster() -> ClusterClient:
    return ClusterClient(kubeconfig_path=settings.kubeconfig_path)


def _create_tenant(client: TestClient, max_gpus: int = 8) -> dict:
    slug = f"t-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/admin/tenants",
        json={
            "slug": slug,
            "name": slug,
            "max_gpus": max_gpus,
            "max_workloads": 20,
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


def _provision_endpoint(client: TestClient, key: str, **overrides: object) -> dict:
    body = {
        "image": "nginx",
        "gpus": 1,
        "min_replicas": 0,
        "max_replicas": 4,
        "port": 80,
    }
    body.update(overrides)
    resp = client.post("/endpoints", json=body, headers={"X-Kestrel-Key": key})
    assert resp.status_code == 201, resp.text
    return resp.json()


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


def _tick_autoscaler(cluster: ClusterClient, now: datetime | None = None) -> dict[str, int]:
    db = SessionLocal()
    try:
        return autoscale_once(db, cluster, get_redis(), now=now)
    finally:
        db.close()


def _endpoint(client: TestClient, key: str, endpoint_id: str) -> dict:
    resp = client.get(f"/endpoints/{endpoint_id}", headers={"X-Kestrel-Key": key})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _k8s_replicas(cluster: ClusterClient, namespace: str, name: str) -> int:
    dep = cluster.apps.read_namespaced_deployment(name=name, namespace=namespace)
    return int(dep.spec.replicas or 0)


def test_endpoint_wakes_under_load_and_sleeps_when_it_stops(
    client: TestClient, cluster: ClusterClient
) -> None:
    tenant = _create_tenant(client)
    key = _issue_key(client, tenant["id"])
    endpoint = _provision_endpoint(client, key)
    headers = {"X-Kestrel-Key": key}

    try:
        # Placement creates the real Deployment, cold at zero replicas.
        _drive_reconcile(
            cluster, until=lambda: _endpoint(client, key, endpoint["id"])["status"] == "running"
        )
        placed = _endpoint(client, key, endpoint["id"])
        assert placed["replicas"] == 0
        assert _k8s_replicas(cluster, placed["namespace"], placed["k8s_name"]) == 0
        # Asleep means free: no usage accrues at all.
        usage = client.get(f"/tenants/{tenant['id']}/usage", headers=headers).json()
        assert Decimal(str(usage["total_gpu_seconds"])) == 0

        # Reported traffic at ~15 rps against a 5 rps/replica target -> 3 replicas.
        resp = client.post(
            f"/endpoints/{endpoint['id']}/load",
            json={"requests": int(15 * WINDOW)},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["desired_replicas"] == 3

        assert _tick_autoscaler(cluster) == {"scaled": 1}
        woken = _endpoint(client, key, endpoint["id"])
        assert woken["replicas"] == 3
        assert _k8s_replicas(cluster, placed["namespace"], placed["k8s_name"]) == 3

        # Awake means metered: 3 replicas x 1 GPU are now on the clock.
        usage = client.get(f"/tenants/{tenant['id']}/usage", headers=headers).json()
        assert Decimal(str(usage["total_gpu_seconds"])) > 0

        # Traffic stops. Past the idle window the endpoint goes back to sleep.
        later = datetime.now(UTC) + timedelta(
            seconds=settings.scale_to_zero_after_seconds + 10
        )
        assert _tick_autoscaler(cluster, now=later) == {"scaled": 1}
        asleep = _endpoint(client, key, endpoint["id"])
        assert asleep["replicas"] == 0
        assert _k8s_replicas(cluster, placed["namespace"], placed["k8s_name"]) == 0

        # And the meter froze when it did: usage read well after is unchanged.
        frozen = client.get(f"/tenants/{tenant['id']}/usage", headers=headers).json()
        time.sleep(2)
        again = client.get(f"/tenants/{tenant['id']}/usage", headers=headers).json()
        assert Decimal(str(again["total_gpu_seconds"])) == Decimal(
            str(frozen["total_gpu_seconds"])
        )

        events = client.get(
            f"/endpoints/{endpoint['id']}/autoscale-events", headers=headers
        ).json()
        assert [(e["from_replicas"], e["to_replicas"], e["reason"]) for e in events] == [
            (0, 3, REASON_SCALE_FROM_ZERO),
            (3, 0, REASON_SCALE_TO_ZERO),
        ]
    finally:
        client.delete(f"/endpoints/{endpoint['id']}", headers=headers)


def test_replica_growth_shows_up_in_cluster_gpu_accounting(
    client: TestClient, cluster: ClusterClient
) -> None:
    tenant = _create_tenant(client)
    key = _issue_key(client, tenant["id"])
    endpoint = _provision_endpoint(client, key, min_replicas=1, max_replicas=4)
    headers = {"X-Kestrel-Key": key}

    try:
        _drive_reconcile(
            cluster, until=lambda: _endpoint(client, key, endpoint["id"])["status"] == "running"
        )
        placed = _endpoint(client, key, endpoint["id"])
        node = placed["node_name"]

        def gpu_used(node_name: str) -> int:
            nodes = client.get("/cluster/nodes", headers=ADMIN_HEADERS).json()
            return next(n["gpu_used"] for n in nodes if n["name"] == node_name)

        before = gpu_used(node)
        client.post(
            f"/endpoints/{endpoint['id']}/load",
            json={"requests": int(20 * WINDOW)},
            headers=headers,
        )
        _tick_autoscaler(cluster)

        assert _endpoint(client, key, endpoint["id"])["replicas"] == 4
        # Scaling is a real capacity change, not just a number on the endpoint:
        # the node's GPU accounting has to move by the same three GPUs.
        assert gpu_used(node) == before + 3
    finally:
        client.delete(f"/endpoints/{endpoint['id']}", headers=headers)
