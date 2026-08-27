"""Emails the platform owes somebody.

§16: **every email is written through this table in the same transaction as the
change that caused it.** Not sent inline, and that is the whole design.

Sending inline couples an obligation to a mail server. A slow SMTP handshake
would make approving payroll slow; a refused connection would make approving
payroll *fail*, rolling back a month that was correctly agreed because an
unrelated service was down. That is the worst trade available: the figure was
right, the money is owed, and the platform threw it away to avoid sending an
email.

The opposite failure is just as bad and less obvious. A month agreed in one
transaction and an email queued in another, later one, is a model who was paid
and never told the moment anything crashes in between.

A row written inside the caller's transaction makes both impossible at once.
The month and the notice about it commit together or not at all.

**Mutable, unlike `integration_event` and `audit_event`.** An outbox row is a
piece of work that changes state as it is done, not a receipt. What was
actually sent is recorded in the audit trail beside it; this table is the
queue, and a queue nothing can update is not a queue.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class NotificationState:
    """Where an email has got to."""

    #: Written, not yet attempted.
    PENDING = "pending"

    #: Handed to the provider, which accepted it.
    SENT = "sent"

    #: Attempted enough times, or refused in a way retrying cannot fix.
    FAILED = "failed"

    #: Deliberately not sent. There is no address, or the platform has no mail
    #: credentials configured at all - which is the normal state of a
    #: development machine and of the test suite.
    #:
    #: **A distinct state from `failed` on purpose.** "Nobody has set this up"
    #: and "we tried and could not" produce the same silence for the recipient
    #: and completely different work for whoever is looking into it.
    SKIPPED = "skipped"


VALID_NOTIFICATION_STATES = frozenset(
    value
    for name, value in vars(NotificationState).items()
    if not name.startswith("_") and isinstance(value, str)
)


class NotificationOutbox(Base):
    """One email, owed to one person."""

    __tablename__ = "notification_outbox"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'sent', 'failed', 'skipped')",
            name="notification_outbox_state_valid",
        ),
        # Partial, covering only rows the sender can pick up. Sent rows are the
        # bulk of the table forever and are never selected by the drain query,
        # so indexing them would be paying to store what we exclude - the same
        # reasoning as `background_job_runnable_idx`.
        Index(
            "notification_outbox_pending_idx",
            "state",
            "id",
            postgresql_where=text("state = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    #: What happened. One of `app.services.notifications.Event`.
    event: Mapped[str] = mapped_column(String(60), nullable=False)

    #: Where it goes. Stored rather than resolved at send time: an address that
    #: changes between the event and the send should not silently redirect the
    #: notice about the change - which matters most for exactly the email that
    #: announces a payout destination was repointed.
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    recipient_name: Mapped[str | None] = mapped_column(String(120))

    #: Who it is about, for the operational view. Not a foreign key: an email
    #: is owed whether or not the row it concerns still resolves, and a queue
    #: that can be blocked by a delete is a queue that stops.
    subject_ref: Mapped[str | None] = mapped_column(String(80), index=True)

    #: **Frozen, not a set of references.** The same reasoning as
    #: `payroll_snapshot` (§11.1): an email resolving "her September figure" at
    #: send time would say something different from the screen if anything
    #: moved in between - and she will be reading both.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    state: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=NotificationState.PENDING
    )

    #: Capped by the sender, so smallint is the honest width.
    attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )

    #: Truncated rather than allowed to fail the write. Recording a failure
    #: must never itself fail - the same rule `background_job.last_error`
    #: follows, and for the same reason.
    last_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
