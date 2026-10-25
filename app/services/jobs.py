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


class JobKind:
    """Every job kind, named once.

    The producer and the handler live in different modules. Two string literals
    that must agree is exactly how a rename ships half-done - the receiver
    queues a kind nothing handles, every job fails with no_handler, and the
    endpoint keeps returning 200 as though nothing were wrong.
    """

    SYNC_ORDER = "shopify_sync_order"
    BULK_IMPORT = "shopify_bulk_import"
    RECONCILE = "shopify_reconcile"
    PRUNE_JOBS = "prune_succeeded_jobs"

    #: Attach the orders a code already had when it was registered (§9.2).
    #: Models arrive with codes already live and already selling, so without
    #: this everything earned before registration belongs to nobody.
    BACKFILL_CODE = "backfill_code"

    #: Walk the shop's products, variants and images (Phase 3, W01). Its own
    #: kind rather than a step inside the order sync, because a product field
    #: Shopify refuses must never be able to stop orders indexing.
    SYNC_CATALOGUE = "shopify_sync_catalogue"

    #: Work out which parcels went to which model (Phase 3, W03/W05). Carries
    #: its own cursor and re-enqueues itself: a whole history in one handler is
    #: a lease held for minutes and lost entirely if it dies at the end.
    SCAN_RECIPIENTS = "shopify_scan_recipients"

    #: Check one order against the model roster, for orders arriving live
    #: (W05: *backfill from January and perform live matching*). The bulk scan
    #: handles history; this handles the parcel that shipped this morning.
    MATCH_ORDER = "shopify_match_order"

    #: Read what was actually inside one matched parcel. **Only matched ones** -
    #: fetching every line of every order in the shop to build twenty wardrobes
    #: is the wrong trade, and the great majority of orders are customers.
    SYNC_LINE_ITEMS = "shopify_sync_line_items"

    #: Settings → Appearance's *Weekly reminder to record achieved content*:
    #: an email to staff who record targets and have not turned it off.
    TARGETS_REMINDER = "targets_weekly_reminder"

    #: Find registered codes that still have orders belonging to nobody, and
    #: queue their backfill again. The backfill is what attaches them; this is
    #: what notices when it did not finish (staging, 26 September: HBA10 stopped
    #: at 1,000 orders and every job said *succeeded*).
    ATTACH_ORPHANS = "attach_orphaned_orders"

    #: Queue the product read for attributed orders that have none, or whose
    #: lines were read before options were (ADR 0050). Hourly and bounded:
    #: staging had 6,943 attributed orders and not one line item, because only
    #: the webhook path ever asked (27 September).
    FILL_LINE_ITEMS = "fill_missing_line_items"

    #: Re-read every order still held as undelivered (ADR 0051). The sweep
    #: only re-reads what changed in two days, so an order stuck by a rule
    #: since corrected - 1,114 on staging, 28 September - was never read again.
    RESYNC_IN_FLIGHT = "resync_in_flight_orders"

    #: Operations' reads (ADR 0057), one kind per source so a source that
    #: fails holds up neither of the others. Each runs every 5 minutes
    #: (app.services.order_ops.polling) and is scheduled with its handler.
    ORDER_OPS_SHOPIFY = "order_ops_read_shopify"
    ORDER_OPS_BOSTA = "order_ops_read_bosta"
    ORDER_OPS_ESTEBDAL = "order_ops_read_estebdal"

    #: Decide whether one order gets a WhatsApp confirmation, and record it
    #: (ADR 0059). One per order, queued when the order is first indexed.
    INBOX_CONFIRM_ORDER = "inbox_confirm_order"
    #: Find recent orders with no confirmation on record and queue each. Runs
    #: after the reconciliation sweep, so an order whose webhook was missed is
    #: still considered.
    INBOX_CONFIRM_SWEEP = "inbox_confirm_sweep"
    #: Apply one stored callback from Meta: a customer's message, a button
    #: tap, or a delivery tick. The callback is written down first and
    #: answered at once; this is the work that follows.
    INBOX_APPLY_EVENT = "inbox_apply_event"
    #: Send one order's confirmation, if it is still waiting and this server
    #: may message that customer. Claimed before WhatsApp is asked, so sent
    #: at most once.
    INBOX_SEND_CONFIRMATION = "inbox_send_confirmation"
    #: The automatic reply to a tap on Edit or Cancel. One per tap.
    INBOX_AUTO_REPLY = "inbox_auto_reply"
    #: Write an order's one confirmation tag to Shopify, through the second
    #: Shopify app - the only thing the platform writes there.
    INBOX_TAG_ORDER = "inbox_tag_order"
    #: Copy a customer's photo, voice note or file from Meta into our own
    #: bucket. WhatsApp deletes it after 7 days.
    INBOX_FETCH_MEDIA = "inbox_fetch_media"
    #: An unpaid international order's one payment reminder (ADR 0062),
    #: claimed before WhatsApp is asked.
    INBOX_PAYMENT_REMINDER = "inbox_payment_reminder"
    #: Ask Shopify to email an unpaid international order's invoice, once,
    #: through the second Shopify app (ADR 0062).
    INBOX_SEND_INVOICE = "inbox_send_invoice"
    #: Read a recent order's confirmation tags back from Shopify, and take an
    #: answer the team tagged there (ADR 0063). Reads only.
    INBOX_READ_TAGS = "inbox_read_tags"


