"""One read of one source, and what is recorded about it (ADR 0057 §6).

Each source is read every 5 minutes by a recurring job of its own. The worker
runs the next one 5 minutes after the last finished and looks for due work
every 60 seconds, so a clean read is never more than about 6 minutes old -
inside the 10 minutes ``freshness`` promises - and a stopped worker shows as
stale numbers rather than current ones.

``run_poll`` is what every source's job does:

- **No key**: ``not_connected`` is recorded and the job succeeds. Failing it
  would add a failed job to the operations panel every 5 minutes for a
  source nobody has connected yet.
- **The read fails**: the failure is recorded *in a transaction of its own*,
  then raised again so the job's normal retries and failed-job visibility
  apply. It has to be its own transaction because the worker rolls the
  job's session back on any failure, which would otherwise take the record
  of the failure with it - and the dashboard would go on showing the last
  numbers as current.
- **The read succeeds**: the rows and the clean read are written together,
  in the job's session, and the worker commits them as one.

The failure reason shown is a sentence written here or by a source's client
(``SourceUnavailable``). Anything else a read raises becomes "Couldn't read
<source>" - on the dashboard and in the job's own error alike - because an
exception's own text can carry a URL, a header or a response body.
"""

import logging
from datetime import timedelta
from typing import Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.shared.services.jobs import PermanentFailure
from app.modules.operations.services.freshness import (
    SOURCE_LABEL,
    record_failure,
    record_not_connected,
    record_success,
)

logger = logging.getLogger(__name__)

#: The gap after one read finishes before the next is due.
POLL_EVERY = timedelta(minutes=5)


class NotConnected(Exception):
    """There is no key for this source. Raise before reading anything."""


class SourceUnavailable(Exception):
    """A read that failed, with a reason fit to show the operations manager.

    The message must be plain words: no key, no URL, no response body.
    """


class PermanentlyUnavailable(SourceUnavailable, PermanentFailure):
    """A failed read that retrying cannot fix, so the job fails at once
    rather than spending its attempts."""


class KeyRefused(PermanentlyUnavailable):
    """The source refused the key."""


#: A read stores its rows in the session it is given and returns how many.
Poll = Callable[[Session], int]


def run_poll(
    db: Session,
    source: str,
    poll: Poll,
    *,
    failure_session: Callable[[], Session] = SessionLocal,
) -> int | None:
    """Read ``source`` once with ``poll``, recording how it went.

    Returns the number of rows stored, or None when the source has no key.
    Like any handler it never commits ``db``; only a failure is committed,
    through a session of its own.
    """
    try:
        # A savepoint: a read that fails part-way leaves none of its writes.
        with db.begin_nested():
            stored = poll(db)
    except NotConnected:
        record_not_connected(db, source)
        logger.info("order-ops %s: not connected", source)
        return None
    except SourceUnavailable as exc:
        # Expected - a source down, a key refused. The dashboard shows it, and
        # the job succeeds: failing it would add a failed job every few
        # minutes and push real failures off the failed-jobs list.
        reason = str(exc) or f"Couldn't read {SOURCE_LABEL[source]}."
        record_failure(db, source, reason)
        logger.warning("order-ops %s read failed: %s", source, reason)
        return None
    except Exception as exc:
        # Anything else is replaced, not re-raised: the worker writes a
        # failed job's message into ``background_job.last_error``, its log
        # and the failed-jobs panel, and this one may carry a URL or a key.
        # The type alone is logged, for diagnosis.
        logger.warning("order-ops %s read failed: %s", source, type(exc).__name__)
        reason = f"Couldn't read {SOURCE_LABEL[source]}."
        _record_failure_apart(failure_session, source, reason)
        replacement = (
            PermanentlyUnavailable if isinstance(exc, PermanentFailure) else SourceUnavailable
        )
        raise replacement(reason) from None

    record_success(db, source, stored)
    return stored


def _record_failure_apart(factory: Callable[[], Session], source: str, reason: str) -> None:
    """Commit the failure on its own. If even that cannot be written, the
    original failure still propagates; the numbers then age into stale."""
    try:
        with factory() as session:
            # Wait briefly, never for ever: were the job's own session ever to
            # hold this row, waiting would hang the worker on itself.
            session.execute(text("SET LOCAL lock_timeout = '2s'"))
            record_failure(session, source, reason)
            session.commit()
    except Exception as exc:  # noqa: BLE001 - must not replace the read's own failure
        logger.error("order-ops %s: could not record the failure: %s", source, type(exc).__name__)
