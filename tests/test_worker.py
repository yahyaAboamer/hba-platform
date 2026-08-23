"""The background worker.

These tests use ``fresh_database`` rather than ``db``: the worker owns its own
transactions, committing the lease before running a handler and the outcome
after, so it cannot run inside a transaction the test rolls back.
"""

import logging

import pytest
from sqlalchemy import text

from app.core.signals import Anomaly
from app.db import SessionLocal
from app.services.jobs import MAX_ATTEMPTS, JobStatus, PermanentFailure, enqueue
from app.worker import HANDLERS, register_handler, run_one, worker_identity


@pytest.fixture(autouse=True)
def _isolated_handlers():
    """Never let a test's handler leak into another test."""
    original = dict(HANDLERS)
    yield
    HANDLERS.clear()
    HANDLERS.update(original)


@pytest.fixture()
def session(fresh_database):
    """A committing session. The schema is rebuilt on teardown."""
    with SessionLocal() as db:
        yield db


def _status(db, job_id):
    db.commit()
    return db.execute(
        text("SELECT status, attempts, last_error FROM background_job WHERE id = :i"),
        {"i": job_id},
    ).one()


# ── Handling work ──────────────────────────────────────────────────────────────


def test_run_one_reports_when_there_is_nothing_to_do(session):
    assert run_one(session, worker_id="w") is False


def test_a_job_is_handled_and_marked_succeeded(session):
    seen = []

    @register_handler("test_kind")
    def handle(db, payload):
        seen.append(payload["value"])

    job = enqueue(session, "test_kind", {"value": 42})
    session.commit()
    job_id = job.id

    assert run_one(session, worker_id="w") is True
    assert seen == [42]

    status, attempts, _ = _status(session, job_id)
    assert status == JobStatus.SUCCEEDED
    assert attempts == 0


def test_a_handler_receives_a_working_session(session):
    """Handlers write through the session they are given, in one transaction."""

    @register_handler("writes")
    def handle(db, payload):
        db.execute(
            text("INSERT INTO background_job (kind, payload) VALUES ('written', '{}')")
        )

    enqueue(session, "writes", {})
    session.commit()
    run_one(session, worker_id="w")

    written = session.execute(
        text("SELECT count(*) FROM background_job WHERE kind = 'written'")
    ).scalar()
    assert written == 1


# ── Failure ────────────────────────────────────────────────────────────────────


def test_a_handler_that_raises_marks_the_job_for_retry(session):
    @register_handler("boom")
    def handle(db, payload):
        raise RuntimeError("the API was down")

    job = enqueue(session, "boom", {})
    session.commit()
    job_id = job.id

    assert run_one(session, worker_id="w") is True

    status, attempts, last_error = _status(session, job_id)
    assert status == JobStatus.PENDING
    assert attempts == 1
    assert "the API was down" in last_error
    assert "RuntimeError" in last_error


def test_a_handler_s_writes_are_discarded_when_it_fails(session):
    """A half-finished job must not leave half its effects behind."""

    @register_handler("writes_then_fails")
    def handle(db, payload):
        db.execute(
            text("INSERT INTO background_job (kind, payload) VALUES ('partial', '{}')")
        )
        raise RuntimeError("failed after writing")

    job = enqueue(session, "writes_then_fails", {})
    session.commit()
    job_id = job.id

    run_one(session, worker_id="w")

    leftover = session.execute(
        text("SELECT count(*) FROM background_job WHERE kind = 'partial'")
    ).scalar()
    assert leftover == 0, "the handler's write survived its own failure"

    _, attempts, _ = _status(session, job_id)
    assert attempts == 1, "the retry state was rolled back along with the work"


def test_the_failure_record_survives_the_rollback_that_discards_the_work(session):
    """The subtle one: rolling back the handler must not roll back the fact
    that it was attempted, or the job retries forever with attempts stuck at 0.
    """

    @register_handler("always_fails")
    def handle(db, payload):
        db.execute(text("SELECT 1"))
        raise RuntimeError("nope")

    job = enqueue(session, "always_fails", {})
    session.commit()
    job_id = job.id

    for expected in range(1, MAX_ATTEMPTS + 1):
        session.execute(
            text("UPDATE background_job SET run_after = now() - interval '1 second' "
                 "WHERE id = :i"),
            {"i": job_id},
        )
        session.commit()
        run_one(session, worker_id="w")
        _, attempts, _ = _status(session, job_id)
        assert attempts == expected

    status, _, _ = _status(session, job_id)
    assert status == JobStatus.FAILED


# ── A kind nobody handles ──────────────────────────────────────────────────────


