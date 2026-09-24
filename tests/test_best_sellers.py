"""*Your best sellers* counts what the money counts. F02, F04, ADR 0040.

The approved portal's line is *"Sales through HBA15 · all time · delivered and
pending"*, and it is the platform's own rule: a pending order is a sale, a
failed delivery is not, and nothing after delivery takes a sale back.

Every order here goes in through `upsert_order_index`, the path a webhook, a
sweep and an import all share, so each state is the one attribution actually
reaches - and a transition is the same order arriving again, not a second row
written by hand. Line items go in through `upsert_line_items`, the writer the
Shopify read uses, for the same reason.
"""

from datetime import datetime, timezone

from app.core.passwords import hash_password
from app.models.attributed_orders import AttributedOrder, CommissionState
from app.models.identity import UserAccount
from app.services.affiliates import create_affiliate
from app.services.codes import register_code
from app.services.performance import best_sellers_for
from app.services.shopify.catalogue import upsert_line_items
from app.services.shopify.fulfilment import DELIVERED, FAILED, IN_FLIGHT
from app.services.shopify.normalise import upsert_order_index


def _model(db, name="Nour", code="NOUR10"):
    account = UserAccount(
        email=f"{name.lower()}@example.com",
        password_hash=hash_password("quiet-harbour-lantern"),
        status="active",
        display_name=name,
    )
    db.add(account)
    db.flush()
    affiliate = create_affiliate(db, user_account_id=account.id, name=name)
    register_code(db, affiliate, code, "2026-01")
    return affiliate


def _arrives(db, order_id, total, *, code="NOUR10", **facts):
    """One Shopify order, as ingestion sees it. Shipping and tax are zero so
    the order's total is the sum of its lines and every figure below can be
    checked by eye."""
    upsert_order_index(
        db,
        {
            "shopify_order_id": order_id,
            "order_number": f"#{order_id}",
            "placed_at": datetime(2026, 8, 10, 12, tzinfo=timezone.utc),
            "business_month": "2026-08",
            "discount_codes": [code],
            "subtotal_piastres": total,
            "total_piastres": total,
            "shipping_piastres": 0,
            "tax_piastres": 0,
            "currency": "EGP",
            **facts,
        },
    )


def _lines(db, order_id, *lines):
    """`(product, quantity, paid)` per line - paid being after her discount."""
    upsert_line_items(
        db,
        order_id,
        [
            {
                "shopify_line_item_id": f"{order_id}-{product}",
                "shopify_order_id": order_id,
                "shopify_product_id": product,
                "title": product.title(),
                "quantity": quantity,
                "discounted_total_piastres": paid,
                "original_total_piastres": paid,
            }
            for product, quantity, paid in lines
        ],
    )


def _state(db, order_id):
    db.expire_all()
    return db.get(AttributedOrder, order_id).commission_state


def _board(db, affiliate):
    return [
        (row.shopify_product_id, row.quantity, row.sales_piastres)
        for row in best_sellers_for(db, affiliate.id)
    ]


DELIVERED_ON = {
    "delivery_state": DELIVERED,
    "delivered_at": datetime(2026, 8, 14, 9, tzinfo=timezone.utc),
}


def test_a_pending_order_sells_and_can_take_first_place(db):
    """EGP 4,500 still travelling outranks EGP 3,000 delivered.

    Delivered-only, this list would read Dress, Scarf. The coat is the reason
    it does not: counted the way she is paid, it is her best seller. The bag
    failed and sells nothing, though it is the largest line of all.
    """
    nour = _model(db)
    _arrives(db, "9001", 400_000, **DELIVERED_ON)
    _lines(db, "9001", ("dress", 1, 300_000), ("scarf", 2, 100_000))
    _arrives(db, "9002", 450_000, delivery_state=IN_FLIGHT)
    _lines(db, "9002", ("coat", 1, 450_000))
    _arrives(db, "9003", 900_000, delivery_state=FAILED)
    _lines(db, "9003", ("bag", 1, 900_000))

    assert _state(db, "9002") == CommissionState.PENDING
    assert _state(db, "9003") == CommissionState.VOID
    assert _board(db, nour) == [
        ("coat", 1, 450_000),
        ("dress", 1, 300_000),
        ("scarf", 2, 100_000),
    ]


def test_an_order_shopify_has_said_nothing_about_is_pending_and_sells(db):
    """No delivery state at all is *anything in between*, not a failure."""
    nour = _model(db)
    _arrives(db, "9004", 120_000)
    _lines(db, "9004", ("belt", 3, 120_000))

    assert _state(db, "9004") == CommissionState.PENDING
    assert _board(db, nour) == [("belt", 3, 120_000)]


def test_pending_then_delivered_is_one_sale_not_two(db):
    """The same order arriving twice, and its lines read twice, is still one
    order: EGP 2,000 and two pieces, before delivery and after it."""
    nour = _model(db)
    _arrives(db, "9005", 200_000, delivery_state=IN_FLIGHT)
    _lines(db, "9005", ("dress", 2, 200_000))

    assert _board(db, nour) == [("dress", 2, 200_000)]

    _arrives(db, "9005", 200_000, **DELIVERED_ON)
    _lines(db, "9005", ("dress", 2, 200_000))

    assert _state(db, "9005") == CommissionState.EARNED
    assert _board(db, nour) == [("dress", 2, 200_000)]


def test_pending_then_failed_leaves_the_list(db):
    """Counted until it resolves, and a failure resolves it out (D03)."""
    nour = _model(db)
    _arrives(db, "9006", 250_000, delivery_state=IN_FLIGHT)
    _lines(db, "9006", ("coat", 1, 250_000))
    _arrives(db, "9007", 80_000, **DELIVERED_ON)
    _lines(db, "9007", ("scarf", 1, 80_000))

    assert _board(db, nour) == [("coat", 1, 250_000), ("scarf", 1, 80_000)]

    _arrives(db, "9006", 250_000, delivery_state=FAILED)

    assert _state(db, "9006") == CommissionState.VOID
    assert _board(db, nour) == [("scarf", 1, 80_000)]


def test_a_refund_or_return_after_delivery_keeps_the_sale(db):
    """F04 and ADR 0025: delivery is the end of the story.

    The order comes back refunded, cancelled and returned, with its whole
    EGP 3,000 recorded as money going back. It stays earned, and the dress
    stays on her list at the full EGP 3,000 the customer paid for it.
    """
    nour = _model(db)
    _arrives(db, "9008", 300_000, **DELIVERED_ON)
    _lines(db, "9008", ("dress", 1, 300_000))

    _arrives(
        db,
        "9008",
        300_000,
        **DELIVERED_ON,
        financial_status="refunded",
        cancelled_at=datetime(2026, 8, 20, 9, tzinfo=timezone.utc),
        return_status="returned",
        refunded_merchandise_piastres=300_000,
    )
    _lines(db, "9008", ("dress", 1, 300_000))

    assert _state(db, "9008") == CommissionState.EARNED
    assert _board(db, nour) == [("dress", 1, 300_000)]


def test_another_models_sales_never_reach_her_list(db):
    nour = _model(db)
    _model(db, name="Sara", code="SARA10")
    _arrives(db, "9009", 100_000, **DELIVERED_ON)
    _lines(db, "9009", ("dress", 1, 100_000))
    _arrives(db, "9010", 700_000, code="SARA10", delivery_state=IN_FLIGHT)
    _lines(db, "9010", ("coat", 1, 700_000))

    assert _board(db, nour) == [("dress", 1, 100_000)]
