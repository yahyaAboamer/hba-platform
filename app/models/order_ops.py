"""What the operations dashboard last read from each source (ADR 0057).

Operations shows numbers from Shopify, Bosta and E-stebdal, each read every
5 minutes into the platform's own tables. A number is only worth showing with
the time it was read, and a source that could not be read must show as a
failure rather than as 0 - so how each source's last read went is kept here,
one row per source, and every response about a source carries it.

Nothing here holds customer details, keys or anything that decides pay.
"""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class OpsSourceStatus(Base):
    """How the last read of one source went. One row per source, rewritten."""

    __tablename__ = "ops_source_status"
    __table_args__ = (
        CheckConstraint(
            "source IN ('shopify', 'bosta', 'estebdal')", name="ops_source_status_source_valid"
        ),
    )

    source: Mapped[str] = mapped_column(String(20), primary_key=True)

    #: False when the last read found no key to read with. A source nobody
    #: connected is "not connected", which is neither a failure nor a 0.
    connected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: The time every number from this source is shown with. Kept through a
    #: failure, so the last good numbers can be shown greyed with their time.
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Set while the latest read failed, cleared by the next good one. Plain
    #: words written by the platform, never a provider's response or a key.
    last_error: Mapped[str | None] = mapped_column(Text)

    #: How many rows the last good read stored.
    row_count: Mapped[int | None] = mapped_column(Integer)