#: The inbox's work (ADR 0059) runs in a lane of its own too: a WhatsApp outage
#: must never delay order sync or anything that decides pay, and a backlog of
#: line-item reads must never delay a customer's confirmation.
INBOX_WORK = frozenset(
    {
        JobKind.INBOX_CONFIRM_ORDER,
        JobKind.INBOX_CONFIRM_SWEEP,
        JobKind.INBOX_APPLY_EVENT,
        JobKind.INBOX_SEND_CONFIRMATION,
        JobKind.INBOX_AUTO_REPLY,
        JobKind.INBOX_TAG_ORDER,
        JobKind.INBOX_FETCH_MEDIA,
        JobKind.INBOX_PAYMENT_REMINDER,
        JobKind.INBOX_SEND_INVOICE,
        JobKind.INBOX_READ_TAGS,
    }
)

#: Operations' reads run in a lane of their own (app.worker): the dashboard
#: promises no number older than 10 minutes, and in the shared queue a read
#: waited behind the hourly batch of 500 line-item reads - 4.5 minutes late
#: on staging, 6 October 2026. They are short, and nothing else waits on them.
OPERATIONS_READS = frozenset(
    {JobKind.ORDER_OPS_SHOPIFY, JobKind.ORDER_OPS_BOSTA, JobKind.ORDER_OPS_ESTEBDAL}
)


class PermanentFailure(Exception):
    """A job failure that retrying cannot fix.

    Raised by a handler when the cause is not going to resolve itself: a
    missing credential, an ungranted scope, a payload that names nothing. The
    worker fails the job at once rather than spending the remaining attempts,
    because four more identical failures over eight minutes buy nothing and
    bury the one line that explains the problem.

    Anything else a handler raises is treated as temporary and retried.
    """


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
    *,
    only: frozenset[str] | None = None,
    exclude: frozenset[str] | None = None,
) -> BackgroundJob | None:
    """Claim the oldest runnable job, or return None if there is none.

    ``only`` and ``exclude`` limit which kinds this caller takes, so a lane of
    the worker can keep to its own work (``OPERATIONS_READS``).

    Runnable means pending and due, or running with an expired lease - the
    second case being a worker that died holding a job.

    ``SKIP LOCKED`` is the whole trick: a row another transaction has already
    locked is passed over rather than waited on, so concurrent workers never
    contend and never collide.
    """
    now = utcnow()
    runnable = select(BackgroundJob.id).where(
        or_(
            (BackgroundJob.status == JobStatus.PENDING)
            & (BackgroundJob.run_after <= now),
            (BackgroundJob.status == JobStatus.RUNNING)
            & (BackgroundJob.leased_until < now),
        )
    )
    if only is not None:
        runnable = runnable.where(BackgroundJob.kind.in_(only))
    if exclude:
        runnable = runnable.where(BackgroundJob.kind.not_in(exclude))
    candidate = db.execute(
        runnable
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
        # Kind, id and attempts only. The payload and the error text can name
        # a customer (a phone, an address, a provider's reply quoting an
        # email), and a log line is copied wherever the logs go; signals.py
        # asks that no customer detail is ever passed. The error stays on the
        # job's own row, for whoever opens it.
        report(
            Anomaly.JOB_GAVE_UP,
            job_id=job.id,
            kind=job.kind,
            attempts=job.attempts,
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
    (docs/limits.md). The newest success of each kind is kept too.
    """
    deleted = db.execute(
        text(
            "DELETE FROM background_job "
            "WHERE status = 'succeeded' "
            "  AND finished_at < now() - make_interval(days => :days) "
            # The newest success of each kind stays, however old: it is what
            # *last successful refresh* reads, and a month of failures must
            # not turn that into *never*.
            "  AND id NOT IN (SELECT DISTINCT ON (kind) id FROM background_job "
            "                 WHERE status = 'succeeded' "
            "                 ORDER BY kind, finished_at DESC, id DESC)"
        ),
        {"days": older_than_days},
    )
    return deleted.rowcount
