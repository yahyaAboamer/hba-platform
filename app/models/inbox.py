"""The customer inbox: WhatsApp chats and order confirmations (ADR 0059).

**These are the only tables that hold customer data** - a phone number, a
name, what was said, and the files sent. ``order_index`` and
``attributed_order`` still hold none, and nothing in Operations reads a
name, a phone or a message from here.

A phone is stored as digits with its country code and no plus sign
(``201005550188``), the form WhatsApp itself uses, so one customer is one
conversation however her number was typed on the order.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

DIRECTIONS = ("in", "out")

#: What a message is. ``button`` is a customer's tap on Confirm, Edit or
#: Cancel; ``template`` is an approved message we sent.
MESSAGE_KINDS = (
    "text", "image", "audio", "video", "document", "sticker",
    "template", "button", "reaction", "unsupported",
)

#: ``received`` is a customer's message; the rest follow one we sent, in the
#: order WhatsApp reports them.
MESSAGE_STATUSES = ("received", "queued", "sent", "delivered", "read", "failed")

#: Who a message came from. ``imported`` is a reply brought over from the old
#: inbox, which never recorded its sender.
MESSAGE_ORIGINS = ("customer", "staff", "automatic", "imported")

#: ``pending`` has not been copied yet; ``gone`` is a file WhatsApp deleted
#: before we had a copy, which is nearly every file from the old inbox.
MEDIA_STATES = ("pending", "stored", "gone", "failed")

#: Where an order's confirmation message stands.
#: - ``not_needed``: a paid order. It never gets a message and is finished,
#:   not failed.
#: - ``would_send``: the silent run beside the old automation - what would
#:   have been sent, with nothing sent.
#: - ``sending``: claimed by the sender, in a transaction of its own, just
#:   before WhatsApp is asked. An order is claimed once, so a crash after
#:   WhatsApp accepted the message can never send it a second time.
CONFIRMATION_STATES = (
    "pending", "sending", "would_send", "sent", "failed",
    "not_needed", "no_phone", "bad_phone", "no_whatsapp",
)

CONFIRMATION_ANSWERS = ("confirmed", "edit", "cancelled")

#: What an order's message is (ADR 0062): the confirmation, or - for an
#: international order that still owes money - a request to pay by link.
CONFIRMATION_KINDS = ("confirmation", "payment")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class InboxConversation(Base):
    """One customer, by phone. Every message with her hangs off this."""

    __tablename__ = "inbox_conversation"
    __table_args__ = (
        CheckConstraint("unread_count >= 0", name="inbox_conversation_unread_not_negative"),
        CheckConstraint(
            f"last_direction IS NULL OR {_in('last_direction', DIRECTIONS)}",
            name="inbox_conversation_last_direction_valid",
        ),
        # The list is read newest first, a page at a time.
        Index(
            "inbox_conversation_recent",
            text("last_message_at DESC NULLS LAST"),
            text("id DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    #: Her WhatsApp profile name, or the name on her order. Either may be absent.
    name: Mapped[str | None] = mapped_column(String(120))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: When she last wrote. Free replies are allowed for 24 hours after it.
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: The list's second line, so the list never reads the messages table.
    last_preview: Mapped[str | None] = mapped_column(String(160))
    last_direction: Mapped[str | None] = mapped_column(String(3))
    unread_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class InboxMessage(Base):
    """One message, either way."""

    __tablename__ = "inbox_message"
    __table_args__ = (
        CheckConstraint(_in("direction", DIRECTIONS), name="inbox_message_direction_valid"),
        CheckConstraint(_in("kind", MESSAGE_KINDS), name="inbox_message_kind_valid"),
        CheckConstraint(_in("status", MESSAGE_STATUSES), name="inbox_message_status_valid"),
        CheckConstraint(_in("origin", MESSAGE_ORIGINS), name="inbox_message_origin_valid"),
        # Only a member of staff has a name to put on a message.
        CheckConstraint(
            "sent_by IS NULL OR origin = 'staff'", name="inbox_message_sender_is_staff"
        ),
        # A chat is read oldest to newest, a page at a time from the end.
        Index("inbox_message_thread", "conversation_id", "occurred_at", "id"),
        Index("inbox_message_order", "shopify_order_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("inbox_conversation.id", ondelete="CASCADE"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(3), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    #: WhatsApp's own id for the message. Unique, so a callback Meta repeats
    #: can never store the same message twice.
    wa_message_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    #: The message this one answers, by WhatsApp's id.
    reply_to_wa_id: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    #: Why WhatsApp refused it, in our own words. Never a key.
    error: Mapped[str | None] = mapped_column(String(300))
    origin: Mapped[str] = mapped_column(String(10), nullable=False)
    #: The member of staff who sent it. Null for a customer's message, an
    #: automatic one, and anything brought over from the old inbox.
    sent_by: Mapped[int | None] = mapped_column(ForeignKey("user_account.id"))
    #: The order this message is about, when it is about one.
    shopify_order_id: Mapped[str | None] = mapped_column(String(64))
    template_name: Mapped[str | None] = mapped_column(String(120))
    #: What does not fit a column: the buttons a template offered, the one
    #: she tapped, a reaction's emoji.
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    #: When it was sent or received, by WhatsApp's clock.
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    #: Where an imported message came from (``n8n:<id>``). Unique, so the
    #: import can be run again without doubling anything.
    source_ref: Mapped[str | None] = mapped_column(String(80), unique=True)


class InboxMedia(Base):
    """The file on a message: a photo, a voice note, a video or a document.

    WhatsApp deletes an incoming file after 7 days, so it is copied to our
    own storage when it arrives and ``storage_key`` says where.
    """

    __tablename__ = "inbox_media"
    __table_args__ = (
        CheckConstraint(_in("state", MEDIA_STATES), name="inbox_media_state_valid"),
        # A stored file says where it is; anything else has nowhere to say.
        CheckConstraint(
            "(state = 'stored') = (storage_key IS NOT NULL)",
            name="inbox_media_stored_has_a_place",
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0", name="inbox_media_size_not_negative"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("inbox_message.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    #: WhatsApp's id for the file, which is what a copy is fetched by.
    wa_media_id: Mapped[str | None] = mapped_column(String(200))
    mime_type: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    filename: Mapped[str | None] = mapped_column(String(255))
    sha256: Mapped[str | None] = mapped_column(String(64))
    storage_key: Mapped[str | None] = mapped_column(String(400))
    state: Mapped[str] = mapped_column(String(8), nullable=False, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class OrderConfirmation(Base):
    """Where one order's confirmation message stands. One row per order.

    The row is the guard against a second message: ``shopify_order_id`` is
    unique, so an order is confirmed once however many times its webhook
    arrives or somebody presses Send again.
    """

    __tablename__ = "order_confirmation"
    __table_args__ = (
        CheckConstraint(_in("state", CONFIRMATION_STATES), name="order_confirmation_state_valid"),
        CheckConstraint(
            f"answer IS NULL OR {_in('answer', CONFIRMATION_ANSWERS)}",
            name="order_confirmation_answer_valid",
        ),
        CheckConstraint("attempts >= 0", name="order_confirmation_attempts_not_negative"),
        CheckConstraint(_in("kind", CONFIRMATION_KINDS), name="order_confirmation_kind_valid"),
        # What the sender picks up next.
        Index(
            "order_confirmation_due",
            "next_attempt_at",
            postgresql_where=text("state = 'pending'"),
        ),
        Index("order_confirmation_state_placed", "state", "placed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shopify_order_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    #: "#31044" - what staff and the customer call it.
    order_name: Mapped[str | None] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(12), nullable=False, server_default="pending")
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("inbox_conversation.id", ondelete="SET NULL")
    )
    #: The three things the message says, as they were when it was built.
    phone: Mapped[str | None] = mapped_column(String(20))
    customer_name: Mapped[str | None] = mapped_column(String(120))
    total_text: Mapped[str | None] = mapped_column(String(32))
    answer: Mapped[str | None] = mapped_column(String(10))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(300))
    #: WhatsApp's id for the confirmation, which a delivery failure names.
    wa_message_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    placed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: ``confirmation``, or ``payment`` for an unpaid international order
    #: (ADR 0062). Decided once, with the row.
    kind: Mapped[str] = mapped_column(
        String(12), nullable=False, default="confirmation", server_default="confirmation"
    )
    #: Where the order ships, as Shopify writes it: ``SA``. Only kept for a
    #: payment request, whose number is read with this country's code.
    country: Mapped[str | None] = mapped_column(String(2))
    #: A payment request's one reminder. Set just before it is sent, so it
    #: is sent at most once.
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: When a payment request's order was seen paid.
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: When Shopify was asked to email the order's invoice - set just before
    #: asking, so it is asked once - and why it refused, if it did.
    invoice_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invoice_error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class MetaWebhookEvent(Base):
    """A callback from Meta, stored before anything acts on it.

    Unlike ``integration_event`` this keeps the payload (ADR 0020 keeps only a
    digest there): a customer's message exists nowhere else until it has been
    applied, so it is written down first. ``digest`` is the SHA-256 of the
    exact bytes Meta sent; it is unique, so a callback Meta repeats is stored
    once and applied once.
    """

    __tablename__ = "meta_webhook_event"
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="meta_webhook_event_attempts_not_negative"),
        Index(
            "meta_webhook_event_waiting",
            "received_at",
            postgresql_where=text("processed_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(String(300))


class InboxConnection(Base):
    """The WhatsApp connection saved from Settings. One row at most.

    **The three secrets are stored encrypted** (Fernet, keyed by
    ``SETTINGS_ENCRYPTION_KEY``) and are never read back out of the API, a
    log or the audit trail. A row is written only after its keys answered
    Meta, so the connection in use is always one that worked.

    ``sending_enabled`` is off until an admin turns it on: a saved connection
    receives, and sends nothing on its own.
    """

    __tablename__ = "inbox_connection"
    __table_args__ = (CheckConstraint("id = 1", name="inbox_connection_single_row"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Meta's id for the number, and for the business account it belongs to.
    phone_number_id: Mapped[str] = mapped_column(String(40), nullable=False)
    business_account_id: Mapped[str] = mapped_column(String(40), nullable=False)
    #: What Meta said the number and its name were when the keys last answered.
    display_number: Mapped[str | None] = mapped_column(String(32))
    verified_name: Mapped[str | None] = mapped_column(String(120))
    #: Fernet tokens. Never the values themselves.
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    app_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    verify_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    #: Last four characters, to tell two keys apart.
    access_token_hint: Mapped[str] = mapped_column(String(8), nullable=False)
    app_secret_hint: Mapped[str] = mapped_column(String(8), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sending_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    updated_by: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ShopifyTagsConnection(Base):
    """The second Shopify connection, used to write order tags and nothing else.

    ADR 0059, point 11. The connection that reads money stays read-only
    (ADR 0015); this one belongs to a different app on the same store and is
    used only to add and remove the five confirmation tags. One row at most,
    its secret encrypted like the others.
    """

    __tablename__ = "shopify_tags_connection"
    __table_args__ = (CheckConstraint("id = 1", name="shopify_tags_connection_single_row"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    client_secret_hint: Mapped[str] = mapped_column(String(8), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_by: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
