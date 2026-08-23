"""Converting a Shopify order node into order_index values.

This is the only place raw Shopify data enters the system, so two rules from
the specification are enforced right here at the boundary rather than trusted
to hold further in.

Money becomes integer piastres immediately, via Decimal. Shopify returns
amounts as decimal strings; parsing one into a float would introduce exactly
the imprecision the money design exists to prevent, and it would be impossible
to detect afterwards.

The business month is derived in Africa/Cairo, never from the UTC prefix of the
timestamp. An order placed at 21:30 UTC on 31 August belongs to September, and
getting this wrong moves money between payroll periods.
"""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.businesstime import business_month, utcnow

PIASTRES_PER_POUND = 100


def money_to_piastres(amount: str | int | None) -> int:
    """Convert a Shopify decimal string to integer piastres.

    Floats are refused outright. Accepting one would mean the value had already
    lost precision before it arrived here, and no amount of care downstream
    could recover it.
    """
    if amount is None or amount == "":
        return 0
    if isinstance(amount, float):
        raise TypeError("Money must arrive as a string, never a float")
    try:
        value = Decimal(str(amount))
    except InvalidOperation as exc:
        raise ValueError(f"Unparseable money value: {amount!r}") from exc
    return int(
        (value * PIASTRES_PER_POUND).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def _money(block: dict | None) -> tuple[int, str | None]:
    shop_money = ((block or {}).get("shopMoney")) or {}
    return money_to_piastres(shop_money.get("amount")), shop_money.get("currencyCode")


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def normalise_order(node: dict) -> dict:
    """Map a Shopify order node onto order_index columns."""
    gid = str(node.get("id") or "")
    legacy = node.get("legacyResourceId")
    order_id = str(legacy) if legacy else (gid.rsplit("/", 1)[-1] if gid else "")
    if not order_id:
        raise ValueError("Shopify order node has no identifier")

    created_at = _timestamp(node.get("createdAt"))
    if created_at is None:
        raise ValueError(f"Shopify order {order_id} has no createdAt")

    subtotal, currency = _money(node.get("currentSubtotalPriceSet"))
    total, total_currency = _money(node.get("currentTotalPriceSet"))
    shipping, _ = _money(node.get("totalShippingPriceSet"))
    tax, _ = _money(node.get("currentTotalTaxSet"))

    codes = []
    for code in node.get("discountCodes") or []:
        cleaned = str(code or "").strip().upper()
        if cleaned:
            codes.append(cleaned)

    return {
        "shopify_order_id": order_id,
        "shopify_order_gid": gid or None,
        "order_number": str(node.get("name") or ""),
        "placed_at": created_at,
        # Derived in Cairo. This decides the payroll month.
        "business_month": business_month(created_at),
        "updated_at_shopify": _timestamp(node.get("updatedAt")),
        "cancelled_at": _timestamp(node.get("cancelledAt")),
        "financial_status": str(node.get("displayFinancialStatus") or "").lower() or None,
        "fulfillment_status": str(node.get("displayFulfillmentStatus") or "").lower()
        or None,
        "discount_codes": codes,
        "subtotal_piastres": subtotal,
        "total_piastres": total,
        "shipping_piastres": shipping,
        "tax_piastres": tax,
        "currency": currency or total_currency or "EGP",
    }


def upsert_order_index(db: Session, values: dict):
    """Insert or update one order by its Shopify id.

    Orders arrive more than once - a webhook, then a reconciliation sweep, then
    perhaps a re-import - so writing has to be idempotent or the same order
    would appear repeatedly.
    """
    from app.models.orders import OrderIndex

    payload = {**values, "last_synced_at": utcnow()}
    statement = insert(OrderIndex).values(**payload)
    statement = statement.on_conflict_do_update(
        index_elements=[OrderIndex.shopify_order_id],
        # first_seen_at is deliberately absent from the update: it records when
        # the platform first saw the order and must not move on a later touch.
        set_={
            key: statement.excluded[key]
            for key in payload
            if key not in ("shopify_order_id", "first_seen_at")
        },
    )
    db.execute(statement)
    return db.get(OrderIndex, values["shopify_order_id"])
