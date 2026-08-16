from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolved to an absolute path so both .env discovery and any relative paths *within*
# .env (e.g. KUBECONFIG_PATH) behave the same regardless of the process's cwd — matters
# because pytest/alembic/uvicorn are invoked from different directories in practice.
_CONTROL_PLANE_DIR = Path(__file__).parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_CONTROL_PLANE_DIR / ".env", extra="ignore")

    database_url: str = "postgresql+psycopg://foundry:foundry@localhost:5432/foundry"
    redis_url: str = "redis://localhost:6379/0"
    kubeconfig_path: str | None = None
    default_namespace: str = "default"
    admin_token: str

    @field_validator("kubeconfig_path")
    @classmethod
    def _resolve_kubeconfig_path(cls, v: str | None) -> str | None:
        if v is None or Path(v).is_absolute():
            return v
        return str((_CONTROL_PLANE_DIR / v).resolve())


settings = Settings()
