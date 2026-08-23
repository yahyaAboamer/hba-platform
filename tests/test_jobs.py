"""Durable background work.

Spec section 10.5. "No queues" means no extra infrastructure, not that
background work may vanish when the service restarts. Postgres is the queue.
"""

import logging
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.core.businesstime import utcnow
from app.core.signals import Anomaly
from app.models.integration import IntegrationEvent
from app.services.jobs import (
    ERROR_LIMIT,
    MAX_ATTEMPTS,
    JobStatus,
    complete_job,
    enqueue,
    fail_job,
    lease_job,
    payload_digest,
    record_event,
)


def _make_runnable(db, job) -> None:
    """Bring a backed-off job forward, standing in for the passage of time."""
    db.execute(
        text("UPDATE background_job SET run_after = now() - interval '1 second' "
             "WHERE id = :i"),
        {"i": job.id},
    )
    db.expire_all()


# ── Idempotent event receipts ──────────────────────────────────────────────────


def test_an_event_is_recorded_once(db):
    event, created = record_event(db, "shopify", "evt-1", "orders/create", {"id": 1})
    db.flush()
    assert created is True
    assert event.id is not None


def test_a_duplicate_delivery_is_detected_not_reprocessed(db):
    """Shopify retries webhooks. Processing twice would double-count."""
    record_event(db, "shopify", "evt-1", "orders/create", {"id": 1})
    db.flush()
    event, created = record_event(db, "shopify", "evt-1", "orders/create", {"id": 1})
    db.flush()
    assert created is False
    assert event is not None


def test_the_same_id_from_a_different_source_is_a_different_event(db):
    record_event(db, "shopify", "evt-1", "orders/create", {})
    db.flush()
    _, created = record_event(db, "estebdal", "evt-1", "returns/create", {})
    db.flush()
    assert created is True


# ── The receipt stores a digest, not a copy (ADR 0020) ─────────────────────────


def test_the_payload_is_digested_not_copied(db):
    """The table is append-only, so whatever it stores it stores forever.

    A receipt proves an event arrived. It is not an archive of Shopify's JSON,
    which can be re-fetched from Shopify at any time.
    """
    body = {"id": 5123456789, "note": "x" * 4000}
    event, _ = record_event(db, "shopify", "evt-2", "orders/create", body)
    db.flush()

    assert event.payload_digest == payload_digest(body)
    assert len(event.payload_digest) == 64
    assert not hasattr(event, "payload")


def test_the_digest_is_stable_across_key_order(db):
    """Two encodings of the same body must not look like different events."""
    assert payload_digest({"a": 1, "b": 2}) == payload_digest({"b": 2, "a": 1})


def test_the_digest_changes_when_the_body_changes(db):
    assert payload_digest({"id": 1}) != payload_digest({"id": 2})


def test_a_redelivery_with_different_content_is_reported(db, caplog):
    """Same event id, different body. Deduplicated, but not silently.

    This is why the digest is kept rather than dropped entirely: it is the only
    way to notice that a sender used an id we have already seen for something
    else. The first delivery still wins - but somebody gets told.
    """
    first, _ = record_event(db, "shopify", "evt-3", "orders/create", {"total": "100.00"})
    db.flush()

    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        again, created = record_event(
            db, "shopify", "evt-3", "orders/create", {"total": "999.00"}
        )
        db.flush()

    assert created is False
    assert again.id == first.id
    assert again.payload_digest == payload_digest({"total": "100.00"})
    assert Anomaly.EVENT_CONTENT_CHANGED in caplog.text
    assert "evt-3" in caplog.text


def test_an_identical_redelivery_is_not_reported(db, caplog):
    """The ordinary case is silent, or the signal is worthless."""
    record_event(db, "shopify", "evt-3b", "orders/create", {"total": "100.00"})
    db.flush()

    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        record_event(db, "shopify", "evt-3b", "orders/create", {"total": "100.00"})
        db.flush()

    assert Anomaly.EVENT_CONTENT_CHANGED not in caplog.text


