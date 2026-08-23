"""Durability for inbound events and background work.

``integration_event`` is an immutable receipt of everything that arrived. It is
append-only, enforced by the same database trigger as the audit log, because a
receipt you can edit proves nothing.

It stores a **digest** of the payload, not the payload (ADR 0020). Append-only
means whatever it holds it holds forever, and holding Shopify's full JSON would
put hundreds of megabytes a year into a table nothing can delete from.

``background_job`` is the queue. Postgres provides it, so there is no Redis and
no queue service to pay for or operate. A lease with an expiry is what makes it
safe: a worker that crashes mid-job loses its lease, and the job is picked up
again rather than vanishing.
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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class IntegrationEvent(Base):
    """Proof that an external system sent us something. Append-only.

    Deliberately *not* indexed on ``topic``. The unique constraint already
    serves deduplication, ``entity_id`` answers "what happened to this order?",
    and ``received_at`` drives the operational view. A topic index would cost a
    write on every webhook to speed up a query nobody runs outside a diagnosis.
    """

    __tablename__ = "integration_event"
    __table_args__ = (
        # The idempotency key. A redelivered webhook collides here and is
        # recognised as a duplicate rather than processed twice.
        UniqueConstraint("source", "external_id", name="integration_event_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    topic: Mapped[str] = mapped_column(String(80), nullable=False)

    #: The thing the event is about - a Shopify order id, usually. Indexed
    #: because "did we ever receive anything for order X?" is the question
    #: asked when an order goes missing.
    entity_id: Mapped[str | None] = mapped_column(String(64), index=True)

    #: SHA-256 of the canonical payload, or NULL for an empty body. Enough to
    #: notice that a redelivery carried different content; not enough to
    #: reconstruct it, which is what Shopify is for.
    payload_digest: Mapped[str | None] = mapped_column(String(64))

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), index=True
    )


class BackgroundJob(Base):
    """A unit of work that survives a restart.

    Unlike ``integration_event`` this table is mutable and prunable by design:
    a succeeded job is a receipt nobody needs. Failed jobs stay.
    """

    __tablename__ = "background_job"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="background_job_status_valid",
        ),
        # Partial, covering only rows the leasing query can return. Succeeded
        # and failed jobs are the bulk of the table over time and are never
        # leased, so indexing them would be paying to store rows we exclude.
        Index(
            "background_job_runnable_idx",
            "status",
            "run_after",
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
        # At most one outstanding job per dedupe key. Shopify sends create,
        # update and paid for the same order within seconds; that is one piece
        # of work, not three. Partial, so the key is reusable once the job
        # finishes - a later genuine change must not be swallowed.
        Index(
            "background_job_dedupe_idx",
            "dedupe_key",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Not indexed. Succeeded jobs are pruned, so this table stays in the low
    #: thousands of rows, where a scan is faster than maintaining an index on
    #: every enqueue.
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    #: Capped at MAX_ATTEMPTS, so smallint is the honest width.
    attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    leased_by: Mapped[str | None] = mapped_column(String(80))
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
