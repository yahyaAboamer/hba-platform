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
from sqlalchemy.dialects.postgresql import ARRAY
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


class OpsShopifyOrder(Base):
    """One open, unshipped Shopify order, as the last clean read found it.

    The whole set is replaced on every read, in the same transaction as the
    read's record in ``ops_source_status``: an order that shipped or was
    cancelled since simply is not here any more. **No customer details**:
    the order's number, when it was placed, its tags and how far it shipped.
    """

    __tablename__ = "ops_shopify_order"

    #: Shopify's numeric order id, for the link to the order in Shopify admin.
    shopify_order_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    #: As the shop shows it, e.g. "#30931".
    order_number: Mapped[str] = mapped_column(String(40), nullable=False)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    fulfillment_status: Mapped[str | None] = mapped_column(String(40))
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OpsEstebdalReturn(Base):
    """One return or exchange request waiting for review on E-stebdal.

    Replaced whole on every read, like ``ops_shopify_order``. E-stebdal's
    answer carries the customer's name, phone, address and the items; none
    of it is kept. Only the numbers a person needs to find the request.
    """

    __tablename__ = "ops_estebdal_return"

    estebdal_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    #: As E-stebdal shows it, e.g. "#30830-R1".
    return_number: Mapped[str] = mapped_column(String(40), nullable=False)
    #: The Shopify order it is for, e.g. "#30830".
    order_number: Mapped[str | None] = mapped_column(String(40))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
