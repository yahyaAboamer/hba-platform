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

logger = logging.getLogger(__name__)


#: kind -> (interval, payload). The interval is the *gap after finishing*, not
#: a fixed clock slot.
SCHEDULE: dict[str, tuple[timedelta, dict]] = {
    JobKind.RECONCILE: (timedelta(minutes=30), {"since_hours": 48}),
    JobKind.PRUNE_JOBS: (timedelta(days=1), {"older_than_days": 30}),
}


def ensure_scheduled(db: Session) -> int:
    """Queue any recurring job that is not already outstanding.

    Returns how many were queued. Safe to call as often as you like - that is
    the point - and it commits nothing, leaving the transaction to the caller.
    """
    queued = 0
    now = utcnow()

    outstanding = set(
        db.scalars(
            select(BackgroundJob.kind).where(
                BackgroundJob.kind.in_(SCHEDULE),
                BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
            )
        )
    )

    for kind, (interval, payload) in SCHEDULE.items():
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