def test_the_entity_the_event_refers_to_is_recorded(db):
    """"Did we ever receive anything for order X?" must be answerable."""
    event, _ = record_event(
        db, "shopify", "evt-4", "orders/create", {"id": 1}, entity_id="5123456789"
    )
    db.flush()
    found = db.query(IntegrationEvent).filter_by(entity_id="5123456789").one()
    assert found.id == event.id


def test_an_empty_payload_is_recorded_without_a_digest(db):
    """A webhook with no body is odd but not an error."""
    event, created = record_event(db, "shopify", "evt-5", "shop/update", None)
    db.flush()
    assert created is True
    assert event.payload_digest is None


# ── The receipt is immutable ───────────────────────────────────────────────────


def test_event_receipts_cannot_be_altered(db):
    """An immutable receipt is the whole point: it proves what arrived."""
    event, _ = record_event(db, "shopify", "evt-9", "orders/create", {})
    db.flush()
    with pytest.raises(DatabaseError):
        db.execute(
            text("UPDATE integration_event SET topic = 'x' WHERE id = :i"),
            {"i": event.id},
        )


def test_event_receipts_cannot_be_deleted(db):
    event, _ = record_event(db, "shopify", "evt-10", "orders/create", {})
    db.flush()
    with pytest.raises(DatabaseError):
        db.execute(text("DELETE FROM integration_event WHERE id = :i"), {"i": event.id})


def test_the_event_table_cannot_be_truncated(db):
    """A row-level trigger does not fire on TRUNCATE. A second one is needed."""
    with pytest.raises(DatabaseError):
        db.execute(text("TRUNCATE integration_event"))


# ── Queue mechanics ────────────────────────────────────────────────────────────


def test_an_enqueued_job_can_be_leased(db):
    enqueue(db, "sync_order", {"order_id": "1"})
    db.flush()
    job = lease_job(db, worker_id="worker-a")
    assert job is not None
    assert job.kind == "sync_order"
    assert job.status == JobStatus.RUNNING
    assert job.leased_by == "worker-a"


def test_a_leased_job_is_not_handed_to_a_second_worker(db):
    enqueue(db, "sync_order", {"order_id": "1"})
    db.flush()
    assert lease_job(db, worker_id="worker-a") is not None
    assert lease_job(db, worker_id="worker-b") is None


def test_an_expired_lease_is_reclaimed(db):
    """A crashed worker must not strand its job forever."""
    enqueue(db, "sync_order", {"order_id": "1"})
    db.flush()
    job = lease_job(db, worker_id="worker-a", lease_seconds=60)
    job.leased_until = utcnow() - timedelta(seconds=1)
    db.flush()

    reclaimed = lease_job(db, worker_id="worker-b")
    assert reclaimed is not None
    assert reclaimed.id == job.id
    assert reclaimed.leased_by == "worker-b"


def test_completing_a_job_removes_it_from_the_queue(db):
    enqueue(db, "sync_order", {"order_id": "1"})
    db.flush()
    job = lease_job(db, worker_id="worker-a")
    complete_job(db, job)
    db.flush()
    assert job.status == JobStatus.SUCCEEDED
    assert job.finished_at is not None
    assert job.leased_by is None
    assert lease_job(db, worker_id="worker-b") is None


def test_a_failed_job_is_retried_with_backoff(db):
    enqueue(db, "sync_order", {"order_id": "1"})
    db.flush()
    job = lease_job(db, worker_id="worker-a")
    fail_job(db, job, "Shopify timed out")
    db.flush()

    assert job.status == JobStatus.PENDING
    assert job.attempts == 1
    assert job.last_error == "Shopify timed out"
    assert lease_job(db, worker_id="worker-b") is None


