"""What the operations dashboard last read from each source (ADR 0057).

Operations shows numbers from Shopify, Bosta and E-stebdal, each read every
5 minutes into the platform's own tables. A number is only worth showing with
the time it was read, and a source that could not be read must show as a
failure rather than as 0 - so how each source's last read went is kept here,
one row per source, and every response about a source carries it.

Nothing here holds customer details, keys or anything that decides pay.
"""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
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


class OpsBostaDelivery(Base):
    """One order HBA has on Bosta, as the platform last read it (ADR 0057).

    A mirror, not a snapshot: Bosta holds every order HBA ever sent, and the
    success rate needs months of them, so rows are upserted and kept. One
    that Bosta no longer has is marked ``deleted_at`` rather than removed.

    **No customer details.** Bosta's answer carries the receiver's name,
    phone and address, notes, the cash to collect and more; only the fields
    below are read out of it. Bosta never decides pay (ADR 0023).
    """

    __tablename__ = "ops_bosta_delivery"
    __table_args__ = (
        UniqueConstraint("tracking_number", name="ops_bosta_delivery_tracking_number"),
        Index("ix_ops_bosta_delivery_state_code", "state_code"),
        Index("ix_ops_bosta_delivery_created_at", "created_at"),
        Index("ix_ops_bosta_delivery_collected_at", "collected_at"),
        # Which of a week's orders Bosta holds (Today's orders panel).
        Index("ix_ops_bosta_delivery_shopify_order_number", "shopify_order_number"),
    )

    bosta_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tracking_number: Mapped[str] = mapped_column(String(40), nullable=False)
    #: "Send", "Exchange", "Customer Return Pickup", "Return to Origin", ...
    type_value: Mapped[str] = mapped_column(String(60), nullable=False)
    state_code: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    state_value: Mapped[str | None] = mapped_column(String(80))
    #: When the order was created on Bosta (``creationTimestamp``).
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at_bosta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: When Bosta collected it from HBA (``collectedFromBusiness``). Not
    #: ``state.pickedUpTime``, which carries the delivery date.
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: When its airway bill was last printed (``latestAWBPrintDate``).
    awb_printed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Bosta's "waiting for business action" flag, behind its own count.
    waiting_for_action: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: From ``businessReference`` ("<store>:#31038"), where Bosta has one.
    shopify_order_number: Mapped[str | None] = mapped_column(String(60))
    #: Still on its way somewhere (``bosta.UNFINISHED``), as of the last read.
    unfinished: Mapped[bool] = mapped_column(Boolean, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OpsBostaSync(Base):
    """How far the Bosta mirror has read. One row.

    History is read backwards a few days per read, from the first day the
    mirror ran back to 1 January 2026, so the most recent ranges are whole
    first. ``backfill_next`` is the next day to read; null once complete.
    """

    __tablename__ = "ops_bosta_sync"
    __table_args__ = (CheckConstraint("id = 1", name="ops_bosta_sync_one_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    backfill_next: Mapped[date | None] = mapped_column(Date)
    #: The newest ``updatedAt`` seen; changes are read down to just below it.
    high_water: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OpsIntegrationKey(Base):
    """A Bosta or E-stebdal key saved from Settings, overriding the server's.

    One row per provider. **The key is stored encrypted** (Fernet, keyed by
    ``SETTINGS_ENCRYPTION_KEY``) and is never read back out of the API, a
    log or the audit trail. A row is written only after its key answered
    the provider, so the key in use is always one that worked.
    """

    __tablename__ = "ops_integration_key"
    __table_args__ = (
        CheckConstraint("provider IN ('bosta', 'estebdal')", name="ops_integration_key_provider_valid"),
    )

    provider: Mapped[str] = mapped_column(String(20), primary_key=True)
    #: Fernet token of the key. Never the key itself.
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    #: Its last four characters, so a person can tell two keys apart (the
    #: approved mockup's "ends in a1b2").
    hint: Mapped[str] = mapped_column(String(8), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_by: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
