"""Shared test fixtures."""

import os

# The worker must not race the tests for jobs, or compete with them for the
# schema while fresh_database is rebuilding it. Set before the app is imported,
# because Settings reads the environment once at import time.
os.environ["WORKER_ENABLED"] = "false"

import pytest  # noqa: E402
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db import SessionLocal, engine


@pytest.fixture(scope="session", autouse=True)
def _cheap_password_hashing():
    """Lower the password cost **for the test suite only**.

    `hash_password` deliberately costs about a second: 600,000 PBKDF2
    iterations, following OWASP guidance, because making an attacker's guessing
    slow is the entire point of it. In a test that cost buys nothing and
    dominates everything - every API test bootstraps an account, so the suite
    was spending over a minute per API file computing hashes nobody attacks.

    Patched on the module rather than read from configuration, deliberately.
    An environment variable could be set in production by accident; a
    monkeypatch inside the test session cannot leave it.

    `verify_password` reads the iteration count from the stored string, so
    everything round-trips exactly as it does in production - only faster.
    `test_the_shipped_password_cost_is_not_this_one` asserts what actually
    ships, so this can never quietly become the real setting.
    """
    from app.core import passwords

    original = passwords.ITERATIONS
    passwords.ITERATIONS = 1_000
    yield
    passwords.ITERATIONS = original


@pytest.fixture(scope="session", autouse=True)
def _clean_session_start():
    """Guarantee the first test of the session meets an empty database."""
    _rebuild_schema()
    yield


@pytest.fixture()
def db():
    """A session wrapped in a transaction that is always rolled back.

    Tests using this fixture never leave rows behind, so they can run in any
    order and cannot interfere with each other. This is the default: prefer it
    to anything that commits.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)
    try:
        yield session
    finally:
        # Roll the session back first. A test that deliberately provokes an
        # IntegrityError leaves the session in a failed state, and unwinding the
        # outer transaction on top of that raises a teardown warning that would
        # obscure a genuine one later.
        session.rollback()
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture()
def fresh_database():
    """An empty database, for tests that genuinely need committed state.

    Chiefly the API tests, which go through TestClient and therefore commit -
    and the bootstrap endpoint, which by definition only works when no account
    exists.

    **Emptied, not rebuilt.** An earlier version dropped the schema and re-ran
    every migration, on the grounds that TRUNCATE is refused by the append-only
    guards. That is true, and it was costing 2.2 seconds a test across 317
    tests - about 11 minutes of a 15-minute suite spent rebuilding a schema
    that had not changed. `session_replication_role` turns the guards off for
    the length of one transaction, which is 0.2 seconds instead.

    The guards come straight back: the setting is `SET LOCAL`, so it reverts
    when the transaction commits, and a test proves an UPDATE on `audit_event`
    is still refused afterwards.
    """
    yield
    # Emptied on the way out, not the way in. Every test that commits uses this
    # fixture and cleans up after itself, so the next one always starts clean -
    # and the session-scoped fixture below guarantees the first one does too.
    # Doing both ends would double the cost for no extra safety.
    #
    # Committed rows leaking into a later test file is not hypothetical: it
    # happened, and failed two identity tests on a unique email constraint.
    empty_the_database()


def empty_the_database() -> None:
    """Delete every row, keep the schema.

    `session_replication_role = replica` disables user triggers for the
    transaction, which is what lets TRUNCATE past the append-only guards on
    `audit_event`, `payment_transaction`, `payroll_snapshot` and the rest.
    Those guards exist so an audit trail cannot be wiped in production; a test
    database being emptied between tests is the one case where that is the
    point.

    **SET LOCAL, deliberately.** A session-level SET would ride along on the
    pooled connection and silently disable the guards for whatever ran next -
    which is exactly the sort of thing that makes a later test pass for the
    wrong reason.

    `alembic_version` is excluded: emptying it would make the schema look
    unmigrated and send the next run through every migration again.
    """
    with engine.begin() as connection:
        tables = list(
            connection.scalars(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' "
                    "AND tablename <> 'alembic_version'"
                )
            )
        )
        if not tables:
            return
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text(
                "TRUNCATE "
                + ", ".join(f'"{name}"' for name in tables)
                + " RESTART IDENTITY CASCADE"
            )
        )


def _rebuild_schema() -> None:
    """Drop everything and migrate from nothing.

    Run once at the start of a session. Keeping it is worth the 2.2 seconds:
    it proves the migrations still build a working schema from an empty
    database, which nothing else checks and which is how the platform is
    deployed.
    """
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    command.upgrade(Config("alembic.ini"), "head")
