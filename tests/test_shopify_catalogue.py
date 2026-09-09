"""The catalogue, and what was in each order.

Phase 03A. Fixtures are the **shape Shopify actually returns** - GIDs beside
legacy ids, money as decimal strings inside `shopMoney`, `nodes` connections -
because a normaliser tested against a tidier shape than the API produces is a
normaliser that passes here and fails on the shop.

Nothing in this file talks to Shopify. `sync_catalogue` takes a client, and the
fake below is one; the real one is covered by `test_shopify_client.py`.
"""

import pytest
from sqlalchemy import select, text

from app.models.catalogue import OrderLineItem, Product, ProductStatus, ProductVariant
from app.services.shopify.catalogue import (
    normalise_line_item,
    normalise_product,
    normalise_variants,
    sync_catalogue,
    sync_order_line_items,
    upsert_line_items,
    upsert_product,
)


def _product_node(
    product_id="8891234567890",
    title="Satin slip dress — black",
    status="ACTIVE",
    variants=(("46912345678901", "S", 1), ("46912345678902", "M", 2)),
    image="https://cdn.shopify.com/s/files/1/slip-black.jpg",
):
    return {
        "id": f"gid://shopify/Product/{product_id}",
        "legacyResourceId": product_id,
        "title": title,
        "handle": "satin-slip-dress-black",
        "status": status,
        "updatedAt": "2026-09-01T10:00:00Z",
        "featuredMedia": (
            {"image": {"url": image, "altText": "Black satin slip"}} if image else None
        ),
        "variants": {
            "nodes": [
                {
                    "id": f"gid://shopify/ProductVariant/{vid}",
                    "legacyResourceId": vid,
                    "title": vtitle,
                    "sku": f"SLIP-BLK-{vtitle}",
                    "position": pos,
                }
                for vid, vtitle, pos in variants
            ]
        },
    }


def _line_node(
    line_id="14412345678901",
    title="Satin slip dress — black",
    variant_title="M",
    quantity=1,
    discounted="1200.00",
    original="1500.00",
    product_id="8891234567890",
    variant_id="46912345678902",
):
    return {
        "id": f"gid://shopify/LineItem/{line_id}",
        "legacyResourceId": line_id,
        "title": title,
        "sku": "SLIP-BLK-M",
        "quantity": quantity,
        "variantTitle": variant_title,
        "product": (
            {
                "id": f"gid://shopify/Product/{product_id}",
                "legacyResourceId": product_id,
            }
            if product_id
            else None
        ),
        "variant": (
            {
                "id": f"gid://shopify/ProductVariant/{variant_id}",
                "legacyResourceId": variant_id,
            }
            if variant_id
            else None
        ),
        "discountedTotalSet": {
            "shopMoney": {"amount": discounted, "currencyCode": "EGP"}
        },
        "originalTotalSet": {"shopMoney": {"amount": original, "currencyCode": "EGP"}},
    }


class FakeClient:
    """Returns pages in order and records what it was asked.

    `require_scope` succeeds unless told otherwise, because the interesting
    case is the one where it does not - see the scope tests.
    """

    def __init__(self, pages=None, order=None, missing_scope=False):
        self.pages = list(pages or [])
        self.order = order
        self.missing_scope = missing_scope
        self.calls = []
        self.scopes_required = []

    def require_scope(self, scope):
        self.scopes_required.append(scope)
        if self.missing_scope:
            from app.services.shopify.client import ShopifyMissingScope

            raise ShopifyMissingScope(f"missing {scope}")

    def execute(self, document, variables=None):
        self.calls.append((document, variables))
        if self.order is not None:
            return {"order": self.order}
        if not self.pages:
            return {"products": {"nodes": [], "pageInfo": {"hasNextPage": False}}}
        return {"products": self.pages.pop(0)}


def _order_row(db, order_id="1001", month="2026-08"):
    db.execute(
        text(
            "INSERT INTO order_index (shopify_order_id, order_number, placed_at,"
            " business_month, discount_codes, subtotal_piastres, total_piastres,"
            " shipping_piastres, tax_piastres, currency)"
            " VALUES (:i, :n, now(), :m, ARRAY['NOUR10'], 0, 0, 0, 0, 'EGP')"
        ),
        {"i": order_id, "n": f"#{order_id}", "m": month},
    )
    db.flush()
    return order_id


# ── Normalising ────────────────────────────────────────────────────────────


