from fastapi import FastAPI
from redis import Redis
from sqlalchemy import create_engine, text

from cluster import ClusterClient
from config import settings

from .routers import admin, endpoints, jobs

app = FastAPI(title="Foundry control plane")
app.include_router(admin.router)
app.include_router(jobs.router)
app.include_router(endpoints.router)


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
        r = Redis.from_url(settings.redis_url)
        return bool(r.ping())
    except Exception:
        return False


def _check_cluster() -> bool:
    try:
        cluster = ClusterClient(kubeconfig_path=settings.kubeconfig_path)
        return len(cluster.list_nodes()) > 0
    except Exception:
        return False
