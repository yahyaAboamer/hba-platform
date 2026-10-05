"""How fresh each source's numbers are (ADR 0057 §6).

Every number on Operations is at most 10 minutes old, and always shown with
the time it was read. The reads themselves run every 5 minutes in the worker
(``polling``); this records how each one went and turns that into one of five
states the dashboard draws differently:

- **fresh**: read cleanly within the last 10 minutes.
- **stale**: the last clean read is older than that, so the worker may have
  stopped. The numbers show with their age, in amber.
- **failed**: the latest read failed. The last good numbers, if any, show
  greyed with their time - never a 0.
- **not_connected**: there is no key to read with.
- **never**: nothing has been read yet ("Reading Shopify…").
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.models.order_ops import OpsSourceStatus

SOURCES = ("shopify", "bosta", "estebdal")

#: How each source is named to a person.
SOURCE_LABEL = {"shopify": "Shopify", "bosta": "Bosta", "estebdal": "E-stebdal"}

#: The promise: no number older than this is shown as current.
FRESH_FOR = timedelta(minutes=10)

#: A failure reason is a sentence, not a traceback.
ERROR_LIMIT = 500


class State:
    FRESH = "fresh"
    STALE = "stale"
    FAILED = "failed"
    NOT_CONNECTED = "not_connected"
    NEVER = "never"


def _require_source(source: str) -> str:
    if source not in SOURCES:
        raise ValueError(f"Unknown operations source: {source!r}")
    return source


def _write(db: Session, source: str, **values) -> None:
    """Insert the source's row or rewrite the given columns of it."""
    statement = insert(OpsSourceStatus).values(source=_require_source(source), **values)
    db.execute(
        statement.on_conflict_do_update(index_elements=[OpsSourceStatus.source], set_=values)
    )


def record_success(db: Session, source: str, row_count: int, at: datetime | None = None) -> None:
    """A clean read, storing ``row_count`` rows. Clears any failure."""
    at = at or utcnow()
    _write(
        db,
        source,
        connected=True,
        last_attempt_at=at,
        last_success_at=at,
        last_error=None,
        row_count=row_count,
    )


def record_failure(db: Session, source: str, message: str, at: datetime | None = None) -> None:
    """A read that failed. The last clean read's time and count are kept."""
    _write(
        db,
        source,
        connected=True,
        last_attempt_at=at or utcnow(),
        last_error=(message or "The read failed.")[:ERROR_LIMIT],
    )


def record_not_connected(db: Session, source: str, at: datetime | None = None) -> None:
    """There was no key to read with: not a failure, and not a 0."""
    _write(db, source, connected=False, last_attempt_at=at or utcnow(), last_error=None)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def describe(db: Session, source: str, now: datetime | None = None) -> dict:
    """The source's state, as every Operations response carries it."""
    # Read afresh: the records above are upserts the session's identity map
    # never sees, so a row it already holds could be out of date.
    row = db.scalars(
        select(OpsSourceStatus)
        .where(OpsSourceStatus.source == _require_source(source))
        .execution_options(populate_existing=True)
    ).one_or_none()
    now = now or utcnow()

    if row is None:
        state = State.NEVER
    elif not row.connected:
        state = State.NOT_CONNECTED
    elif row.last_error is not None:
        state = State.FAILED
    elif row.last_success_at is None:
        state = State.NEVER
    elif now - row.last_success_at > FRESH_FOR:
        state = State.STALE
    else:
        state = State.FRESH

    return {
        "source": source,
        "label": SOURCE_LABEL[source],
        "state": state,
        # The time the numbers were read - what "Updated N minutes ago" counts.
        "updated_at": _iso(row.last_success_at) if row else None,
        "checked_at": _iso(row.last_attempt_at) if row else None,
        "error": row.last_error if state == State.FAILED else None,
        "row_count": row.row_count if row else None,
    }
