"""The job queue, backed by Postgres.

Leasing uses ``SELECT ... FOR UPDATE SKIP LOCKED``, which is what makes this
safe without a queue server: two workers asking at the same moment get
different rows rather than the same one.

A job that exhausts its attempts is marked failed and left in place. It is not
deleted and not retried forever - a silently dropped job is worse than a
visible failed one, because nobody learns that the work never happened.
"""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.core.signals import Anomaly, report
from app.models.integration import BackgroundJob, IntegrationEvent

#: Five attempts over roughly eight minutes. Long enough to ride out a Shopify
#: blip, short enough that a genuine failure is visible while it still matters.
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 30
LEASE_SECONDS = 60

#: A traceback can be enormous. Recording the failure must never itself fail,
#: so the message is truncated rather than the write rejected (docs/limits.md).
ERROR_LIMIT = 2000


class JobStatus:
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    TERMINAL = frozenset({SUCCEEDED, FAILED})


# ── Event receipts ─────────────────────────────────────────────────────────────


def payload_digest(payload: dict[str, Any] | None) -> str | None:
    """SHA-256 of a payload, or None if there was no body.

    Keys are sorted so that two encodings of the same body produce the same
    digest - otherwise a redelivery would look like a change every time.
    """
    if payload is None:
        return None
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_event(
    db: Session,
    source: str,
    external_id: str,
    topic: str,
    payload: dict[str, Any] | None = None,
    entity_id: str | None = None,
) -> tuple[IntegrationEvent, bool]:
    """Record an inbound event. Returns ``(event, newly_recorded)``.

    A repeated delivery returns the original receipt and ``False``, so the
    caller can skip processing rather than doing it twice.

    The payload is digested, not stored (ADR 0020). Callers that need the
    contents must use them now; the receipt will not hold them afterwards.
    """
    statement = (
        insert(IntegrationEvent)
        .values(
            source=source,
            external_id=external_id,
            topic=topic,
            entity_id=entity_id,
            payload_digest=payload_digest(payload),
        )
        .on_conflict_do_nothing(constraint="integration_event_identity")
        .returning(IntegrationEvent.id)
    )
    digest = payload_digest(payload)
    inserted_id = db.execute(statement).scalar()
    if inserted_id is not None:
        return db.get(IntegrationEvent, inserted_id), True

    existing = db.scalar(
        select(IntegrationEvent).where(
            IntegrationEvent.source == source,
            IntegrationEvent.external_id == external_id,
        )
    )
    if existing is not None and existing.payload_digest != digest:
        # Deduplication is still correct - the first delivery wins. But the
        # same id carrying different content means an assumption about the
        # sender is wrong, and that must not pass in silence.
        report(
            Anomaly.EVENT_CONTENT_CHANGED,
            source=source,
            external_id=external_id,
            topic=topic,
            first_digest=existing.payload_digest,
            this_digest=digest,
        )
    return existing, False


# ── Queue ──────────────────────────────────────────────────────────────────────


def enqueue(
    db: Session,
    kind: str,
    payload: dict[str, Any],
    run_after: datetime | None = None,
    dedupe_key: str | None = None,
) -> BackgroundJob | None:
    """Queue a unit of work.

    With a ``dedupe_key``, a job already pending or running under that key
    absorbs this one and ``None`` is returned. The key becomes free again once
    that job finishes, so a genuinely later change is never swallowed.
    """
    values = {
        "kind": kind,
        "payload": payload,
        "dedupe_key": dedupe_key,
        "run_after": run_after or utcnow(),
        "status": JobStatus.PENDING,
    }

    if dedupe_key is None:
        job = BackgroundJob(**values)
        db.add(job)
        return job

    inserted_id = db.execute(
        insert(BackgroundJob)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=["dedupe_key"],
            # Must mirror the partial index exactly, or Postgres cannot
            # infer which index this conflict refers to.
            index_where=text("status IN ('pending', 'running')"),
        )
        .returning(BackgroundJob.id)
    ).scalar()
    if inserted_id is None:
        report(Anomaly.WORK_DEDUPLICATED, kind=kind, dedupe_key=dedupe_key)
        return None
    return db.get(BackgroundJob, inserted_id)


