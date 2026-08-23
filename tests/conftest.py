"""Shared test fixtures."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db import SessionLocal, engine


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
    """Rebuild the schema from scratch.

    Only for tests that genuinely need committed state and an empty database -
    chiefly the bootstrap endpoint, which by definition only works when no
    account exists.

    The obvious approach, TRUNCATE, does not work and should not. audit_event
    is append-only and refuses TRUNCATE, and truncating user_account cascades
    into it. That is the guard doing its job: an audit trail you can wipe is
    not an audit trail. So the schema is dropped and migrated again, which is
    the honest way to get an empty database and also proves the migrations
    build correctly from nothing on every run.
    """
    yield
    # Rebuild on the way out, not the way in. Every test that commits uses this
    # fixture and cleans up after itself, so the next one always starts clean -
    # and the session-scoped fixture below guarantees the first one does too.
    # Rebuilding at both ends would double the cost for no extra safety.
    #
    # Committed rows leaking into a later test file is not hypothetical: it
    # happened, and failed two identity tests on a unique email constraint.
    _rebuild_schema()


def _rebuild_schema() -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    command.upgrade(Config("alembic.ini"), "head")
