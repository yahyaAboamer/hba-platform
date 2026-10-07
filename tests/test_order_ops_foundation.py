"""What every Operations tab stands on (ADR 0057, build plan phase 2).

- How fresh each source's numbers are, and the five states that keeps apart.
- One read of one source: not connected is not a failure, and a failure is
  still on record after the worker has rolled the job back.
- The Operations API's one guard.
"""

import logging
from datetime import timedelta

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api import order_ops
from app.core.businesstime import utcnow
from app.db import SessionLocal, engine
from app.main import app
from app.services.jobs import JobStatus, PermanentFailure, enqueue
from app.services.order_ops.freshness import (
    FRESH_FOR,
    State,
    describe,
    record_failure,
    record_not_connected,
    record_success,
)
from app.services.order_ops.polling import (
    POLL_EVERY,
    KeyRefused,
    NotConnected,
    SourceUnavailable,
    run_poll,
)
from app.worker import HANDLERS, SCHEDULE_CHECK_SECONDS, register_handler, run_one

# ── Freshness ─────────────────────────────────────────────────────────────────


def test_a_source_never_read_says_so(db):
    described = describe(db, "shopify")
    assert described["state"] == State.NEVER
    assert described["updated_at"] is None
    assert described["label"] == "Shopify"


def test_a_clean_read_is_fresh_with_its_time_and_count(db):
    read_at = utcnow() - timedelta(minutes=3)
    record_success(db, "bosta", 165, at=read_at)

    described = describe(db, "bosta")

    assert described["state"] == State.FRESH
    assert described["updated_at"] == read_at.isoformat()
    assert described["row_count"] == 165
    assert described["error"] is None


def test_ten_minutes_is_still_fresh_and_a_moment_more_is_stale(db):
    read_at = utcnow()
    record_success(db, "estebdal", 3, at=read_at)

    assert describe(db, "estebdal", now=read_at + FRESH_FOR)["state"] == State.FRESH
    stale = describe(db, "estebdal", now=read_at + FRESH_FOR + timedelta(seconds=1))
    assert stale["state"] == State.STALE
    # Stale numbers still show, with their age.
    assert stale["updated_at"] == read_at.isoformat()


def test_a_failure_keeps_the_last_good_numbers_and_their_time(db):
    read_at = utcnow() - timedelta(minutes=12)
    record_success(db, "bosta", 165, at=read_at)
    record_failure(db, "bosta", "Bosta didn't answer.")

    described = describe(db, "bosta")

    assert described["state"] == State.FAILED
    assert described["error"] == "Bosta didn't answer."
    assert described["updated_at"] == read_at.isoformat()
    assert described["row_count"] == 165


def test_a_failure_before_any_good_read_has_no_numbers_to_show(db):
    record_failure(db, "bosta", "Bosta didn't answer.")
    described = describe(db, "bosta")
    assert described["state"] == State.FAILED
    assert described["updated_at"] is None
    assert described["row_count"] is None


def test_the_next_clean_read_clears_a_failure(db):
    record_failure(db, "shopify", "Shopify didn't answer.")
    record_success(db, "shopify", 40)
    described = describe(db, "shopify")
    assert described["state"] == State.FRESH
    assert described["error"] is None


def test_no_key_is_not_connected_rather_than_failed_or_zero(db):
    record_success(db, "estebdal", 3, at=utcnow() - timedelta(hours=1))
    record_not_connected(db, "estebdal")
    described = describe(db, "estebdal")
    assert described["state"] == State.NOT_CONNECTED
    assert described["error"] is None


def test_a_record_after_a_read_is_seen_by_the_next_read(db):
    """The same session reads, records and reads again, as a poll followed by
    a page would; the second read must not be the first one remembered."""
    record_success(db, "shopify", 40)
    assert describe(db, "shopify")["state"] == State.FRESH
    record_failure(db, "shopify", "Shopify didn't answer.")
    assert describe(db, "shopify")["state"] == State.FAILED


