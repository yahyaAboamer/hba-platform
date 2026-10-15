"""Gifts that reached nobody on the roster, and staff saying whose each was.

ADR 0060. Matching is by the phone on the parcel (W03), and on 15 October 47 of
HBA's gifts had been shipped to numbers no model had on her profile. They were
stored as `no_match` - *a customer* - and listed nowhere, so a model's gifts
were missing from her wardrobe and nothing on any screen said so.

**Nothing here guesses.** A recipient's name beside a model's is a reason for a
person to look, not a match. Staff choose; the platform records it, and
remembers the number for next time (`recipients.match_recipient`).
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.models.affiliates import AccountKind, AffiliateProfile
from app.models.orders import OrderIndex
from app.models.shipments import ModelShipment
from app.services.audit import record_audit
from app.services.jobs import JobKind, enqueue
from app.services.recipients import (
    AMBIGUOUS,
    ASSIGNED,
    NOT_A_MODEL,
    match_recipient,
)

#: Rows per look. The real list was 47; a list longer than this is a backlog,
#: and the count beside it says how much is left.
LIST_LIMIT = 50

#: Who the parcel was shipped to and what was in it. Read when the list opens,
#: because the platform stores neither for a parcel that matched nobody.
RECIPIENTS = """
query GiftRecipients($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on Order {
      legacyResourceId
      shippingAddress { name phone }
      lineItems(first: 10) { nodes { title quantity } }
    }
  }
}
"""


class ParcelNotFound(LookupError):
    pass


class ParcelRefused(ValueError):
    """A sentence for the person who clicked."""


def _unclaimed():
    """Free, carrying a discount code, not cancelled, and nobody's.

    *Free* is the order's original subtotal, as everywhere (W04). *A code* is
    what makes it HBA's gift rather than an exchange: a Return Prime exchange
    is free too, carries no code, and is a customer swapping a size. Ambiguous
    parcels have their own list, where the fix is two models' phones.
    """
    return (
        select(ModelShipment, OrderIndex)
        .join(OrderIndex, OrderIndex.shopify_order_id == ModelShipment.shopify_order_id)
        .where(ModelShipment.affiliate_id.is_(None))
        .where(ModelShipment.match_reason.not_in((NOT_A_MODEL, AMBIGUOUS)))
        .where(OrderIndex.original_subtotal_piastres.is_not(None))
        .where(OrderIndex.original_subtotal_piastres <= 0)
        .where(func.cardinality(OrderIndex.discount_codes) > 0)
        .where(OrderIndex.cancelled_at.is_(None))
    )


def unclaimed_gifts(db: Session, client=None, *, limit: int = LIST_LIMIT) -> dict:
    """The list, newest first, with who received each when Shopify can say.

    `client` is optional so that Shopify being unreachable costs the names and
    not the list: the orders are known here, and a row without a name is
    still a row somebody can open in Shopify.
    """
    rows = list(db.execute(_unclaimed().order_by(OrderIndex.placed_at.desc()).limit(limit)))
    total = db.scalar(select(func.count()).select_from(_unclaimed().subquery())) or 0

    tokens = [shipment.recipient_token for shipment, _ in rows if shipment.recipient_token]
    per_number: dict[str, int] = {}
    if tokens:
        per_number = dict(
            db.execute(
                select(ModelShipment.recipient_token, func.count())
                .where(ModelShipment.affiliate_id.is_(None))
                .where(ModelShipment.match_reason != NOT_A_MODEL)
                .where(ModelShipment.recipient_token.in_(set(tokens)))
                .group_by(ModelShipment.recipient_token)
            ).all()
        )

    shipped: dict[str, dict] = {}
    # No connection at all is the same answer to the person reading the list:
    # the names could not be read.
    read_failed = bool(rows) and client is None
    if rows and client is not None:
        try:
            payload = client.execute(
                RECIPIENTS,
                {"ids": [f"gid://shopify/Order/{order.shopify_order_id}" for _, order in rows]},
            )
            for node in (payload or {}).get("nodes") or []:
                if node and node.get("legacyResourceId"):
                    shipped[str(node["legacyResourceId"])] = node
        except Exception:  # noqa: BLE001 - names are a convenience; see the docstring
            read_failed = True

    gifts = []
    for shipment, order in rows:
        node = shipped.get(order.shopify_order_id) or {}
        address = node.get("shippingAddress") or {}
        items = ((node.get("lineItems") or {}).get("nodes")) or []
        gifts.append(
            {
                "shopify_order_id": order.shopify_order_id,
                "order_number": order.order_number,
                "placed_at": order.placed_at.isoformat(),
                "discount_codes": list(order.discount_codes or []),
                "recipient_name": address.get("name"),
                "phone": address.get("phone") or shipment.recipient_token,
                "items": [f"{item.get('quantity', 1)}× {item.get('title', '')}" for item in items],
                # The other parcels one click will move with this one.
                "same_number": per_number.get(shipment.recipient_token or "", 1),
            }
        )

    models = [
        {"id": model.id, "name": model.name}
        for model in db.scalars(
            select(AffiliateProfile)
            .where(AffiliateProfile.account_kind != AccountKind.HOUSE)
            .where(AffiliateProfile.archived_at.is_(None))
            .order_by(func.lower(AffiliateProfile.name))
        )
    ]
    return {"gifts": gifts, "total": total, "models": models, "names_unavailable": read_failed}


def _parcel(db: Session, order_id: str) -> ModelShipment:
    row = db.scalar(select(ModelShipment).where(ModelShipment.shopify_order_id == order_id))
    if row is None:
        raise ParcelNotFound(order_id)
    if row.affiliate_id is not None:
        raise ParcelRefused("This parcel is already attached to a model.")
    return row


def _same_number(db: Session, row: ModelShipment) -> list[ModelShipment]:
    """This parcel, and every other unmatched one sent to the same number.

    One person, one number: answering once for each of six parcels to "Mahmoud
    M" would be six clicks for one fact. A parcel with no usable number moves
    alone.
    """
    if not row.recipient_token:
        return [row]
    others = db.scalars(
        select(ModelShipment)
        .where(ModelShipment.affiliate_id.is_(None))
        .where(ModelShipment.recipient_token == row.recipient_token)
        .where(ModelShipment.id != row.id)
    )
    return [row, *others]


def assign_gift(db: Session, *, order_id: str, affiliate_id: int, actor) -> dict:
    """*This is her*: the parcel, and its number, become hers."""
    row = _parcel(db, order_id)
    model = db.get(AffiliateProfile, affiliate_id)
    if model is None or model.account_kind == AccountKind.HOUSE:
        raise ParcelRefused("Choose a model.")
    if model.archived_at is not None:
        raise ParcelRefused(f"{model.name} is archived and takes no new parcels.")

    # The number must not already be somebody else's. Assigning it would make
    # every later parcel to it ambiguous, and give this one to the wrong model.
    if row.recipient_token:
        owner = match_recipient(db, row.recipient_token)
        if owner["affiliate_id"] not in (None, affiliate_id) or owner["reason"] == AMBIGUOUS:
            others = sorted(
                profile.name
                for profile in db.scalars(
                    select(AffiliateProfile).where(
                        AffiliateProfile.id.in_(
                            owner.get("candidates") or [owner["affiliate_id"]]
                        )
                    )
                )
                if profile.id != affiliate_id
            )
            raise ParcelRefused(
                f"This number belongs to {', '.join(others)}. "
                "Fix the phone on her profile instead."
            )

    now = utcnow()
    moved = _same_number(db, row)
    for parcel in moved:
        parcel.affiliate_id = model.id
        parcel.match_reason = ASSIGNED
        parcel.matched_at = now
        parcel.updated_at = now
        enqueue(
            db,
            JobKind.SYNC_LINE_ITEMS,
            {"order_id": parcel.shopify_order_id},
            dedupe_key=f"{JobKind.SYNC_LINE_ITEMS}:{parcel.shopify_order_id}",
        )

    orders = sorted(parcel.shopify_order_id for parcel in moved)
    record_audit(
        db,
        action="parcel.assigned",
        subject=f"affiliate:{model.id}",
        actor_id=getattr(actor, "id", None),
        actor_email=getattr(actor, "email", None),
        after={"orders": orders},
    )
    db.flush()
    return {"affiliate_id": model.id, "orders": orders}


def dismiss_gift(db: Session, *, order_id: str, actor) -> dict:
    """*Not a model*: it leaves the list, and stays unmatched."""
    row = _parcel(db, order_id)
    now = utcnow()
    moved = _same_number(db, row)
    for parcel in moved:
        parcel.match_reason = NOT_A_MODEL
        parcel.updated_at = now

    orders = sorted(parcel.shopify_order_id for parcel in moved)
    record_audit(
        db,
        action="parcel.not_a_model",
        subject=f"order:{row.shopify_order_id}",
        actor_id=getattr(actor, "id", None),
        actor_email=getattr(actor, "email", None),
        after={"orders": orders},
    )
    db.flush()
    return {"orders": orders}