def test_backoff_lengthens_with_each_attempt(db):
    """Retrying a struggling service at the same rate makes it worse."""
    enqueue(db, "sync_order", {"order_id": "1"})
    db.flush()

    waits = []
    for _ in range(3):
        job = lease_job(db, worker_id="w")
        before = utcnow()
        fail_job(db, job, "boom")
        db.flush()
        waits.append((job.run_after - before).total_seconds())
        _make_runnable(db, job)

    assert waits[0] < waits[1] < waits[2]


def test_a_job_gives_up_after_the_attempt_limit_and_stays_visible(db):
    """A silently dropped job is worse than a visible failed one."""
    enqueue(db, "sync_order", {"order_id": "1"})
    db.flush()

    for attempt in range(MAX_ATTEMPTS):
        job = lease_job(db, worker_id="w")
        assert job is not None, f"job vanished before attempt {attempt + 1}"
        fail_job(db, job, f"attempt {attempt + 1}")
        db.flush()
        _make_runnable(db, job)

    assert job.status == JobStatus.FAILED
    assert job.attempts == MAX_ATTEMPTS
    assert job.last_error == f"attempt {MAX_ATTEMPTS}"
    assert lease_job(db, worker_id="w") is None


def test_a_failed_job_is_never_deleted(db):
    """It is the record that the work did not happen."""
    enqueue(db, "sync_order", {"order_id": "1"})
    db.flush()
    for _ in range(MAX_ATTEMPTS):
        job = lease_job(db, worker_id="w")
        fail_job(db, job, "boom")
        db.flush()
        _make_runnable(db, job)

    still_there = db.execute(
        text("SELECT count(*) FROM background_job WHERE status = 'failed'")
    ).scalar()
    assert still_there == 1


def test_a_huge_error_is_truncated_not_rejected(db):
    """The failure-recording path must not itself fail on a big traceback."""
    enqueue(db, "sync_order", {"order_id": "1"})
    db.flush()
    job = lease_job(db, worker_id="w")
    fail_job(db, job, "E" * (ERROR_LIMIT * 3))
    db.flush()
    assert len(job.last_error) == ERROR_LIMIT


def test_a_job_scheduled_for_later_is_not_leased_yet(db):
    enqueue(db, "sync_order", {"order_id": "1"}, run_after=utcnow() + timedelta(hours=1))
    db.flush()
    assert lease_job(db, worker_id="worker-a") is None


def test_jobs_are_leased_oldest_first(db):
    enqueue(db, "first", {})
    db.flush()
    enqueue(db, "second", {})
    db.flush()
    assert lease_job(db, worker_id="w").kind == "first"


def test_the_payload_survives_a_round_trip(db):
    enqueue(db, "sync_order", {"order_id": "5123456789", "reason": "webhook"})
    db.flush()
    job = lease_job(db, worker_id="w")
    assert job.payload["order_id"] == "5123456789"
    assert job.payload["reason"] == "webhook"


def test_an_unknown_status_is_refused_by_the_database(db):
    """The status column is a fixed vocabulary, not free text."""
    enqueue(db, "sync_order", {})
    db.flush()
    with pytest.raises(DatabaseError):
        db.execute(text("UPDATE background_job SET status = 'nearly'"))


# ── Deduplicating queued work ──────────────────────────────────────────────────


def test_the_same_order_is_not_queued_twice_while_pending(db):
    """Shopify sends create, then update, then paid, all within a second.

    Three jobs would fetch the same order three times for the same result.
    """
    enqueue(db, "sync_order", {"order_id": "1"}, dedupe_key="sync_order:1")
    db.flush()
    enqueue(db, "sync_order", {"order_id": "1"}, dedupe_key="sync_order:1")
    db.flush()

    queued = db.execute(
        text("SELECT count(*) FROM background_job WHERE kind = 'sync_order'")
    ).scalar()
    assert queued == 1


