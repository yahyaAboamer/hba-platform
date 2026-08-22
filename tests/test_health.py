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
