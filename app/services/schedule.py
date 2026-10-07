"""Recurring work.

Some jobs have to happen on their own: the reconciliation sweep that makes
order data complete rather than merely prompt, and the prune that stops
``background_job`` growing forever. Nothing triggers those, so without this
they simply never run - and *never running* is silent. The dashboard would look
fine while orders quietly went missing.

**There is no cron table, and no scheduler process.** The worker calls
``ensure_scheduled`` periodically; it queues a recurring job only when none is
already outstanding, and when one finishes the next call queues another due an
interval later.

It asks before enqueuing rather than letting the dedupe key absorb a duplicate.
Both are correct, and the absorbed path reports ``work_deduplicated`` every
time - which, called on a timer forever, would bury the log in a signal that
means nothing here. The dedupe key stays as the guarantee against a race; the
check is what keeps it quiet.

That gives *roughly* every interval, not exactly. Nothing here needs exactly:
a sweep that runs 31 minutes after the last one instead of 30 is not a defect,
and buying precision would mean a schedule table, a clock, and a new set of
ways to fail.
"""

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.models.integration import BackgroundJob
from app.services.jobs import JobKind, JobStatus, enqueue
from app.services.order_ops.polling import POLL_EVERY

logger = logging.getLogger(__name__)


#: kind -> (interval, payload). The interval is the *gap after finishing*, not
#: a fixed clock slot.
SCHEDULE: dict[str, tuple[timedelta, dict]] = {
    JobKind.RECONCILE: (timedelta(minutes=30), {"since_hours": 48}),
    JobKind.PRUNE_JOBS: (timedelta(days=1), {"older_than_days": 30}),
    # Settings → Appearance. Roughly weekly; who receives it is decided when
    # it runs (app.services.staff_prefs).
    JobKind.TARGETS_REMINDER: (timedelta(days=7), {}),
    # A query and, usually, nothing more (app.services.commission.backfill).
    # Hourly so a code whose backfill stopped is whole again the same hour.
    JobKind.ATTACH_ORPHANS: (timedelta(hours=1), {}),
    # A query and a bounded batch of reads (app.services.recipients).
    JobKind.FILL_LINE_ITEMS: (timedelta(hours=1), {}),
    # Re-read what is still undelivered (app.services.reconcile, ADR 0051).
    # Every six hours: a stuck order is days old, not minutes.
    JobKind.RESYNC_IN_FLIGHT: (timedelta(hours=6), {}),
    # Operations' reads (ADR 0057): every 5 minutes, so no number on the
    # dashboard is more than 10 minutes old (app.services.order_ops.polling).
    JobKind.ORDER_OPS_SHOPIFY: (POLL_EVERY, {}),
    JobKind.ORDER_OPS_ESTEBDAL: (POLL_EVERY, {}),
    JobKind.ORDER_OPS_BOSTA: (POLL_EVERY, {}),
}


def ensure_scheduled(
    db: Session,
    *,
    only: frozenset[str] | None = None,
    exclude: frozenset[str] | None = None,
) -> int:
    """Queue any recurring job that is not already outstanding.

    Returns how many were queued. Safe to call as often as you like - that is
    the point - and it commits nothing, leaving the transaction to the caller.

    ``only`` / ``exclude`` let each worker lane top up its own kinds, so one
    lane busy for an hour never leaves the other's work unqueued.
    """
    queued = 0
    now = utcnow()
    kinds = {
        kind: entry
        for kind, entry in SCHEDULE.items()
        if (only is None or kind in only) and not (exclude and kind in exclude)
    }

    outstanding = set(
        db.scalars(
            select(BackgroundJob.kind).where(
                BackgroundJob.kind.in_(kinds),
                BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
            )
        )
    )

    for kind, (interval, payload) in kinds.items():
        if kind in outstanding:
            continue
        # Due one interval from now rather than immediately: a restart must not
        # trigger a sweep, or a crash-loop would become a sweep storm.
        job = enqueue(
            db,
            kind,
            dict(payload),
            run_after=now + interval,
            dedupe_key=kind,
        )
        if job is not None:
            queued += 1
            logger.info("scheduled %s to run in %s", kind, interval)

    return queued
