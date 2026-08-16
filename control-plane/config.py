from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://foundry:foundry@localhost:5432/foundry"
    redis_url: str = "redis://localhost:6379/0"
    kubeconfig_path: str | None = None
    default_namespace: str = "default"


settings = Settings()
