"""What HBA has sent a model, and where each thing got to.

W06, W08, D05. The wardrobe is built from three things that already exist: the
shipments 03B matched, the line items 03A read, and the delivery state the
commission engine already derives from Shopify.

## Only gifts (D05, 10 September 2026)

> Anything that she bought? Then it's not shown in the wardrobe. We only return
> the products from the orders that have zero price.

So a `purchase` is excluded, and so is an `unknown` — unknown is not zero, and
telling a model she owns something the platform cannot show HBA gave her is the
error worth avoiding. The classification is still stored either way; what was
declined is showing it.

## One state per product, not per parcel

W06: *one shipment may contain many products; its status applies to each. The
normal replacement updates the latest relevant shipment for each product/model
pair, preserving earlier history. If only pants are resent, a previously failed
T-shirt stays Needs checking.*

That sentence is the whole design. The unit is **a product and a model**, not a
parcel — so a resend of one item cannot mark the rest of the parcel delivered.
Each pair takes the state of *its own most recent shipment*, and the earlier
ones stay readable underneath.

## Where the state comes from

Shopify, through the same derivation commission already trusts (F01):

    delivered   → received      it arrived
    failed      → failed        it did not, and will not
    anything else → processing  it is on its way

**Failed is shown and never hidden** (W08): a failed product must not look
owned, and must not vanish either — a model who was told something was sent has
to be able to see what happened to it.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow

from app.models.catalogue import OrderLineItem, Product
from app.models.orders import OrderIndex
from app.models.shipments import Classification, ModelShipment

#: How wide a grid thumbnail needs to be, at 2x for a retina phone.
#:
#: Shopify's CDN resizes on request, so asking for one is free and **not
#: asking is not**: a product photograph is commonly 2000px and several hundred
#: kilobytes, and a grid of sixty of them is tens of megabytes of image to draw
#: a page of thumbnails. That is the difference between a screen that appears
#: and one somebody waits for.
THUMBNAIL_WIDTH = 400


def thumbnail(url: str | None, width: int = THUMBNAIL_WIDTH) -> str | None:
    """The same image, asked for at the size it will actually be drawn.

    Only rewrites Shopify's own CDN, and only by adding a query parameter it
    documents. Anything else - a URL from somewhere else, or one that already
    carries a width - is returned untouched, because guessing at a foreign
    host's resizing scheme produces a broken image rather than a smaller one.
    """
    if not url:
        return None
    if "cdn.shopify.com" not in url:
        return url
    if "width=" in url:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}width={width}"


#: What a model sees against each product.
RECEIVED = "received"
PROCESSING = "processing"
FAILED = "failed"

#: Shopify's derived delivery state, mapped to a wardrobe state. The left-hand
#: values are `fulfilment.DELIVERED` / `FAILED`; anything else is still moving.
_FROM_DELIVERY = {"delivered": RECEIVED, "failed": FAILED}

#: The states that count as *having* the product, for a feature request (W10).
#: **Received or processing**, not failed - a parcel that did not arrive is not
#: something she can be asked to post about.
HOLDS = frozenset({RECEIVED, PROCESSING})


def _state_for(order: OrderIndex) -> str:
    return _FROM_DELIVERY.get(order.delivery_state or "", PROCESSING)


def _gift_lines(db: Session, affiliate_id: int | None = None, product_id: str | None = None):
    """Every line of every matched gift, newest order first, in **one query**.

    This used to be a loop: one query per shipment for its lines, then one more
    per line for its product. Twenty models with a year of parcels is a
    thousand round trips to draw one grid, and it is the shape that only shows
    itself once there is real data in the shop - which is exactly when somebody
    is watching a screen not load.

    Gift only, by D05. Ordered by when the order was *placed*, so "the latest
    relevant shipment" is decided by the calendar rather than by row id - a
    backfill inserts history out of order, and row id would make the oldest
    parcel look like the newest.
    """
    query = (
        select(ModelShipment, OrderIndex, OrderLineItem)
        .join(OrderIndex, OrderIndex.shopify_order_id == ModelShipment.shopify_order_id)
        .join(
            OrderLineItem,
            OrderLineItem.shopify_order_id == ModelShipment.shopify_order_id,
        )
        .where(ModelShipment.affiliate_id.is_not(None))
        .where(ModelShipment.classification == Classification.GIFT)
        .order_by(OrderIndex.placed_at.desc())
    )
    if affiliate_id is not None:
        query = query.where(ModelShipment.affiliate_id == affiliate_id)
    if product_id is not None:
        query = query.where(OrderLineItem.shopify_product_id == product_id)
    return db.execute(query).all()


def _products_by_id(db: Session, ids: set[str]) -> dict[str, Product]:
    """Every product named, in one query rather than one each."""
    clean = {value for value in ids if value}
    if not clean:
        return {}
    return {
        row.shopify_product_id: row
        for row in db.scalars(
            select(Product).where(Product.shopify_product_id.in_(clean))
        )
    }


def wardrobe_for(db: Session, affiliate_id: int) -> dict:
    """Everything HBA has sent her, one entry per product.

    **The latest shipment of each product wins, and the earlier ones stay.**
    W06's pants-and-T-shirt case: a resend that contains only the pants updates
    the pants and leaves the T-shirt exactly where it was.

    A product deleted from Shopify still appears. The line item carries its own
    title and size (03A), so the entry is complete without the catalogue row -
    it simply has no picture, which is the honest version of that state.

    Two queries total, whatever the size of her history.
    """
    rows = _gift_lines(db, affiliate_id)
    products = _products_by_id(db, {line.shopify_product_id for _, _, line in rows})

    entries: dict[str, dict] = {}

    for shipment, order, line in rows:
        state = _state_for(order)
        # Keyed by product where there is one, and by the line's own title
        # otherwise. A deleted product still belongs to her, and grouping every
        # untitled line together would merge two different garments.
        key = line.shopify_product_id or f"title:{line.title}"

        if key in entries:
            # Already have a newer shipment of this product. W06: the latest
            # wins and this one becomes history.
            entries[key]["history"].append(
                {
                    "shopify_order_id": shipment.shopify_order_id,
                    "state": state,
                    "placed_at": order.placed_at.isoformat()
                    if order.placed_at
                    else None,
                }
            )
            continue

        product = products.get(line.shopify_product_id or "")

        entries[key] = {
            "shopify_product_id": line.shopify_product_id,
            "title": line.title,
            "size": line.variant_title,
            "quantity": line.quantity,
            "state": state,
            "image_url": product.image_url if product else None,
            # Sized for a phone grid rather than a product page. The full one
            # stays beside it for anything that wants it.
            "image_thumb_url": thumbnail(product.image_url if product else None),
            "shopify_order_id": shipment.shopify_order_id,
            "placed_at": order.placed_at.isoformat() if order.placed_at else None,
            "history": [],
        }

    items = list(entries.values())
    return {
        # W08: Received first, with images and sizes. Then a compact
        # not-received area - **failed products must not look owned**, and must
        # not disappear either.
        "received": [row for row in items if row["state"] == RECEIVED],
        "processing": [row for row in items if row["state"] == PROCESSING],
        "failed": [row for row in items if row["state"] == FAILED],
    }


def roster_for(db: Session, shopify_product_id: str) -> dict:
    """Which models have this product, grouped as W02 asks.

    Received · Processing · Needs checking · Not sent, in that order. *Needs
    checking* is W02's name for a failed delivery: from the business's side it
    is not a category of ownership, it is a thing to do something about.

    **Not sent is everybody else**, which is what makes this a roster rather
    than a list of shipments - the question the screen answers is *who could I
    ask*, and a model who never received it is part of that answer.

    Two queries, not one per shipment in the shop. The first version asked
    "does this parcel contain this product" once per parcel, which is a
    thousand round trips on a real catalogue and invisible on an empty one.
    """
    from app.models.affiliates import AccountKind, AffiliateProfile

    latest: dict[int, str] = {}
    for shipment, order, _line in _gift_lines(db, product_id=shopify_product_id):
        # Newest first, so the first row seen for a model is the one that
        # counts and later rows are her earlier history.
        latest.setdefault(shipment.affiliate_id, _state_for(order))

    models = list(
        db.scalars(
            select(AffiliateProfile)
            .where(AffiliateProfile.account_kind != AccountKind.HOUSE)
            .order_by(AffiliateProfile.name)
        )
    )

    groups: dict[str, list] = {
        RECEIVED: [],
        PROCESSING: [],
        FAILED: [],
        "not_sent": [],
    }
    for model in models:
        row = {"affiliate_id": model.id, "name": model.name, "status": model.status}
        groups[latest.get(model.id, "not_sent")].append(row)

    # Names alphabetical inside groups (W02). The query already ordered by
    # name, so each list arrives sorted and nothing re-sorts it.
    return {
        "shopify_product_id": shopify_product_id,
        "received": groups[RECEIVED],
        "processing": groups[PROCESSING],
        "needs_checking": groups[FAILED],
        "not_sent": groups["not_sent"],
    }


def holds_product(db: Session, affiliate_id: int, shopify_product_id: str) -> bool:
    """Whether she has this product now, for W10's feature eligibility.

    **Received or processing**, never failed. A parcel that did not arrive is
    not something she can be asked to post about, and W10 is explicit that
    eligibility *changes with current shipment state* — so this reads the
    wardrobe rather than a stored flag, and a replacement entering processing
    makes her eligible again without anybody re-running anything.
    """
    wardrobe = wardrobe_for(db, affiliate_id)
    for state in (RECEIVED, PROCESSING):
        for row in wardrobe[state]:
            if row["shopify_product_id"] == shopify_product_id:
                return True
    return False


# ── Feature requests (W09, W10) ──────────────────────────────────────────────


def set_feature_request(
    db: Session,
    shopify_product_id: str,
    *,
    message: str | None = None,
    visible: bool | None = None,
    actor_id: int | None = None,
) -> "FeatureRequest":
    """Write or update what marketing would like said about a product.

    Three verbs in one function, because W09 names three and they are the same
    row: write the wording, make it visible, hide it. **Removing** is
    `remove_feature_request` — hiding keeps the wording and removing does not,
    and collapsing them would lose a paragraph somebody wrote.
    """
    from app.models.promotions import FeatureRequest

    request = db.get(FeatureRequest, shopify_product_id)
    if request is None:
        if message is None or not str(message).strip():
            raise ValueError("A feature request needs something to say")
        request = FeatureRequest(
            shopify_product_id=shopify_product_id,
            message=str(message).strip(),
            visible=bool(visible),
            updated_by=actor_id,
        )
        db.add(request)
        db.flush()
        return request

    if message is not None:
        cleaned = str(message).strip()
        if not cleaned:
            raise ValueError("A feature request needs something to say")
        request.message = cleaned
    if visible is not None:
        request.visible = bool(visible)
    request.updated_by = actor_id
    request.updated_at = utcnow()
    db.flush()
    return request


def remove_feature_request(db: Session, shopify_product_id: str) -> bool:
    """Withdraw it entirely. Removing is not hiding (W09)."""
    from app.models.promotions import FeatureRequest

    request = db.get(FeatureRequest, shopify_product_id)
    if request is None:
        return False
    db.delete(request)
    db.flush()
    return True


def feature_request_for(db: Session, shopify_product_id: str) -> dict | None:
    """The request on one product, for the staff editor. Visible or not."""
    from app.models.promotions import FeatureRequest

    request = db.get(FeatureRequest, shopify_product_id)
    if request is None:
        return None
    return {
        "shopify_product_id": request.shopify_product_id,
        "message": request.message,
        "visible": request.visible,
        "updated_at": request.updated_at.isoformat() if request.updated_at else None,
    }


def eligible_requests(db: Session, affiliate_id: int) -> list[dict]:
    """The requests this model may actually see.

    **The intersection is computed on the server, every time** (W10). Filtering
    in the browser would still hand every request to every model through the
    API, and W10's audience is *received or processing for that product* —
    which changes as parcels move.

    Two consequences the rule states outright and this inherits for free:
    a failed-only model drops out, and a replacement entering processing puts
    her back. Nothing is stored, so nothing has to be re-run.

    An empty list means the section disappears. W11's `hasFeatured` bug was
    checking an array's length against a list that had not been filtered.
    """
    from app.models.promotions import FeatureRequest

    wardrobe = wardrobe_for(db, affiliate_id)
    held = {
        row["shopify_product_id"]
        for state in HOLDS
        for row in wardrobe[state]
        if row["shopify_product_id"]
    }
    if not held:
        return []

    rows = db.scalars(
        select(FeatureRequest)
        .where(FeatureRequest.visible.is_(True))
        .where(FeatureRequest.shopify_product_id.in_(held))
    )

    out = []
    for request in rows:
        product = db.get(Product, request.shopify_product_id)
        out.append(
            {
                "shopify_product_id": request.shopify_product_id,
                "message": request.message,
                "title": product.title if product else None,
                "image_url": product.image_url if product else None,
            }
        )
    return out