def test_a_product_keeps_its_numeric_id_and_its_gid(db):
    """Both, because the REST-shaped id is what joins and the GID is what
    GraphQL speaks. Rebuilding one from the other by string surgery is how an
    API version change breaks a join quietly."""
    values = normalise_product(_product_node())

    assert values["shopify_product_id"] == "8891234567890"
    assert values["shopify_product_gid"] == "gid://shopify/Product/8891234567890"


def test_a_status_is_lowercased_to_match_the_column(db):
    assert normalise_product(_product_node(status="ARCHIVED"))["status"] == (
        ProductStatus.ARCHIVED
    )


def test_an_unrecognised_status_becomes_a_draft(db):
    """Shopify has three and the column checks for three. A fourth is treated
    as the status that shows nowhere by default, which is the safe direction
    for a value nobody anticipated."""
    assert normalise_product(_product_node(status="SOMETHING_NEW"))["status"] == (
        ProductStatus.DRAFT
    )


def test_a_product_with_no_id_is_skipped_rather_than_raising(db):
    """One malformed product in a page of a hundred should cost that product,
    not the page."""
    assert normalise_product({"title": "No id at all"}) is None


def test_a_product_with_no_image_is_not_an_error(db):
    values = normalise_product(_product_node(image=None))

    assert values["image_url"] is None
    assert values["title"]


def test_a_variant_is_the_size(db):
    node = _product_node()
    rows = normalise_variants(node, "8891234567890")

    assert [row["title"] for row in rows] == ["S", "M"]
    assert rows[0]["shopify_product_id"] == "8891234567890"


# ── Line items ─────────────────────────────────────────────────────────────


def test_money_arrives_as_integer_piastres(db):
    values = normalise_line_item(_line_node(), "1001")

    assert values["discounted_total_piastres"] == 120_000
    assert values["original_total_piastres"] == 150_000


def test_a_line_keeps_its_own_title_so_a_rename_cannot_rewrite_history(db):
    """W01. A product renamed in March must not change what she was sent in
    January, so the line carries its own copy rather than only a join."""
    values = normalise_line_item(_line_node(title="Old name"), "1001")

    assert values["title"] == "Old name"
    assert values["variant_title"] == "M"


def test_a_deleted_product_leaves_the_line_intact(db):
    """Shopify drops the product from the payload. The line is still a real
    thing that was sent to a real person."""
    values = normalise_line_item(
        _line_node(product_id=None, variant_id=None), "1001"
    )

    assert values["shopify_product_id"] is None
    assert values["shopify_variant_id"] is None
    assert values["title"] == "Satin slip dress — black"


def test_a_line_with_no_original_reports_no_discount_rather_than_free(db):
    """Falling back to the discounted value says "nothing was taken off",
    which is true. Zero would say "this was free", which is not."""
    values = normalise_line_item(_line_node(original=None), "1001")

    assert values["original_total_piastres"] == values["discounted_total_piastres"]


def test_a_zero_quantity_line_is_skipped(db):
    assert normalise_line_item(_line_node(quantity=0), "1001") is None


# ── Writing, twice ─────────────────────────────────────────────────────────


def test_syncing_the_same_product_twice_writes_one_row(db):
    """A lease expires and hands the same job to a second worker."""
    node = _product_node()
    values = normalise_product(node)
    variants = normalise_variants(node, values["shopify_product_id"])

    upsert_product(db, values, variants)
    upsert_product(db, values, variants)

    assert len(list(db.scalars(select(Product)))) == 1
    assert len(list(db.scalars(select(ProductVariant)))) == 2


def test_a_withdrawn_variant_stops_being_listed(db):
    """A size no longer sold should not appear in a size picker. The evidence
    that somebody received it lives on the line item, not here."""
    node = _product_node()
    values = normalise_product(node)
    upsert_product(db, values, normalise_variants(node, values["shopify_product_id"]))

    smaller = _product_node(variants=(("46912345678901", "S", 1),))
    upsert_product(
        db, normalise_product(smaller), normalise_variants(smaller, "8891234567890")
    )

    assert [v.title for v in db.scalars(select(ProductVariant))] == ["S"]


def test_a_renamed_product_updates_in_place(db):
    node = _product_node()
    upsert_product(db, normalise_product(node), [])

    renamed = _product_node(title="Satin slip dress — noir")
    upsert_product(db, normalise_product(renamed), [])

    rows = list(db.scalars(select(Product)))
    assert len(rows) == 1
    assert rows[0].title == "Satin slip dress — noir"


