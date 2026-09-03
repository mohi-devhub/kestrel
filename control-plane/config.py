from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolved to an absolute path so both .env discovery and any relative paths *within*
# .env (e.g. KUBECONFIG_PATH) behave the same regardless of the process's cwd — matters
# because pytest/alembic/uvicorn are invoked from different directories in practice.
_CONTROL_PLANE_DIR = Path(__file__).parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_CONTROL_PLANE_DIR / ".env", extra="ignore")

    database_url: str = "postgresql+psycopg://kestrel:kestrel@localhost:5432/kestrel"
    redis_url: str = "redis://localhost:6379/0"
    kubeconfig_path: str | None = None
    default_namespace: str = "default"
    admin_token: str
    reconcile_interval_seconds: float = 2.0

    # Autoscaling. Defaults are platform-wide; max/min replicas and the RPS target
    # are per-endpoint overrides on the workload spec.
    autoscale_interval_seconds: float = 5.0
    autoscale_window_seconds: float = 30.0
    autoscale_target_rps_per_replica: float = 5.0
    scale_to_zero_after_seconds: float = 60.0
    # Scale-up is immediate; scale-down waits this long after the last replica change
    # so a brief dip in traffic can't flap an endpoint down and straight back up.
    scale_down_stabilization_seconds: float = 30.0
    # A scale-up may not grow a tenant's burn rate past what their remaining budget
    # can sustain for this long — the horizon `economics.runway.budget_headroom_gpus`
    # sizes headroom against.
    budget_headroom_horizon_seconds: float = 300.0

    @field_validator("kubeconfig_path")
    @classmethod
    def _resolve_kubeconfig_path(cls, v: str | None) -> str | None:
        if v is None or Path(v).is_absolute():
            return v
        return str((_CONTROL_PLANE_DIR / v).resolve())


settings = Settings()