def test_the_same_order_can_be_queued_again_once_the_first_finished(db):
    """Deduplication must not swallow a genuinely later change."""
    enqueue(db, "sync_order", {"order_id": "1"}, dedupe_key="sync_order:1")
    db.flush()
    complete_job(db, lease_job(db, worker_id="w"))
    db.flush()

    enqueue(db, "sync_order", {"order_id": "1"}, dedupe_key="sync_order:1")
    db.flush()
    assert lease_job(db, worker_id="w") is not None


def test_jobs_without_a_dedupe_key_are_never_merged(db):
    enqueue(db, "reconcile", {})
    db.flush()
    enqueue(db, "reconcile", {})
    db.flush()
    queued = db.execute(
        text("SELECT count(*) FROM background_job WHERE kind = 'reconcile'")
    ).scalar()
    assert queued == 2


# ── Prevented failures are reported, not swallowed ─────────────────────────────


def test_giving_up_on_a_job_is_reported(db, caplog):
    """The single most important thing to notice: work that never happened."""
    enqueue(db, "sync_order", {"order_id": "77"})
    db.flush()

    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        for _ in range(MAX_ATTEMPTS):
            job = lease_job(db, worker_id="w")
            fail_job(db, job, "Shopify unreachable")
            db.flush()
            _make_runnable(db, job)

    assert Anomaly.JOB_GAVE_UP in caplog.text
    assert "sync_order" in caplog.text
    assert caplog.text.count(Anomaly.JOB_GAVE_UP) == 1, "reported once, not per attempt"


def test_a_retry_that_will_happen_again_is_not_reported_as_giving_up(db, caplog):
    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        enqueue(db, "sync_order", {"order_id": "78"})
        db.flush()
        fail_job(db, lease_job(db, worker_id="w"), "one blip")
        db.flush()

    assert Anomaly.JOB_GAVE_UP not in caplog.text


def test_truncating_an_error_is_reported(db, caplog):
    """The failure is still recorded; part of the detail is not. Say so."""
    enqueue(db, "sync_order", {"order_id": "79"})
    db.flush()
    job = lease_job(db, worker_id="w")

    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        fail_job(db, job, "E" * (ERROR_LIMIT + 1))
        db.flush()

    assert Anomaly.ERROR_TRUNCATED in caplog.text


def test_an_error_that_fits_is_not_reported(db, caplog):
    enqueue(db, "sync_order", {"order_id": "80"})
    db.flush()
    job = lease_job(db, worker_id="w")

    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        fail_job(db, job, "E" * ERROR_LIMIT)
        db.flush()

    assert Anomaly.ERROR_TRUNCATED not in caplog.text


def test_reclaiming_a_dead_worker_s_job_is_reported(db, caplog):
    """Normal once. Constant means workers are dying."""
    enqueue(db, "sync_order", {"order_id": "81"})
    db.flush()
    job = lease_job(db, worker_id="worker-a")
    job.leased_until = utcnow() - timedelta(seconds=1)
    db.flush()

    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        lease_job(db, worker_id="worker-b")
        db.flush()

    assert Anomaly.LEASE_RECLAIMED in caplog.text
    assert "worker-a" in caplog.text


def test_a_first_lease_is_not_reported_as_a_reclaim(db, caplog):
    enqueue(db, "sync_order", {"order_id": "82"})
    db.flush()
    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        lease_job(db, worker_id="worker-a")
        db.flush()
    assert Anomaly.LEASE_RECLAIMED not in caplog.text


def test_absorbing_duplicate_work_is_reported(db, caplog):
    enqueue(db, "sync_order", {"order_id": "83"}, dedupe_key="sync_order:83")
    db.flush()
    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        enqueue(db, "sync_order", {"order_id": "83"}, dedupe_key="sync_order:83")
        db.flush()
    assert Anomaly.WORK_DEDUPLICATED in caplog.text


def test_reporting_never_raises_on_an_awkward_value(db, caplog):
    """A reporting path that can fail is worse than no reporting path."""

    class Awkward:
        def __repr__(self):
            raise RuntimeError("no repr for you")

    from app.core.signals import report

    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        report("something", value=Awkward())

    assert "something" in caplog.text