def test_a_long_reason_is_cut_to_a_sentence(db):
    record_failure(db, "bosta", "x" * 5000)
    assert len(describe(db, "bosta")["error"]) == 500


def test_an_unknown_source_is_refused(db):
    with pytest.raises(ValueError, match="Unknown operations source"):
        record_success(db, "aramex", 1)
    with pytest.raises(ValueError, match="Unknown operations source"):
        describe(db, "aramex")


def test_the_database_refuses_an_unknown_source(db):
    with pytest.raises(IntegrityError):
        db.execute(text("INSERT INTO ops_source_status (source) VALUES ('aramex')"))
        db.flush()


def test_five_minute_reads_keep_numbers_inside_the_promise():
    """The gap after a read, plus the worker's look for due work, must leave
    room before a clean read turns stale."""
    assert POLL_EVERY + timedelta(seconds=SCHEDULE_CHECK_SECONDS) < FRESH_FOR


# ── One read of one source ────────────────────────────────────────────────────


def test_a_clean_read_records_what_it_stored(db):
    assert run_poll(db, "estebdal", lambda session: 3) == 3
    assert describe(db, "estebdal")["state"] == State.FRESH
    assert describe(db, "estebdal")["row_count"] == 3


def test_no_key_records_not_connected_and_does_not_fail(db):
    def poll(session):
        raise NotConnected

    assert run_poll(db, "bosta", poll) is None
    assert describe(db, "bosta")["state"] == State.NOT_CONNECTED


def test_a_refused_key_is_permanent():
    """Retrying the same key four more times buys nothing."""
    assert issubclass(KeyRefused, PermanentFailure)
    assert issubclass(KeyRefused, SourceUnavailable)


@pytest.fixture()
def committing(fresh_database):
    with SessionLocal() as session:
        yield session


def test_a_failed_read_stays_on_record_after_the_rollback(committing):
    def poll(session):
        raise SourceUnavailable("Bosta didn't answer.")

    assert run_poll(committing, "bosta", poll) is None
    committing.commit()  # an expected failure is recorded and the job succeeds

    described = describe(committing, "bosta")
    assert described["state"] == State.FAILED
    assert described["error"] == "Bosta didn't answer."


def test_an_unexpected_error_shows_a_plain_reason_and_logs_no_detail(committing, caplog):
    secret = "https://app.bosta.co/api/v2?key=sk_live_do_not_show"

    def poll(session):
        raise RuntimeError(secret)

    with caplog.at_level(logging.INFO), pytest.raises(SourceUnavailable) as raised:
        run_poll(committing, "bosta", poll)
    committing.rollback()

    assert describe(committing, "bosta")["error"] == "Couldn't read Bosta."
    assert str(raised.value) == "Couldn't read Bosta."
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    assert secret not in caplog.text


def test_an_unexpected_permanent_failure_stays_permanent(committing):
    def poll(session):
        raise PermanentFailure("scope read_orders missing for shpat_do_not_show")

    with pytest.raises(PermanentFailure) as raised:
        run_poll(committing, "shopify", poll)
    assert "shpat_" not in str(raised.value)


@pytest.fixture()
def isolated_handlers():
    original = dict(HANDLERS)
    yield
    HANDLERS.clear()
    HANDLERS.update(original)


def test_through_the_worker_a_failure_is_kept_and_the_job_retried(
    committing, isolated_handlers
):
    def refuse(session):
        raise SourceUnavailable("E-stebdal didn't answer.")

    @register_handler("test_order_ops_read")
    def handle(session, payload):
        run_poll(session, "estebdal", refuse)

    job = enqueue(committing, "test_order_ops_read", {})
    committing.commit()
    job_id = job.id

    assert run_one(committing, worker_id="w") is True

    status = committing.execute(
        text("SELECT status, last_error FROM background_job WHERE id = :i"), {"i": job_id}
    ).one()
    assert status.status == JobStatus.SUCCEEDED  # recorded on the dashboard, not a failed job
    assert describe(committing, "estebdal")["state"] == State.FAILED


