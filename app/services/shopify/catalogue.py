"""Reading the catalogue, and what was in an order.

Two ingestion paths, kept apart from commission's on purpose.

## Why this is not bolted onto `sync.py`

03A's prompt: *new recipient field denial cannot break existing commission
sync.* GraphQL rejects an **entire document** when one field is wrong, and
`ORDER_FIELDS` runs on every webhook. Adding an unproven product selection to it
would risk stopping order ingestion outright in order to gain a wardrobe.

So these are separate documents, separate functions and separate jobs. If
Shopify refuses a product field tomorrow, the catalogue goes stale and orders
keep indexing - which is the failure worth having.

## Idempotent, because everything here runs twice

A lease expires and hands the same job to a second worker; a sweep overlaps a
webhook; somebody re-runs an import. Every write below is an upsert keyed by
Shopify's own id, so running twice is indistinguishable from running once.

## Freshness is recorded, not implied

`synced_at` is when HBA last *heard from* Shopify about a row, which is a
different fact from when Shopify last changed it (`updated_at_shopify`). A
screen that shows a price needs the first to say "as of" honestly; a sync that
decides what to re-fetch needs the second.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.signals import Anomaly, report
from app.services.jobs import JobKind, PermanentFailure
from app.worker import register_handler
from app.models.catalogue import (
    VALID_PRODUCT_STATUSES,
    OrderLineItem,
    Product,
    ProductStatus,
    ProductVariant,
)
from app.services.shopify.normalise import money_to_piastres

#: Shopify's page size for products. A hundred is its documented maximum for a
#: connection and costs one query per hundred products rather than per product.
PAGE_SIZE = 100

#: A guard on the walk, not a limit on the shop. A cursor that stops advancing
#: is a bug that would otherwise loop until the rate limiter noticed.
MAX_PAGES = 200


def _numeric_id(node: dict, gid_key: str = "id") -> str | None:
    """Shopify's numeric id, from `legacyResourceId` or the tail of the GID.

    `legacyResourceId` is asked for and is the right answer. The fallback
    exists because a nested selection sometimes carries only `id`, and
    reconstructing the number from the GID's last segment is well-defined -
    `gid://shopify/Product/12345` - while leaving the row unkeyed is not.
    """
    legacy = node.get("legacyResourceId")
    if legacy:
        return str(legacy)
    gid = node.get(gid_key)
    if not gid:
        return None
    tail = str(gid).rstrip("/").split("/")[-1]
    return tail or None


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def normalise_product(node: dict) -> dict | None:
    """Map a Shopify product node onto `product` columns.

    Returns `None` for a node with no usable id rather than raising. One
    malformed product in a page of a hundred should cost that product, not the
    page - and the caller counts what it skipped so the gap is visible.
    """
    product_id = _numeric_id(node)
    if not product_id:
        return None

    status = str(node.get("status") or "").strip().lower()
    if status not in VALID_PRODUCT_STATUSES:
        # Shopify has three and the column checks for those three. An
        # unrecognised one is treated as a draft: it is the status that shows
        # nowhere by default, which is the safe direction for a value nobody
        # anticipated.
        status = ProductStatus.DRAFT

    image = ((node.get("featuredMedia") or {}).get("image")) or {}

    return {
        "shopify_product_id": product_id,
        "shopify_product_gid": node.get("id"),
        "title": str(node.get("title") or "").strip() or "Untitled product",
        "handle": node.get("handle"),
        "status": status,
        "image_url": image.get("url"),
        "image_alt": image.get("altText"),
        "updated_at_shopify": _timestamp(node.get("updatedAt")),
    }


def normalise_variants(node: dict, product_id: str) -> list[dict]:
    """Every variant on one product node. W01: the variant is the size."""
    rows = []
    for variant in ((node.get("variants") or {}).get("nodes")) or []:
        variant_id = _numeric_id(variant)
        if not variant_id:
            continue
        rows.append(
            {
                "shopify_variant_id": variant_id,
                "shopify_variant_gid": variant.get("id"),
                "shopify_product_id": product_id,
                "title": str(variant.get("title") or "").strip() or "One size",
                "sku": variant.get("sku"),
                "position": variant.get("position"),
            }
        )
    return rows


def normalise_line_item(node: dict, order_id: str) -> dict | None:
    """Map one Shopify line item onto `order_line_item` columns.

    The title and variant title are copied **as they are now**, which is the
    point: W01 asks that a product renamed or archived later must not rewrite
    what a model was sent. The ids come along so a live product can still be
    joined for its picture, and both are nullable because a deleted product
    takes its id out of the payload while the line stays real.
    """
    line_id = _numeric_id(node)
    if not line_id:
        return None

    quantity = int(node.get("quantity") or 0)
    if quantity <= 0:
        # The column refuses it, and a zero-quantity line is not a thing that
        # was sent to anybody. Skipped rather than stored as evidence of
        # nothing.
        return None

    discounted = money_to_piastres(
        (((node.get("discountedTotalSet") or {}).get("shopMoney")) or {}).get("amount")
    )
    original = money_to_piastres(
        (((node.get("originalTotalSet") or {}).get("shopMoney")) or {}).get("amount")
    )

    product = node.get("product") or {}
    variant = node.get("variant") or {}

    return {
        "shopify_line_item_id": line_id,
        "shopify_order_id": order_id,
        "shopify_product_id": _numeric_id(product) if product else None,
        "shopify_variant_id": _numeric_id(variant) if variant else None,
        "title": str(node.get("title") or "").strip() or "Untitled item",
        "variant_title": node.get("variantTitle"),
        "sku": node.get("sku"),
        "quantity": quantity,
        "discounted_total_piastres": discounted,
        # An order placed before discounts existed reports no original. Falling
        # back to the discounted value says "no discount applied", which is
        # true, rather than "this was free", which is not.
        "original_total_piastres": original or discounted,
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def upsert_product(db: Session, values: dict, variants: list[dict]) -> Product:
    """One product and its variants, written idempotently.

    Variants that Shopify no longer lists are **deleted**, not left behind: a
    size withdrawn from sale should stop appearing in a size picker, and the
    evidence that somebody once received it lives on the line item rather than
    here.
    """
    product = db.get(Product, values["shopify_product_id"])
    if product is None:
        product = Product(**values, synced_at=_now())
        db.add(product)
    else:
        for key, value in values.items():
            setattr(product, key, value)
        product.synced_at = _now()

    db.flush()

    seen = set()
    for row in variants:
        seen.add(row["shopify_variant_id"])
        existing = db.get(ProductVariant, row["shopify_variant_id"])
        if existing is None:
            db.add(ProductVariant(**row, synced_at=_now()))
        else:
            for key, value in row.items():
                setattr(existing, key, value)
            existing.synced_at = _now()

    stale = db.scalars(
        select(ProductVariant).where(
            ProductVariant.shopify_product_id == values["shopify_product_id"]
        )
    )
    for variant in stale:
        if variant.shopify_variant_id not in seen:
            db.delete(variant)

    db.flush()
    return product


def upsert_line_items(db: Session, order_id: str, rows: list[dict]) -> int:
    """Every line of one order, replacing what was there.

    Replacing rather than merging, because the set is the fact: an order edited
    in Shopify to remove a line must not keep that line here, and a line item
    id is not reused. Bounded by the order, so this cannot touch another's.
    """
    existing = db.scalars(
        select(OrderLineItem).where(OrderLineItem.shopify_order_id == order_id)
    )
    keep = {row["shopify_line_item_id"] for row in rows}
    for item in existing:
        if item.shopify_line_item_id not in keep:
            db.delete(item)

    for row in rows:
        found = db.get(OrderLineItem, row["shopify_line_item_id"])
        if found is None:
            db.add(OrderLineItem(**row, synced_at=_now()))
        else:
            for key, value in row.items():
                setattr(found, key, value)
            found.synced_at = _now()

    db.flush()
    return len(rows)


def sync_catalogue(db: Session, client, *, page_size: int = PAGE_SIZE) -> dict:
    """Walk the whole catalogue, one page at a time.

    Paginated because a shop is not a page. Durable because each page commits
    on its own: a walk that dies at page seven leaves six pages of catalogue
    behind rather than nothing, and running it again is an upsert.

    Returns counts rather than rows. The caller is a job or a diagnostic route,
    and neither wants a thousand products in memory to report a number.
    """
    from app.services.shopify.queries import PRODUCTS_PAGE

    # **Refuse early, naming the scope.** Without this the first page comes
    # back as a GraphQL access error and the walk reports "0 products" - which
    # is indistinguishable from an empty shop, and is the version of this
    # failure somebody would spend an afternoon on.
    client.require_scope("read_products")

    products = 0
    variants = 0
    skipped = 0
    cursor = None
    pages = 0

    while pages < MAX_PAGES:
        pages += 1
        payload = client.execute(
            PRODUCTS_PAGE, {"first": page_size, "after": cursor}
        )
        block = ((payload or {}).get("products")) or {}
        for node in block.get("nodes") or []:
            values = normalise_product(node)
            if values is None:
                skipped += 1
                continue
            rows = normalise_variants(node, values["shopify_product_id"])
            upsert_product(db, values, rows)
            products += 1
            variants += len(rows)

        db.commit()

        info = block.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            break
        next_cursor = info.get("endCursor")
        if not next_cursor or next_cursor == cursor:
            # A cursor that does not advance would loop until the rate limiter
            # noticed. Stopping is the honest outcome, and the counts say how
            # far it got.
            break
        cursor = next_cursor

    return {
        "products": products,
        "variants": variants,
        "skipped": skipped,
        "pages": pages,
    }


def sync_order_line_items(db: Session, client, order_gid: str) -> dict:
    """What was in one order.

    Separate from the order's own sync, and deliberately so - see the module
    docstring. An order whose line items cannot be read is still an order whose
    commission is correct.
    """
    from app.services.shopify.queries import ORDER_LINE_ITEMS

    client.require_scope("read_products")
    payload = client.execute(ORDER_LINE_ITEMS, {"id": order_gid})
    order = ((payload or {}).get("order")) or {}
    order_id = _numeric_id(order)
    if not order_id:
        return {"order_id": None, "lines": 0, "truncated": False}

    block = (order.get("lineItems") or {})
    rows = []
    for node in block.get("nodes") or []:
        values = normalise_line_item(node, order_id)
        if values is not None:
            rows.append(values)

    upsert_line_items(db, order_id, rows)

    return {
        "order_id": order_id,
        "lines": len(rows),
        # **Said rather than hidden.** An order with more than a hundred lines
        # is not something HBA ships, but silently keeping the first hundred
        # would make a wardrobe wrong in a way nothing could see.
        "truncated": bool((block.get("pageInfo") or {}).get("hasNextPage")),
    }


# ── The job ──────────────────────────────────────────────────────────────────


@register_handler(JobKind.SYNC_CATALOGUE)
def _handle_sync_catalogue(db: Session, payload: dict) -> None:
    """Walk the catalogue in the background.

    Its own job kind, not a step inside the order sync. A product field Shopify
    refuses must never be able to stop orders indexing, and two kinds is what
    makes that structural rather than careful.

    A missing scope or credential is permanent: waiting does not grant a scope,
    and retrying four times only delays the message that says so.
    """
    from app.services.shopify.sync import PERMANENT, build_client

    try:
        client = build_client()
        result = sync_catalogue(db, client)
    except PERMANENT as exc:
        raise PermanentFailure(str(exc)) from exc

    if result["skipped"]:
        report(
            Anomaly.CATALOGUE_PRODUCT_SKIPPED,
            skipped=result["skipped"],
            products=result["products"],
        )


def catalogue_state(db: Session) -> dict:
    """What the catalogue looks like, for the operations panel.

    **Freshness is a fact, not an impression.** `synced_at` is when HBA last
    heard from Shopify, which a screen needs in order to say "as of" rather
    than implying "now" - a catalogue nobody has synced for a fortnight looks
    identical to a fresh one until it says otherwise.
    """
    total = db.scalar(select(func.count()).select_from(Product)) or 0
    active = (
        db.scalar(
            select(func.count())
            .select_from(Product)
            .where(Product.status == ProductStatus.ACTIVE)
        )
        or 0
    )
    newest = db.scalar(select(func.max(Product.synced_at)))
    variants = db.scalar(select(func.count()).select_from(ProductVariant)) or 0
    lines = db.scalar(select(func.count()).select_from(OrderLineItem)) or 0

    return {
        "products": total,
        "active_products": active,
        "variants": variants,
        "line_items": lines,
        "last_synced_at": newest.isoformat() if newest else None,
    }
