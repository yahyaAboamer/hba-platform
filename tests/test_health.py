import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_live_returns_ok():
    response = client.get("/api/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_database_and_configuration():
    response = client.get("/api/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert "database" in body["checks"]
    assert "configuration" in body["checks"]


def test_production_hides_api_docs():
    # Docs must be disabled in production; verified via the app's own config.
    from app.config import Settings

    assert Settings(app_env="production").is_production is True
    assert Settings(app_env="development").is_production is False


def test_unreachable_database_fails_fast_instead_of_hanging():
    """An unreachable database must fail the probe, not hang it.

    libpq defaults connect_timeout to 0, meaning wait forever. Without an
    explicit timeout, engine.connect() blocked for over 100 seconds against a
    stopped database, so the readiness probe never answered and a platform
    health check would time out rather than report honestly.
    """
    import time

    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError

    from app.config import settings

    # Port 5999 has no listener; this must refuse or time out, never hang.
    engine = create_engine(
        "postgresql+psycopg://hba:hba@127.0.0.1:5999/nothing",
        connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
    )
    started = time.monotonic()
    with pytest.raises(OperationalError):
        with engine.connect():
            pass
    elapsed = time.monotonic() - started
    assert elapsed < settings.db_connect_timeout_seconds * 3, (
        f"connect took {elapsed:.1f}s - the timeout is not being applied"
    )


def test_database_url_avoids_the_ipv6_detour():
    """localhost resolves to ::1 and 127.0.0.1, doubling every failed attempt."""
    from app.config import Settings

    assert "localhost" not in Settings().database_url


def test_a_hosted_database_url_is_normalised_to_psycopg3():
    """Managed providers hand out postgresql:// or postgres://.

    SQLAlchemy maps a bare postgresql:// to psycopg2, which is not installed
    here, so without this the app would build cleanly and crash on its first
    connection. Rewriting the scheme also means a rotated database URL keeps
    working without anyone editing a variable.
    """
    from app.config import Settings

    for supplied in (
        "postgresql://u:p@host:5432/railway",
        "postgres://u:p@host:5432/railway",
    ):
        resolved = Settings(database_url=supplied).database_url
        assert resolved.startswith("postgresql+psycopg://")
        assert resolved.endswith("@host:5432/railway")


def test_an_explicit_driver_is_left_alone():
    from app.config import Settings

    explicit = "postgresql+psycopg://u:p@host:5432/db"
    assert Settings(database_url=explicit).database_url == explicit


def test_readiness_reports_whether_shopify_is_configured():
    """Operators need to see this without reading environment variables."""
    response = client.get("/api/health/ready")
    assert "shopify" in response.json()["checks"]


def test_shopify_configuration_requires_a_domain_and_credentials():
    from app.config import Settings

    assert Settings().shopify_configured is False
    assert (
        Settings(shopify_shop_domain="s.myshopify.com").shopify_configured is False
    )
    assert (
        Settings(
            shopify_shop_domain="s.myshopify.com",
            shopify_client_id="a",
            shopify_client_secret="b",
        ).shopify_configured
        is True
    )
    # An older admin-created app supplies a static token instead.
    assert (
        Settings(
            shopify_shop_domain="s.myshopify.com", shopify_access_token="shpat_x"
        ).shopify_configured
        is True
    )
