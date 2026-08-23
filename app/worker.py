"""The background worker.

It runs inside the API process. With a single replica that is simpler and
cheaper than operating a second service, and because jobs are leased rather
than assigned, splitting it out later needs no change to the queue.

**Three transactions per job, not one.** The lease is committed before the
handler runs, then the handler runs in its own transaction, then the outcome is
committed. That matters for two reasons:

- A handler that takes a minute would otherwise hold a row lock — and an open
  Postgres transaction — for that whole minute, which blocks vacuuming and ties
  up a connection from a small pool.
- The lease only means anything once it is visible to other transactions. Until
  it is committed, a crashed worker's job is protected by a row lock that dies
  with it, and ``leased_until`` never comes into play.

A handler that raises has its transaction rolled back, so no half-finished work
is committed. The failure is then recorded in a *fresh* transaction — otherwise
the rollback that discards the work would also discard the fact that it was
attempted, and the job would retry forever with ``attempts`` stuck at zero.
"""

import asyncio
import logging
import os
import socket
from typing import Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.core.signals import Anomaly, report
from app.db import SessionLocal
from app.models.integration import BackgroundJob
from app.services.jobs import complete_job, fail_job, lease_job

logger = logging.getLogger(__name__)

Handler = Callable[[Session, dict], None]

#: Job kind -> the function that performs it. Populated by @register_handler at
#: import time, so a handler's module must be imported for its kind to be
#: runnable - see app.main.
HANDLERS: dict[str, Handler] = {}


def register_handler(kind: str):
    """Attach a handler to a job kind.

    Refuses a duplicate registration. Two handlers for one kind means one of
    them silently never runs, which is the kind of bug that hides for months.

    **The contract for a handler:**

    - Write through the session it is given; the worker commits it on success.
    - **Never commit or roll back that session.** Committing part-way defeats
      the rollback that discards a failed job's work, leaving half its effects
      behind.
    - Raise to fail. The exception's type and message become ``last_error``, so
      make it say something a person can act on.
    - Be idempotent. A lease can expire and hand the same job to another
      worker, so running twice must be indistinguishable from running once.
    """

    def decorator(function: Handler) -> Handler:
        if kind in HANDLERS:
            raise ValueError(f"A handler is already registered for {kind!r}")
        HANDLERS[kind] = function
        return function

    return decorator


def worker_identity() -> str:
    """Who holds a lease. Recorded so a stuck job names the process."""
    return f"{socket.gethostname()}:{os.getpid()}"


def _record_failure(db: Session, job_id: int, message: str, *, give_up: bool) -> None:
    """Record an outcome in a transaction of its own.

    Called after a rollback, so it must re-fetch the job: the instance the
    caller was holding was expired by that rollback.
    """
    job = db.get(BackgroundJob, job_id)
    if job is None:  # pragma: no cover - only if something deleted it mid-flight
        return
    fail_job(db, job, message, give_up=give_up)
    db.commit()


def run_one(db: Session, worker_id: str) -> bool:
    """Process at most one job. Returns whether there was one.

    Commits. The caller must not be inside a transaction it intends to roll
    back.
    """
    job = lease_job(db, worker_id)
    if job is None:
        return False

    job_id, kind, payload = job.id, job.kind, dict(job.payload or {})
    # Make the lease durable before doing any work, so the row lock is released
    # and leased_until becomes the thing that protects the job.
    db.commit()

    handler = HANDLERS.get(kind)
    if handler is None:
        # A deployed job kind with no handler is a mismatch between what is
        # queued and what is running - usually a half-finished deploy. Retrying
        # will never fix it, so fail now and say so loudly.
        report(Anomaly.NO_HANDLER, job_id=job_id, kind=kind)
        _record_failure(
            db, job_id, f"No handler registered for job kind {kind!r}", give_up=True
        )
        return True

    try:
        handler(db, payload)
    except Exception as exc:  # noqa: BLE001 - any failure must be recorded, not raised
        db.rollback()
        message = f"{type(exc).__name__}: {exc}"
        logger.warning("job %s (%s) failed: %s", job_id, kind, message)
        _record_failure(db, job_id, message, give_up=False)
        return True

    complete_job(db, db.get(BackgroundJob, job_id))
    db.commit()
    return True


async def worker_loop() -> None:
    """Poll for work until cancelled.

    Sleeps only when idle, so a backlog drains at full speed rather than one
    job per poll interval.
    """
    worker_id = worker_identity()
    logger.info("background worker %s started", worker_id)
    while True:
        did_work = False
        try:
            with SessionLocal() as db:
                did_work = run_one(db, worker_id)
        except asyncio.CancelledError:
            logger.info("background worker %s stopping", worker_id)
            raise
        except Exception:  # noqa: BLE001 - the loop must outlive any single error
            # A failure here is not a job failing - that is handled inside
            # run_one. This is the queue itself being unreachable, so back off
            # rather than spinning against a database that is down.
            logger.exception("worker iteration failed")
            report(Anomaly.WORKER_ITERATION_FAILED, worker_id=worker_id)

        if not did_work:
            await asyncio.sleep(settings.worker_poll_seconds)