def test_through_the_worker_no_detail_reaches_the_job_or_its_log(
    committing, isolated_handlers, caplog
):
    """The worker records a failed job's own message - and shows it on the
    failed-jobs panel - so what it is handed must already be plain."""
    secret = "https://api.e-stebdal.com/api/v1/public/returns x-api-key=es_do_not_show"

    def explode(session):
        raise RuntimeError(secret)

    @register_handler("test_order_ops_leak")
    def handle(session, payload):
        run_poll(session, "estebdal", explode)

    job = enqueue(committing, "test_order_ops_leak", {})
    committing.commit()
    job_id = job.id

    with caplog.at_level(logging.INFO):
        assert run_one(committing, worker_id="w") is True

    last_error = committing.execute(
        text("SELECT last_error FROM background_job WHERE id = :i"), {"i": job_id}
    ).scalar_one()
    assert "Couldn't read E-stebdal." in last_error
    assert secret not in last_error
    assert secret not in caplog.text


def test_through_the_worker_no_key_is_a_job_that_succeeds(committing, isolated_handlers):
    """Not connected adds nothing to the failed-jobs panel every 5 minutes."""

    def no_key(session):
        raise NotConnected

    @register_handler("test_order_ops_unconnected")
    def handle(session, payload):
        run_poll(session, "bosta", no_key)

    job = enqueue(committing, "test_order_ops_unconnected", {})
    committing.commit()
    job_id = job.id

    run_one(committing, worker_id="w")

    status = committing.execute(
        text("SELECT status FROM background_job WHERE id = :i"), {"i": job_id}
    ).scalar_one()
    assert status == JobStatus.SUCCEEDED
    assert describe(committing, "bosta")["state"] == State.NOT_CONNECTED


def test_a_failed_source_shows_failed_even_once_its_numbers_are_old(db):
    """Failed outranks stale: the reason is the more useful thing to say."""
    record_success(db, "bosta", 165, at=utcnow() - timedelta(hours=2))
    record_failure(db, "bosta", "Bosta didn't answer.")
    assert describe(db, "bosta")["state"] == State.FAILED


# ── The Operations API's guard ────────────────────────────────────────────────

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "quiet-harbour-lantern",
}


@pytest.fixture()
def probe():
    """A route behind exactly the guard every Operations route gets.

    Operations has no route of its own until its tabs arrive, so this mounts
    one with the router's own dependencies and removes it afterwards.
    """
    router = APIRouter(prefix="/api/order-ops", dependencies=order_ops.router.dependencies)

    @router.get("/_probe")
    def _probe() -> dict:
        return {"ok": True}

    before = list(app.router.routes)
    app.include_router(router)
    # Ahead of the app's catch-all, which would otherwise answer 404 first.
    added = app.router.routes[len(before):]
    app.router.routes[:] = added + before
    yield "/api/order-ops/_probe"
    app.router.routes[:] = before


@pytest.fixture()
def client(fresh_database, probe):
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _demote_to(role: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = :r"), {"r": role})


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("admin", 200),
        ("operations_manager", 200),
        ("affiliate_manager", 403),
        ("content_manager", 403),
        ("affiliate", 403),
    ],
)
def test_only_the_operations_manager_and_the_admin_reach_operations(
    client, probe, role, expected
):
    if role != "admin":
        _demote_to(role)
    assert client.get(probe).status_code == expected


def test_nobody_signed_out_reaches_operations(fresh_database, probe):
    with TestClient(app) as anonymous:
        assert anonymous.get(probe).status_code == 401


def test_every_operations_route_carries_the_guard():
    for route in order_ops.router.routes:
        assert any(
            dependency.call is order_ops.GUARD for dependency in route.dependant.dependencies
        ), route.path


def test_each_response_carries_its_sources_freshness(db):
    record_success(db, "bosta", 165)
    assert order_ops.freshness(db, "bosta") == describe(db, "bosta")
