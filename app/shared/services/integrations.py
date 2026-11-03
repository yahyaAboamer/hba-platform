"""Settings → Integrations: whether each outside connection works (Batch 2.3).

The owner's one page for the platform's six connections - Bosta, Shopify,
WhatsApp, E-stebdal, email and file storage - in the order the approved frame
draws them, broken or not.

**Built only from what the platform already records.** Each department notes
how its own reads and sends went (Operations its freshness, the Inbox its
messages and files, the outbox its emails); this reads those notes and asks
no outside service anything, so opening the page can never itself fail a
connection or spend a provider's quota.

**Departments are reached only through their ``public``** (the import check
in ``pyproject.toml``), as Today's are.

A source that cannot be read leaves its own row as ``unknown`` - logged, never
a guess - and the other rows stay.
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.inbox import public as inbox
from app.modules.operations import public as operations
from app.shared.models.notifications import NotificationOutbox, NotificationState

logger = logging.getLogger(__name__)


class State:
    """A row's state, which the page draws as its pill."""

    WORKING = "working"
    LATE = "late"
    FAILED = "failed"
    NOT_CONNECTED = "not_connected"
    NEVER = "never"
    UNKNOWN = "unknown"


#: Operations' freshness, in this page's words (contract §3).
_FROM_FRESHNESS = {
    "fresh": State.WORKING,
    "stale": State.LATE,
    "failed": State.FAILED,
    "not_connected": State.NOT_CONNECTED,
    "never": State.NEVER,
}

NO_KEY = "No key is saved."
LATE_WHY = "Not read cleanly for over 10 minutes. The reads may have stopped."
NO_MAIL = "No mail service is set on the server, so no email is sent."
NO_BUCKET = "No file storage is set on the server, so customers' files are not kept."
FILE_FAILED = "The latest file could not be kept."

#: A Python exception's name in front of a message ("RuntimeError: ...")
#: says nothing to the owner and is dropped.
_EXCEPTION_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*: ")

#: The outbox errors that say **the mail service itself** is not working, as
#: ``notifications.send_notification`` and ``mail`` write them. The outbox keeps no kind
#: of failure, only its words, so this reads the words those two modules
#: write: the mail account refused (SMTP sign-in), the provider refusing the
#: key (401/403), the provider unreachable or failing (5xx), and the SMTP
#: connection failing after every retry. Anything else - no address, an
#: expired code, one recipient or message refused (other 4xx, an SMTP
#: recipient or sender refusal, a data error) - is that email's own.
#:
#: A Postgres regular expression, matched in the query - so no word
#: boundaries: Postgres writes those differently from Python.
TRANSPORT_FAILURE = (
    r"^The mail account was refused"
    r"|^(resend|brevo) refused the message \((401|403)\)"
    r"|Could not reach (resend|brevo)"
    r"|(resend|brevo) returned 5[0-9][0-9]"
    r"|^(SMTPConnectError|SMTPServerDisconnected|SMTPHeloError|ConnectionRefusedError"
    r"|ConnectionResetError|ConnectionAbortedError|TimeoutError|timeout|gaierror"
    r"|OSError|SSLError|SSLCertVerificationError): "
)


@dataclass(frozen=True)
class Row:
    """What a connection is, as the frame writes it, and how its facts are read."""

    key: str
    name: str
    what: str
    used_by: str
    when_label: str
    key_form: str | None
    #: Reads the source and returns (state, why, when).
    read: Callable[[Session], tuple[str, str | None, datetime | None]]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _operations(source: str) -> Callable[[Session], tuple[str, str | None, datetime | None]]:
    """Shopify, Bosta or E-stebdal: Operations' own freshness for it.

    ``when`` is the last clean read, whatever the state - a failed source's
    last good numbers are as of then."""

    def read(db: Session):
        facts = operations.source_state(db, source)
        state = _FROM_FRESHNESS[facts["state"]]
        why = {
            State.FAILED: facts["error"] or "The latest read failed.",
            State.LATE: LATE_WHY,
            State.NOT_CONNECTED: NO_KEY,
        }.get(state)
        return state, why, facts["read_at"]

    return read


def _whatsapp(db: Session):
    """No connection saved: not connected. Saved but its keys cannot be read
    here: failed, with the Inbox's own words. Otherwise working, as of the
    latest message either way."""
    facts = inbox.whatsapp_connection(db)
    if not facts["saved"]:
        return State.NOT_CONNECTED, NO_KEY, None
    if not facts["readable"]:
        return State.FAILED, facts["problem"] or "Its keys cannot be read here. Save them again.", facts["last_message_at"]
    return State.WORKING, None, facts["last_message_at"]