def test_line_items_are_replaced_not_merged(db):
    """An order edited in Shopify to remove a line must not keep it here."""
    order_id = _order_row(db)
    first = [
        normalise_line_item(_line_node(line_id="1"), order_id),
        normalise_line_item(_line_node(line_id="2"), order_id),
    ]
    upsert_line_items(db, order_id, first)

    upsert_line_items(db, order_id, [normalise_line_item(_line_node(line_id="1"), order_id)])

    assert [row.shopify_line_item_id for row in db.scalars(select(OrderLineItem))] == [
        "1"
    ]


def test_replacing_one_orders_lines_leaves_anothers_alone(db):
    a = _order_row(db, "1001")
    b = _order_row(db, "1002")
    upsert_line_items(db, a, [normalise_line_item(_line_node(line_id="1"), a)])
    upsert_line_items(db, b, [normalise_line_item(_line_node(line_id="2"), b)])

    upsert_line_items(db, a, [])

    assert [row.shopify_order_id for row in db.scalars(select(OrderLineItem))] == [b]


# ── Walking the catalogue ──────────────────────────────────────────────────


def test_the_walk_follows_every_page(db):
    client = FakeClient(
        pages=[
            {
                "nodes": [_product_node(product_id="1")],
                "pageInfo": {"hasNextPage": True, "endCursor": "a"},
            },
            {
                "nodes": [_product_node(product_id="2")],
                "pageInfo": {"hasNextPage": False, "endCursor": "b"},
            },
        ]
    )

    result = sync_catalogue(db, client)

    assert result["products"] == 2
    assert result["pages"] == 2
    assert len(list(db.scalars(select(Product)))) == 2


def test_a_cursor_that_does_not_advance_stops_the_walk(db):
    """It would otherwise loop until the rate limiter noticed. Stopping is the
    honest outcome, and the counts say how far it got."""
    stuck = {
        "nodes": [_product_node(product_id="1")],
        "pageInfo": {"hasNextPage": True, "endCursor": None},
    }
    client = FakeClient(pages=[stuck, stuck, stuck])

    result = sync_catalogue(db, client)

    assert result["pages"] == 1


def test_a_malformed_product_is_counted_rather_than_swallowed(db):
    client = FakeClient(
        pages=[
            {
                "nodes": [{"title": "No id"}, _product_node(product_id="7")],
                "pageInfo": {"hasNextPage": False},
            }
        ]
    )

    result = sync_catalogue(db, client)

    assert result["products"] == 1
    assert result["skipped"] == 1


def test_the_walk_refuses_early_without_the_scope(db):
    """Without this the first page returns an access error and the walk reports
    "0 products", which is indistinguishable from an empty shop."""
    from app.services.shopify.client import ShopifyMissingScope

    client = FakeClient(missing_scope=True)

    with pytest.raises(ShopifyMissingScope):
        sync_catalogue(db, client)


def test_reading_an_orders_lines_says_when_it_truncated(db):
    """An order with more than a hundred lines is not something HBA ships, but
    silently keeping the first hundred would make a wardrobe wrong invisibly."""
    order_id = _order_row(db)
    client = FakeClient(
        order={
            "id": f"gid://shopify/Order/{order_id}",
            "legacyResourceId": order_id,
            "lineItems": {
                "nodes": [_line_node()],
                "pageInfo": {"hasNextPage": True, "endCursor": "x"},
            },
        }
    )

    result = sync_order_line_items(db, client, f"gid://shopify/Order/{order_id}")

    assert result["lines"] == 1
    assert result["truncated"] is True


# ── The boundary that must not move ────────────────────────────────────────


def test_no_catalogue_table_holds_customer_data(db):
    """§10.2. The cheapest way never to leak a field is never to store it.

    Structural, like the order-index test it mirrors: it reads the columns
    rather than the rows, so it fails when somebody *adds* a place to put a
    phone number rather than when somebody fills one in.
    """
    forbidden = {
        "email",
        "phone",
        "customer_name",
        "customer_id",
        "first_name",
        "last_name",
        "address1",
        "address2",
        "shipping_address",
        "shipping_phone",
        "city",
        "zip",
    }

    for table in ("product", "product_variant", "order_line_item"):
        columns = {
            row[0]
            for row in db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_name = :t"
                ),
                {"t": table},
            )
        }
        assert not (columns & forbidden), (
            f"{table} has a column for customer data: {sorted(columns & forbidden)}. "
            "The recipient's phone belongs to the restricted matching path, not here."
        )
