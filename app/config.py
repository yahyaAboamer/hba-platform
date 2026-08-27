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

    # §11.2. The first month the platform is responsible for paying. Everything
    # before it is `historical`: imported and visible, never payable.
    #
    # **Blank on purpose, and blank blocks every approval.** An unset go-live
    # that defaulted to something would silently make eight months of imported
    # orders look approvable - money already settled outside the platform, ready
    # to be paid a second time. Refusing until somebody chooses is the whole
    # point (§21, open question 1).
    go_live_month: str = ""

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

    # Where links in emails point. Blank means the platform will not put a
    # link in an email at all rather than send one to localhost - a sign-in
    # link that goes nowhere is worse than no email, because it teaches twenty
    # people that mail from HBA is broken.
    public_base_url: str = ""

    # Mail. Blank by default so the platform runs, queues and records what it
    # *would* have sent on a machine with no credentials - the same rule
    # Shopify follows, and what keeps the test suite from needing a mail
    # server.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    # STARTTLS on 587. Only turned off for a local capture server; there is no
    # reason to send credentials to a real host in the clear.
    smtp_use_tls: bool = True
    smtp_timeout_seconds: float = 20.0
    # What a recipient sees in the From line. The address must be one the SMTP
    # account is allowed to send as - Gmail refuses anything else, which is a
    # useful refusal.
    mail_from_address: str = ""
    mail_from_name: str = "HBA Aesthetics"
    # Where operational warnings go (Section 16). Blank means nowhere, and the
    # in-platform view is the only channel.
    maintainer_email: str = ""

    # The worker runs inside the API process. With one replica that is simpler
    # and cheaper than a second service, and because jobs are leased rather
    # than assigned, splitting it out later needs no change to the queue.
    worker_enabled: bool = True
    # An idle poll is one indexed lookup against a partial index covering only
    # pending and running rows - microseconds, roughly 43,000 times a day. That
    # is cheaper than the moving parts of LISTEN/NOTIFY, and it caps the delay
    # between a webhook arriving and its order syncing at two seconds.
    worker_poll_seconds: float = 2.0

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
    def mail_configured(self) -> bool:
        """Whether an email could actually be sent.

        A host and a From address are the minimum. Credentials are not
        required: a relay on a private network may accept unauthenticated mail,
        and demanding a username would make that setup impossible to express.
        """
        return bool(self.smtp_host.strip() and self.mail_from_address.strip())

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"


settings = Settings()
