"""*Refresh now* and *last successful refresh* (Settings → Shopify).

The export's card (`syncState`, `lastSync`, `refreshSync`) says whether the
shop is connected, when orders were last refreshed, and offers a refresh.

**A refresh is the reconciliation sweep, run now.** Not a new kind of work:
`JobKind.RECONCILE` already re-reads every order Shopify changed in the last
48 hours and re-indexes it, and runs by itself every half hour. *Refresh now*
brings the next sweep forward. Reading is all it does - nothing is written to
Shopify, by this or by the sweep.

Three things this module is careful about:

* **Accepting a request is not a refresh.** Asking puts the sweep in the queue;
  only a sweep that *finished* moves *last successful refresh*, read from the
  job's own ``finished_at``. A queued or running one is shown as such.
* **A failure keeps the last success.** The timestamp is the newest
  *succeeded* sweep, so a failed one cannot move or clear it; the failure is
  reported beside it.
* **A second click starts nothing new.** At most one sweep is ever outstanding
  (the job's dedupe key); a request while one is queued brings that one
  forward, and while one is running joins it.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.models.integration import BackgroundJob
from app.services.jobs import JobKind, JobStatus, enqueue
from app.services.schedule import SCHEDULE

KIND = JobKind.RECONCILE

#: The scheduled sweep's own window, so a manual refresh reads exactly what the
#: half-hourly one does.
PAYLOAD = SCHEDULE[KIND][1]

OUTSTANDING = (JobStatus.PENDING, JobStatus.RUNNING)


class NotConnected(Exception):
    """There is no Shopify connection to refresh from."""


@dataclass(frozen=True)
class Requested:
    job_id: int
    #: ``queued`` - a sweep is now due; ``running`` - one was already reading,
    #: and this request joined it rather than starting a second.
    state: str


def _outstanding(db: Session, *, lock: bool = False) -> BackgroundJob | None:
    query = select(BackgroundJob).where(
        BackgroundJob.kind == KIND, BackgroundJob.status.in_(OUTSTANDING)
    )
    if lock:
        query = query.with_for_update()
    return db.scalars(query.order_by(BackgroundJob.id.desc()).limit(1)).first()


def request_refresh(db: Session) -> Requested:
    """Bring the next sweep forward, or join the one already running.

    Leaves the transaction to the caller. Raises ``NotConnected`` when there is
    no connection, so nothing is queued that could only fail.
    """
    from app.services.shopify.connection import effective

    if effective(db).source is None:
        raise NotConnected()

    now = utcnow()
    job = _outstanding(db, lock=True)
    if job is None:
        job = enqueue(db, KIND, dict(PAYLOAD), run_after=now, dedupe_key=KIND)
        if job is None:
            # Another request inserted one between our read and our insert;
            # the dedupe index kept it to one. Use that one.
            job = _outstanding(db, lock=True)
    if job is None:  # pragma: no cover - the index guarantees one exists
        raise RuntimeError("no outstanding sweep after enqueue")

    lease_valid = job.leased_until is not None and job.leased_until > now
    if job.status == JobStatus.RUNNING and lease_valid:
        return Requested(job.id, "running")

    if job.status == JobStatus.PENDING and job.run_after > now:
        db.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == job.id)
            .values(run_after=now)
        )
    return Requested(job.id, "queued")


def _failure_line(error: str | None) -> str:
    """The failure in words safe to show.

    ``last_error`` is ``"{ExceptionType}: {message}"`` from the worker. The
    Shopify client never puts a secret in a message, and only the recognised
    cases are shown in our own words; anything else says what kind of failure
    it was, not the raw text.
    """
    text = error or ""
    if "429" in text or "throttled" in text.lower():
        cause = "Shopify limited how fast orders could be read (429)."
    elif "rejected the credentials" in text or "token exchange failed" in text:
        cause = "Shopify refused the saved connection's credentials."
    elif "denied access" in text or "ShopifyMissingScope" in text:
        cause = "Shopify refused access to orders for this connection."
    elif "ShopifyNotConfigured" in text or "not configured" in text.lower():
        cause = "There was no Shopify connection to read from."
    elif "Shopify returned 5" in text:
        cause = "Shopify had a server error while orders were being read."
    elif "timed out" in text or "request failed:" in text:
        cause = "Shopify could not be reached."
    else:
        cause = "Reading orders from Shopify failed."
    return (
        f"{cause} Nothing from this attempt was saved; the next refresh reads "
        "the same orders again."
    )


def refresh_state(db: Session) -> dict:
    """What the card shows. Every time is the job's own, in UTC ISO form.

    ``state`` is one of:

    * ``not_connected`` - no connection, nothing can refresh
    * ``never`` - connected, and no sweep has finished yet
    * ``queued`` - a sweep is due and waiting for the worker
    * ``running`` - a sweep is reading now
    * ``failed`` - the latest attempt failed (a retry may be scheduled)
    * ``succeeded`` - the latest sweep finished
    """
    from app.services.shopify.connection import effective

    now = utcnow()
    last_success = db.scalars(
        select(BackgroundJob.finished_at)
        .where(BackgroundJob.kind == KIND, BackgroundJob.status == JobStatus.SUCCEEDED)
        .order_by(BackgroundJob.finished_at.desc())
        .limit(1)
    ).first()
    last_finished = db.scalars(
        select(BackgroundJob)
        .where(
            BackgroundJob.kind == KIND,
            BackgroundJob.status.in_([JobStatus.SUCCEEDED, JobStatus.FAILED]),
        )
        .order_by(BackgroundJob.finished_at.desc(), BackgroundJob.id.desc())
        .limit(1)
    ).first()
    outstanding = _outstanding(db)

    error: str | None = None
    failed_at = None
    if effective(db).source is None:
        state = "not_connected"
    elif outstanding is not None and outstanding.status == JobStatus.RUNNING and (
        outstanding.leased_until is not None and outstanding.leased_until > now
    ):
        state = "running"
    elif outstanding is not None and outstanding.run_after <= now:
        # Due: asked for, or a retry whose wait is over. The worker takes it
        # within seconds (or a dead worker's lease has expired).
        state = "queued"
    elif outstanding is not None and outstanding.last_error:
        # An attempt failed and a retry is waiting its turn.
        state, error = "failed", outstanding.last_error
    elif last_finished is not None and last_finished.status == JobStatus.FAILED:
        state, error = "failed", last_finished.last_error
        failed_at = last_finished.finished_at
    elif last_success is not None:
        state = "succeeded"
    else:
        state = "never"

    return {
        "state": state,
        "last_success_at": last_success.isoformat() if last_success else None,
        "failed_at": failed_at.isoformat() if failed_at else None,
        "error_line": _failure_line(error) if state == "failed" else None,
    }
