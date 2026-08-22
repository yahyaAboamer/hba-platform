"""Append-only business audit trail.

Every mutation that matters records who did it, what changed, when, and why
where a reason is required. The table is append-only and the database enforces
that (see the trigger migration), so the trail cannot be rewritten by anyone —
including this application.

actor_id uses ON DELETE RESTRICT rather than SET NULL. Nulling the column would
be an UPDATE, which the append-only trigger blocks, so SET NULL would fail with
a confusing error at delete time. RESTRICT states the real rule plainly: an
account that has done something is suspended, never deleted. actor_email is
stored alongside the id so the record stays readable regardless.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AuditEvent(Base):
    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT")
    )
    actor_email: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), index=True
    )
