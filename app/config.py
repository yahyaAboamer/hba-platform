"""Application settings, read once from the environment."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform"
    app_env: str = "development"
    session_hours: int = 12
    db_connect_timeout_seconds: int = 5

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"


settings = Settings()
