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

``when`` is always the last time the connection worked (Bosta's last good
read, the last email sent, the last file kept), failed or not; when a failure
happened is said in ``why``, in Cairo time.
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.businesstime import at_words
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

#: The outbox errors that say **the mail service itself** is not working, as
#: ``notifications.send_notification`` and ``mail`` write them, each with what
#: the owner is told (``{at}`` is when, in Cairo time). The outbox keeps no
#: kind of failure, only its words, so these read the words those two modules
#: write - and ``tests/test_integrations.py`` drives that code, so a change of
#: wording there fails a test here. The first that matches says why.
#:
#: Anything else - no address, an expired code, one recipient or message
#: refused (another 4xx, an SMTP recipient refusal, a data error) - is that
#: email's own and says nothing about whether mail works.
#:
#: Postgres regular expressions as well as Python ones (matched in the query),
#: so no word boundaries or flags: the two write those differently.
SERVICE_FAILURES: tuple[tuple[str, str], ...] = (
    (r"^The mail account was refused",
     "The mail service refused the account's sign-in {at}."),
    (r"^STARTTLS extension not supported",
     "The mail server would not open a secure connection {at}."),
    # Before the key: Resend refuses an unverified domain with a 403.
    (r"^(resend|brevo) refused the message \(4[0-9][0-9]\): "
     r"(.*([Dd]omain|[Ss]ender).*([Nn]ot verified|[Nn]ot valid|[Uu]nverified)|.*Invalid `from`)",
     "The mail service refused the sender address {at}: its domain is not verified."),
    (r"^(resend|brevo) refused the message \((401|403)\)",
     "The mail service refused the key {at}."),
    (r"^(resend|brevo) refused the message \(429\)",
     "The mail service turned emails away as too many {at}."),
    # Only after every retry: these are tried again until they give up.
    (r"Could not reach (resend|brevo)|(resend|brevo) returned 5[0-9][0-9]"
     r"|^(SMTPConnectError|SMTPServerDisconnected|SMTPHeloError|ConnectionRefusedError"
     r"|ConnectionResetError|ConnectionAbortedError|TimeoutError|timeout|gaierror"
     r"|OSError|SSLError|SSLCertVerificationError): ",
     "The mail service could not be reached {at}, even after every retry."),
)

#: All of them at once, for the query.
SERVICE_FAILURE = "|".join(f"({pattern})" for pattern, _ in SERVICE_FAILURES)


def service_failure_why(error: str | None, at: str) -> str | None:
    """What the owner is told about one outbox error, or None when it is
    that email's own."""
    for pattern, sentence in SERVICE_FAILURES:
        if re.search(pattern, error or ""):
            return sentence.format(at=at)
    return None


#: What a row's reader returns: its state, why (in words), and ``when``.
Facts = tuple[str, str | None, datetime | None]


@dataclass(frozen=True)
class Row:
    """What a connection is, as the frame writes it, and how its facts are read."""

    key: str
    name: str
    what: str
    used_by: str
    when_label: str
    key_form: str | None
    #: Reads the source, as of ``now``.
    read: Callable[[Session, datetime], Facts]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _operations(source: str) -> Callable[[Session, datetime], Facts]:
    """Shopify, Bosta or E-stebdal: Operations' own freshness for it.

    ``when`` is the last clean read, whatever the state - a failed source's
    last good numbers are as of then."""

    def read(db: Session, now: datetime) -> Facts:
        facts = operations.source_state(db, source)
        state = _FROM_FRESHNESS[facts["state"]]
        why = {
            State.FAILED: facts["error"] or "The latest read failed.",
            State.LATE: LATE_WHY,
            State.NOT_CONNECTED: NO_KEY,
        }.get(state)
        return state, why, facts["read_at"]

    return read


def _whatsapp(db: Session, now: datetime) -> Facts:
    """No connection saved: not connected. Saved but its keys cannot be read
    here: failed, with the Inbox's own words. Otherwise working, as of the
    latest message either way."""
    facts = inbox.whatsapp_connection(db)
    if not facts["saved"]:
        return State.NOT_CONNECTED, NO_KEY, None
    if not facts["readable"]:
        why = facts["problem"] or "Its keys cannot be read here. Save them again."
        return State.FAILED, why, facts["last_message_at"]
    return State.WORKING, None, facts["last_message_at"]


def _email(db: Session, now: datetime) -> Facts:
    """No mail service set: not connected. The mail service's own latest
    failure (``SERVICE_FAILURES``) newer than the last email sent: failed,
    saying what and when. Otherwise working; nothing ever sent: never.

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
            NotificationOutbox.last_error.regexp_match(SERVICE_FAILURE),
        )
        .order_by(NotificationOutbox.created_at.desc(), NotificationOutbox.id.desc())
        .limit(1)
    ).first()
    # A failed email records no time of its own but when it was written.
    if failure is not None and (last_sent is None or failure.created_at > last_sent):
        why = service_failure_why(failure.last_error, at_words(failure.created_at, now))
        return State.FAILED, why, last_sent
    if last_sent is None:
        return State.NEVER, None, None
    return State.WORKING, None, last_sent


def _storage(db: Session, now: datetime) -> Facts:
    """No bucket set: not connected. The bucket refused the latest file whose
    copy into it finished: failed, saying when. Otherwise working; nothing
    kept yet: never. No size: reading it would be a call to the bucket
    (Choice 9)."""
    facts = inbox.file_storage(db)
    if not facts["configured"]:
        return State.NOT_CONNECTED, NO_BUCKET, None
    if facts["refused_at"] is not None:
        why = f"File storage refused the latest file {at_words(facts['refused_at'], now)}."
        return State.FAILED, why, facts["last_stored_at"]
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


def _read(db: Session, row: Row, now: datetime) -> Facts:
    """One row's facts, or ``unknown`` when they could not be read.

    Inside a savepoint, so a failed query leaves the session usable for the
    rows after it.
    """
    try:
        with db.begin_nested():
            return row.read(db, now)
    except Exception:
        logger.exception("integrations: %s could not be read", row.key)
        return State.UNKNOWN, None, None


def connections(db: Session, now: datetime, rows: tuple[Row, ...] = ROWS) -> dict:
    """The page's whole answer, as of ``now``."""
    body = []
    for row in rows:
        state, why, when = _read(db, row, now)
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
