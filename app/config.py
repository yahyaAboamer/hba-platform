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

    # Shopify. Blank by default so the platform runs without it: health checks
    # and authentication must keep working on a machine with no credentials.
    shopify_shop_domain: str = ""
    # HBA's app is a Dev Dashboard app, so tokens are short-lived and exchanged
    # from the client credentials. The static token stays supported for an older
    # admin-created app.
    shopify_client_id: str = ""
    shopify_client_secret: str = ""
    shopify_access_token: str = ""
    shopify_webhook_secret: str = ""
    # Pinned deliberately. Shopify deprecates versions on a schedule, and an
    # unpinned client would change behaviour without a deploy.
    shopify_api_version: str = "2026-07"
    shopify_timeout_seconds: float = 20.0

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
    def shopify_configured(self) -> bool:
        has_credentials = bool(self.shopify_client_id and self.shopify_client_secret)
        return bool(
            self.shopify_shop_domain and (has_credentials or self.shopify_access_token)
        )

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"


settings = Settings()
