from sqlalchemy import text

from app.db import engine


def test_database_is_reachable():
    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar() == 1


def test_alembic_version_table_exists_after_upgrade():
    with engine.connect() as connection:
        result = connection.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_name = 'alembic_version'"
            )
        ).scalar()
    assert result == 1, "run: alembic upgrade head"
