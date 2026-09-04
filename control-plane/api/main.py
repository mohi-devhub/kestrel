from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import create_engine, text

from cluster import ClusterClient
from config import settings
from db import SessionLocal
from obs import register_collector
from redis_client import get_redis

from .routers import admin, cluster, endpoints, jobs, usage, workloads

app = FastAPI(title="Kestrel control plane")
app.include_router(admin.router)
app.include_router(jobs.router)
app.include_router(endpoints.router)
app.include_router(cluster.router)
app.include_router(usage.router)
app.include_router(workloads.router)

# State metrics are derived from Postgres and the cluster at scrape time, so the
# collector needs a way to reach both. See obs/metrics.py for why they aren't
# accumulated in-process.
register_collector(
    SessionLocal, lambda: ClusterClient(kubeconfig_path=settings.kubeconfig_path)
)


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/healthz")
def healthz() -> dict[str, object]:
    checks = {"database": _check_database(), "redis": _check_redis(), "cluster": _check_cluster()}
    ok = all(checks.values())
    return {"ok": ok, "checks": checks}


def _check_database() -> bool:
    try:
        engine = create_engine(settings.database_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _check_redis() -> bool:
    try:
        return bool(get_redis().ping())
    except Exception:
        return False


def _check_cluster() -> bool:
    try:
        cluster = ClusterClient(kubeconfig_path=settings.kubeconfig_path)
        return len(cluster.list_nodes()) > 0
    except Exception:
        return False
