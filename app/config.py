"""Application settings, read once from the environment."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 127.0.0.1 rather than localhost: localhost resolves to both ::1 and
    # 127.0.0.1, so every failed connection is attempted twice.
    database_url: str = "postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform"
    app_env: str = "development"
    session_hours: int = 12
    db_connect_timeout_seconds: int = 5

    @field_validator("database_url")
    @classmethod
    def _use_psycopg3(cls, value: str) -> str:
        """Normalise the driver in a hosted DATABASE_URL.

        Railway (and most managed providers) hand out postgresql:// or
        postgres://. SQLAlchemy maps a bare postgresql:// to psycopg2, which is
        not installed here - this project uses psycopg 3 - so the application
        would build cleanly and then crash on its first connection.

        Rewriting the scheme rather than requiring the variable to be set by
        hand means a rotated database URL keeps working untouched.
        """
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix) :]
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"


settings = Settings()