def lease_job(
    db: Session,
    worker_id: str,
    lease_seconds: int = LEASE_SECONDS,
) -> BackgroundJob | None:
    """Claim the oldest runnable job, or return None if there is none.

    Runnable means pending and due, or running with an expired lease - the
    second case being a worker that died holding a job.

    ``SKIP LOCKED`` is the whole trick: a row another transaction has already
    locked is passed over rather than waited on, so concurrent workers never
    contend and never collide.
    """
    now = utcnow()
    candidate = db.execute(
        select(BackgroundJob.id)
        .where(
            or_(
                (BackgroundJob.status == JobStatus.PENDING)
                & (BackgroundJob.run_after <= now),
                (BackgroundJob.status == JobStatus.RUNNING)
                & (BackgroundJob.leased_until < now),
            )
        )
        .order_by(BackgroundJob.run_after, BackgroundJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar()

    if candidate is None:
        return None

    reclaimed_from = db.get(BackgroundJob, candidate)
    if reclaimed_from is not None and reclaimed_from.status == JobStatus.RUNNING:
        report(
            Anomaly.LEASE_RECLAIMED,
            job_id=candidate,
            kind=reclaimed_from.kind,
            lost_by=reclaimed_from.leased_by,
            attempts=reclaimed_from.attempts,
        )

    db.execute(
        update(BackgroundJob)
        .where(BackgroundJob.id == candidate)
        .values(
            status=JobStatus.RUNNING,
            leased_by=worker_id,
            leased_until=now + timedelta(seconds=lease_seconds),
        )
    )
    job = db.get(BackgroundJob, candidate)
    db.refresh(job)
    return job


def complete_job(db: Session, job: BackgroundJob) -> None:
    """Mark work done. The lease is released so the row reads cleanly."""
    job.status = JobStatus.SUCCEEDED
    job.finished_at = utcnow()
    job.leased_by = None
    job.leased_until = None
    job.last_error = None


def fail_job(
    db: Session, job: BackgroundJob, error: str, *, give_up: bool = False
) -> None:
    """Record a failed attempt, and either back off or give up.

    Backoff doubles each time: 30s, 60s, 120s, 240s. Retrying a struggling
    service at a fixed interval is how a blip becomes an outage.

    ``give_up`` fails the job now, without spending the remaining attempts. For
    a failure that cannot succeed on a retry - a job kind with no handler, say -
    retrying only delays the signal.
    """
    message = error or ""
    if len(message) > ERROR_LIMIT:
        report(
            Anomaly.ERROR_TRUNCATED,
            job_id=job.id,
            kind=job.kind,
            original_length=len(message),
            kept=ERROR_LIMIT,
        )

    job.attempts = MAX_ATTEMPTS if give_up else job.attempts + 1
    job.last_error = message[:ERROR_LIMIT]
    job.leased_by = None
    job.leased_until = None

    if job.attempts >= MAX_ATTEMPTS:
        job.status = JobStatus.FAILED
        job.finished_at = utcnow()
        report(
            Anomaly.JOB_GAVE_UP,
            job_id=job.id,
            kind=job.kind,
            attempts=job.attempts,
            payload=job.payload,
            last_error=job.last_error[:200],
        )
        return

    job.status = JobStatus.PENDING
    job.run_after = utcnow() + timedelta(
        seconds=BACKOFF_BASE_SECONDS * (2 ** (job.attempts - 1))
    )


def prune_succeeded_jobs(db: Session, older_than_days: int = 30) -> int:
    """Delete old succeeded jobs, returning how many went.

    Only succeeded ones. A failed job is the record that work did not happen,
    and deleting it on a timer would erase exactly the evidence someone needs
    (docs/limits.md).
    """
    deleted = db.execute(
        text(
            "DELETE FROM background_job "
            "WHERE status = 'succeeded' "
            "  AND finished_at < now() - make_interval(days => :days)"
        ),
        {"days": older_than_days},
    )
    return deleted.rowcount