def test_an_unknown_kind_fails_immediately_rather_than_retrying(session, caplog):
    """Retrying is for failures that might succeed next time. A missing handler
    will never succeed, so five attempts over eight minutes buy nothing and
    delay the signal.
    """
    job = enqueue(session, "no_such_handler", {})
    session.commit()
    job_id = job.id

    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        assert run_one(session, worker_id="w") is True

    status, attempts, last_error = _status(session, job_id)
    assert status == JobStatus.FAILED
    assert attempts == MAX_ATTEMPTS
    assert "no handler" in last_error.lower()
    assert Anomaly.NO_HANDLER in caplog.text
    assert "no_such_handler" in caplog.text


# ── Registration ───────────────────────────────────────────────────────────────


def test_registering_two_handlers_for_one_kind_is_refused():
    """Two handlers for one kind means one silently never runs."""

    @register_handler("dup")
    def first(db, payload):
        pass

    with pytest.raises(ValueError, match="already registered"):

        @register_handler("dup")
        def second(db, payload):
            pass


def test_a_handler_keeps_working_after_registration():
    """The decorator returns the function, not None."""

    @register_handler("returned")
    def handle(db, payload):
        return "still callable"

    assert handle(None, {}) == "still callable"


def test_the_worker_identity_distinguishes_processes():
    identity = worker_identity()
    assert ":" in identity
    assert identity == worker_identity()


# ── The worker actually starts with the app ────────────────────────────────────


def test_the_worker_runs_when_the_application_starts(session, monkeypatch):
    """The failure this guards against is silent: the worker never starts, no
    error appears anywhere, and background work simply never happens.

    Nothing else in the suite exercises the lifespan wiring - every other test
    calls the worker directly.
    """
    import time

    from fastapi.testclient import TestClient

    from app.config import settings
    from app.main import app

    done = []

    @register_handler("started_by_app")
    def handle(db, payload):
        done.append(payload["marker"])

    enqueue(session, "started_by_app", {"marker": "ran"})
    session.commit()

    monkeypatch.setattr(settings, "worker_enabled", True)
    monkeypatch.setattr(settings, "worker_poll_seconds", 0.05)

    # Entering the context manager is what runs the lifespan; a bare
    # TestClient(app) does not.
    with TestClient(app):
        deadline = time.monotonic() + 10
        while not done and time.monotonic() < deadline:
            time.sleep(0.05)

    assert done == ["ran"], "the worker did not start with the application"


def test_the_worker_stays_off_when_disabled(session, monkeypatch):
    """WORKER_ENABLED=false must genuinely stop it, or the tests race it."""
    import time

    from fastapi.testclient import TestClient

    from app.config import settings
    from app.main import app

    done = []

    @register_handler("should_not_run")
    def handle(db, payload):
        done.append(1)

    enqueue(session, "should_not_run", {})
    session.commit()

    monkeypatch.setattr(settings, "worker_enabled", False)

    with TestClient(app):
        time.sleep(0.5)

    assert done == []


# ── Failures that will not get better ──────────────────────────────────────────


def test_a_permanent_failure_gives_up_on_the_first_attempt(session):
    """Retrying is for failures that might succeed next time. A missing
    credential is not one, and four more identical failures over eight minutes
    only bury the line that explains the problem.
    """

    @register_handler("hopeless")
    def handle(db, payload):
        raise PermanentFailure("SHOPIFY_CLIENT_SECRET is not set")

    job = enqueue(session, "hopeless", {})
    session.commit()
    job_id = job.id

    assert run_one(session, worker_id="w") is True

    status, attempts, last_error = _status(session, job_id)
    assert status == JobStatus.FAILED
    assert attempts == MAX_ATTEMPTS, "did not skip the remaining attempts"
    assert "SHOPIFY_CLIENT_SECRET" in last_error
    assert run_one(session, worker_id="w") is False, "the job was leased again"


def test_an_ordinary_failure_still_retries(session):
    """Guards the test above: PermanentFailure must be the exception, not the
    rule. A Shopify timeout has to keep retrying.
    """

    @register_handler("temporary")
    def handle(db, payload):
        raise TimeoutError("Shopify took too long")

    job = enqueue(session, "temporary", {})
    session.commit()
    job_id = job.id

    run_one(session, worker_id="w")

    status, attempts, _ = _status(session, job_id)
    assert status == JobStatus.PENDING
    assert attempts == 1


def test_a_permanent_failure_still_discards_the_handler_s_writes(session):
    """Giving up early must not mean committing half a job."""

    @register_handler("hopeless_writer")
    def handle(db, payload):
        db.execute(
            text("INSERT INTO background_job (kind, payload) VALUES ('half', '{}')")
        )
        raise PermanentFailure("no")

    enqueue(session, "hopeless_writer", {})
    session.commit()
    run_one(session, worker_id="w")

    leftover = session.execute(
        text("SELECT count(*) FROM background_job WHERE kind = 'half'")
    ).scalar()
    assert leftover == 0