def _plain(error: str | None) -> str:
    """An outbox error as a sentence for the owner.

    An error carrying an exception's name is one the outbox retried until it
    gave up; the name goes, and that it was retried is said instead."""
    raw = (error or "").strip()
    text = _EXCEPTION_NAME.sub("", raw, count=1).strip()
    if not text:
        return "The last email could not be sent."
    if text != raw:
        text = f"Still failing after every retry: {text}"
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _email(db: Session):
    """No mail service set: not connected. The mail service's own latest
    failure (``TRANSPORT_FAILURE``) newer than the last email sent: failed,
    with its error. Otherwise working as of the last one sent; none ever
    sent: never.

    **Only a failure of the service itself counts.** An email refused for its
    own reasons - no address on file, a sign-in code that expired before it
    could go, an address the provider would not take - says nothing about
    whether mail works, and the next email goes out fine. Skipped emails
    were never attempted and are left out too.
    """
    if not settings.mail_configured:
        return State.NOT_CONNECTED, NO_MAIL, None
    last_sent = db.scalar(
        select(func.max(NotificationOutbox.sent_at)).where(
            NotificationOutbox.state == NotificationState.SENT
        )
    )
    failure = db.execute(
        select(NotificationOutbox.last_error, NotificationOutbox.created_at)
        .where(
            NotificationOutbox.state == NotificationState.FAILED,
            NotificationOutbox.last_error.regexp_match(TRANSPORT_FAILURE),
        )
        .order_by(NotificationOutbox.created_at.desc(), NotificationOutbox.id.desc())
        .limit(1)
    ).first()
    # A failed email records no time of its own but when it was written.
    if failure is not None and (last_sent is None or failure.created_at > last_sent):
        return State.FAILED, _plain(failure.last_error), failure.created_at
    if last_sent is None:
        return State.NEVER, None, None
    return State.WORKING, None, last_sent


def _storage(db: Session):
    """No bucket set: not connected. The latest file's copy failed: failed.
    Otherwise working as of the last file kept; none yet: never. No size:
    reading it would be a call to the bucket (Choice 9)."""
    facts = inbox.file_storage(db)
    if not facts["configured"]:
        return State.NOT_CONNECTED, NO_BUCKET, None
    if facts["latest"] == "failed":
        return State.FAILED, FILE_FAILED, facts["latest_at"]
    if facts["last_stored_at"] is None:
        return State.NEVER, None, None
    return State.WORKING, None, facts["last_stored_at"]


#: Every connection, in the frame's fixed order: a broken row is not moved.
ROWS: tuple[Row, ...] = (
    Row("bosta", "Bosta", "Deliveries", "Used by Operations and order pages",
        "Last read", "bosta", _operations("bosta")),
    Row("shopify", "Shopify", "Orders, products and tags", "Used by Operations, Affiliates and Inbox",
        "Read at", "shopify", _operations("shopify")),
    Row("whatsapp", "WhatsApp", "Customer chats and confirmations", "Used by Inbox",
        "Last message", "whatsapp", _whatsapp),
    Row("estebdal", "E-stebdal", "Returns and exchanges", "Used by Operations",
        "Read at", "estebdal", _operations("estebdal")),
    Row("email", "Email", "Invitations, password resets, model emails", "Used by everyone",
        "Last sent", None, _email),
    # Not frame 6's "receipts" / "Inbox and Affiliates": only the Inbox's
    # files go to the bucket; models' proofs are kept in the database.
    Row("storage", "File storage", "Chat photos and voice notes", "Used by Inbox",
        "Last file stored", None, _storage),
)


def _read(db: Session, row: Row) -> tuple[str, str | None, datetime | None]:
    """One row's facts, or ``unknown`` when they could not be read.

    Inside a savepoint, so a failed query leaves the session usable for the
    rows after it.
    """
    try:
        with db.begin_nested():
            return row.read(db)
    except Exception:
        logger.exception("integrations: %s could not be read", row.key)
        return State.UNKNOWN, None, None


def connections(db: Session, now: datetime, rows: tuple[Row, ...] = ROWS) -> dict:
    """The page's whole answer, as of ``now``."""
    body = []
    for row in rows:
        state, why, when = _read(db, row)
        body.append(
            {
                "key": row.key,
                "name": row.name,
                "what": row.what,
                "used_by": row.used_by,
                "state": state,
                # Said only where something is wrong or missing.
                "why": why if state in (State.FAILED, State.LATE, State.NOT_CONNECTED) else None,
                "when_label": row.when_label,
                "when": _iso(when),
                "key_form": row.key_form,
            }
        )
    return {"checked_at": now.isoformat(), "connections": body}
