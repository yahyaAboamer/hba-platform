"""Production starts from zero (ADR 0085, migration e5b9a3d70038).

The old framed Production app is retired: its eleven tables are dropped, its
API and its static app are gone. What stays is the supplier list, because the
new orders, purchases, ratings and factory logins all point at it.
"""

import importlib.util

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import Base, engine
from app.main import app
from tests.conftest import alembic_head

#: The old app's tables, children first (the order the migration drops them).
OLD_TABLES = (
    "production_stage_update",
    "production_order_stage",
    "production_qc_check",
    "production_order",
    "production_product",
    "production_phase",
    "production_activity",
    "production_document",
    "production_task",
    "production_sample",
    "production_fixture",
)
KEPT_TABLES = ("production_supplier", "production_supplier_category")
#: The new tables whose foreign keys point at a supplier.
POINTING_AT_SUPPLIERS = ("prod_order", "prod_purchase", "prod_supplier_entry", "prod_rating", "prod_factory_access")


def _tables() -> set[str]:
    with engine.connect() as connection:
        return set(connection.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")))


def _supplier_keys() -> set[tuple[str, str]]:
    """(table, column) of every foreign key that points at `production_supplier`."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT cl.relname, att.attname FROM pg_constraint con "
                "JOIN pg_class cl ON cl.oid = con.conrelid "
                "JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ANY (con.conkey) "
                "WHERE con.contype = 'f' AND con.confrelid = 'production_supplier'::regclass"
            )
        )
        return {(table, column) for table, column in rows}


# ── The database ──────────────────────────────────────────────────────────────

def _own_keys(table: str) -> set[tuple[str, str]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT cl.relname, att.attname FROM pg_constraint con "
                "JOIN pg_class cl ON cl.oid = con.conrelid "
                "JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ANY (con.conkey) "
                "WHERE con.contype = 'f' AND con.conrelid = CAST(:t AS regclass)"
            ),
            {"t": table},
        )
        return {(name, column) for name, column in rows}



def test_the_old_tables_are_gone_and_the_suppliers_stay():
    tables = _tables()
    assert not set(OLD_TABLES) & tables
    assert set(KEPT_TABLES) <= tables


def test_every_foreign_key_the_new_tables_hold_to_a_supplier_is_intact():
    pointing = {table for table, _ in _supplier_keys()}
    assert set(POINTING_AT_SUPPLIERS) <= pointing
    assert ("production_supplier", "category_id") in _own_keys("production_supplier")


def test_the_models_no_longer_describe_the_old_tables():
    assert not set(OLD_TABLES) & set(Base.metadata.tables)
    assert set(KEPT_TABLES) <= set(Base.metadata.tables)


def test_the_downgrade_recreates_the_old_tables_empty_and_the_upgrade_drops_them_again(fresh_database):
    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO production_supplier_category (id, name) VALUES ('cat-x', 'Fabric')"))
        connection.execute(
            text(
                "INSERT INTO production_supplier (id, code, name, category_id, active) "
                "VALUES ('sup-x', 'SUP-X', 'Kept workshop', 'cat-x', true)"
            )
        )
    keys_before = _supplier_keys()
    try:
        command.downgrade(config, "d4a8f2c60037")
        assert set(OLD_TABLES) <= _tables()
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "d4a8f2c60037"
            )
            for table in OLD_TABLES:
                assert connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one() == 0, table
            # The suppliers were never touched.
            assert connection.execute(text("SELECT name FROM production_supplier")).scalar_one() == "Kept workshop"
    finally:
        command.upgrade(config, "head")

    assert not set(OLD_TABLES) & _tables()
    assert _supplier_keys() == keys_before
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == alembic_head()
        assert connection.execute(text("SELECT name FROM production_supplier")).scalar_one() == "Kept workshop"
        assert connection.execute(text("SELECT count(*) FROM production_supplier_category")).scalar_one() == 1


# ── The service ───────────────────────────────────────────────────────────────

client = TestClient(app)


@pytest.mark.parametrize(
    "path",
    [
        "/api/production/state",
        "/api/production/fixtures",
        "/api/production/documents",
        "/api/production/order-photos/anything",
        "/api/production/actions/create_order",
    ],
)
def test_the_old_api_is_not_served(path):
    assert client.get(path).status_code == 404
    # A write finds nothing to run: the shell's catch-all answers GET only.
    assert client.post(path).status_code in (404, 405)


def test_no_route_is_left_under_the_old_api_prefix():
    # `/api/prod/...` is the new Production; `/api/production/...` was the old.
    assert [route.path for route in app.routes if getattr(route, "path", "").startswith("/api/production")] == []


@pytest.mark.parametrize(
    "path",
    ["/production-app", "/production-app/", "/production-app/assets/index.js", "/production-app/orders", "/production-app/favicon.svg"],
)
def test_the_framed_app_is_not_served(path):
    response = client.get(path)
    assert response.status_code == 404
    # And it never answers as a page the platform lets itself frame.
    assert "frame-ancestors" not in response.headers.get("content-security-policy", "")


def test_the_old_code_is_not_importable():
    for module in (
        "app.modules.production.api",
        "app.modules.production.services",
        "app.modules.production.services.actions",
        "app.modules.production.services.state",
        "app.modules.production.services.files",
    ):
        try:
            found = importlib.util.find_spec(module)
        except ModuleNotFoundError:  # the parent package is gone too
            found = None
        assert found is None, module
