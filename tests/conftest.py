"""Shared test fixtures."""

import pytest
from sqlalchemy import text

from app.db import SessionLocal, engine


@pytest.fixture()
def db():
    """A session wrapped in a transaction that is always rolled back.

    Tests using this fixture never leave rows behind, so they can run in any
    order and cannot interfere with each other.
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
def clean_tables():
    """Truncate identity tables. Only for tests that need real commits."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE invitation, auth_session, role_assignment, user_account "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield
