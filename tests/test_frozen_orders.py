"""ADR 0051: a return freezes the order, and a cancelled fulfilment carries nothing.

Every shape here was read from HBA's real shop on 28 September, in a read-only
audit of the 1,114 orders staging held as in flight. The order numbers in the
test names are the ones the owner checked by hand:

- **#22369** - fulfilled, cancelled, fulfilled again, delivered. In flight for
  five months, because the cancelled fulfilment counted as still travelling.
- **#22408** - a cancelled fulfilment, then a failed one. Never delivered.
- **#29499 / #29475 / #29457** - delivered, then an E-stebdal exchange: a new
  fulfilment created after delivery, marked fulfilled by hand, never reported
  on by any courier.
"""

import json
from datetime import datetime, timezone

from sqlalchemy import text

from app.core.passwords import hash_password
from app.modules.affiliates.models.attributed_orders import AttributedOrder, CommissionState
from app.shared.models.identity import UserAccount
from app.modules.affiliates.services.affiliates import create_affiliate
from app.modules.affiliates.services.codes import register_code
from app.modules.affiliates.services.commission.base import base_for_order
from app.shared.services.shopify.catalogue import frozen_lines
from app.shared.services.shopify.fulfilment import (
    DELIVERED,
    FAILED,
    IN_FLIGHT,
    derive_delivery,
    paid_by_delivery,
    summarise_fulfilments,
)
from app.shared.services.shopify.normalise import normalise_order, upsert_order_index
from app.shared.services.stale import (
    COURIER_SILENT,
    NO_TRACKING,
    OTHER_COURIER,
    stale_fulfilments,
)


def _f(display, *, created, delivered=None, status="SUCCESS", company="Bosta", number="1", lines=()):
    return {
        "status": status,
        "displayStatus": display,
        "createdAt": created,
        "deliveredAt": delivered,
        "trackingInfo": [{"company": company, "number": number}] if company or number else [],
        "fulfillmentLineItems": {
            "nodes": [{"lineItem": {"id": f"gid://shopify/LineItem/{line}"}} for line in lines]
        },
    }


def _pay(amount, at, kind="SALE", status="SUCCESS"):
    return {
        "kind": kind,
        "status": status,
        "processedAt": at,
        "amountSet": {"shopMoney": {"amount": amount, "currencyCode": "EGP"}},
    }


# #22369's timeline, as the owner pasted it.
CANCELLED_THEN_RESENT = [
    _f("CANCELED", status="CANCELLED", created="2026-04-20T10:31:00Z"),
    _f("DELIVERED", created="2026-04-20T15:16:00Z", delivered="2026-04-21T13:08:00Z"),
]

# #29499's: delivered 29 August, exchange shipped 3 September.
DELIVERED_THEN_EXCHANGED = [
    _f("DELIVERED", created="2026-08-27T12:55:00Z", delivered="2026-08-29T16:59:00Z", lines=("1",)),
    _f("FULFILLED", created="2026-09-03T12:40:00Z", company="Bosta", lines=("2",)),
]


# ── Rule 2: a cancelled fulfilment carries nothing ─────────────────────────────


def test_22369_a_cancelled_then_resent_order_is_delivered():
    state, delivered_at, raw = derive_delivery(CANCELLED_THEN_RESENT)
    assert state == DELIVERED
    assert delivered_at == datetime(2026, 4, 21, 13, 8, tzinfo=timezone.utc)
    assert raw == "DELIVERED"


def test_22408_a_cancelled_then_failed_order_is_failed():
    state, _, _ = derive_delivery(
        [
            _f("CANCELED", status="CANCELLED", created="2026-04-20T09:00:00Z"),
            _f("NOT_DELIVERED", created="2026-04-20T12:00:00Z"),
        ]
    )
    assert state == FAILED


def test_an_order_whose_only_fulfilments_were_cancelled_was_not_shipped():
    """Scenario 2: all sixty were cancelled orders, already void in commission."""
    state, delivered_at, raw = derive_delivery(
        [_f("CANCELED", status="CANCELLED", created="2026-06-20T09:00:00Z")]
    )
    assert (state, delivered_at, raw) == (None, None, "CANCELED")


def test_either_spelling_of_cancelled_is_enough():
    only_status = [_f("FULFILLED", status="CANCELLED", created="2026-04-20T09:00:00Z")]
    only_display = [_f("CANCELED", status="SUCCESS", created="2026-04-20T09:00:00Z")]
    assert derive_delivery(only_status)[0] is None
    assert derive_delivery(only_display)[0] is None


# ── Rule 1: a return freezes the order ─────────────────────────────────────────


def test_29499_an_exchange_after_delivery_leaves_the_order_delivered():
    state, delivered_at, _ = derive_delivery(
        DELIVERED_THEN_EXCHANGED, return_status="RETURNED"
    )
    assert state == DELIVERED
    # The frozen delivery, not the exchange's.
    assert delivered_at == datetime(2026, 8, 29, 16, 59, tzinfo=timezone.utc)


def test_an_open_return_freezes_it_too():
    assert derive_delivery(DELIVERED_THEN_EXCHANGED, return_status="IN_PROGRESS")[0] == DELIVERED


def test_without_a_return_a_late_fulfilment_still_counts():
    """The gate. The audit found no late fulfilment on an order without a
    return, so a genuine late split shipment is never hidden by this rule."""
    assert derive_delivery(DELIVERED_THEN_EXCHANGED, return_status="NO_RETURN")[0] == IN_FLIGHT
    assert derive_delivery(DELIVERED_THEN_EXCHANGED)[0] == IN_FLIGHT


def test_a_split_shipment_created_before_delivery_still_waits():
    """#19177's shape: two fulfilments made before anything arrived, one of
    them never reported on. Not frozen away - it was part of the order."""
    state, _, _ = derive_delivery(
        [
            _f("FULFILLED", created="2026-03-02T09:00:00Z"),
            _f("DELIVERED", created="2026-03-02T10:00:00Z", delivered="2026-03-04T10:00:00Z"),
        ],
        return_status="RETURNED",
    )
    assert state == IN_FLIGHT


def test_cancelled_then_resent_then_exchanged_is_delivered():
    """#22318's shape: both rules at once."""
    rows = CANCELLED_THEN_RESENT + [
        _f("FULFILLED", created="2026-04-25T10:00:00Z"),
    ]
    assert derive_delivery(rows, return_status="RETURNED")[0] == DELIVERED


def test_an_exchange_item_that_failed_does_not_undo_the_delivery():
    """#24467: the replacement's delivery failed. The order was delivered."""
    rows = [
        DELIVERED_THEN_EXCHANGED[0],
        _f("NOT_DELIVERED", created="2026-09-03T12:40:00Z"),
    ]
    assert derive_delivery(rows, return_status="RETURNED")[0] == DELIVERED


# ── The money frozen with it ───────────────────────────────────────────────────


def test_paid_by_delivery_is_the_money_up_to_the_parcel_arriving():
    """#29457: E£654.10 cash on delivery, then E£640 more for the exchange."""
    delivered = datetime(2026, 8, 29, 20, 16, tzinfo=timezone.utc)
    paid = paid_by_delivery(
        [
            _pay("654.10", "2026-08-29T20:16:00Z"),
            _pay("640.00", "2026-08-30T10:36:00Z"),
        ],
        delivered,
    )
    assert paid == 65410


def test_a_refund_before_delivery_is_money_that_went_back():
    delivered = datetime(2026, 8, 29, 12, tzinfo=timezone.utc)
    paid = paid_by_delivery(
        [
            _pay("1000.00", "2026-08-20T12:00:00Z"),
            _pay("250.00", "2026-08-22T12:00:00Z", kind="REFUND"),
            _pay("99.00", "2026-08-23T12:00:00Z", status="FAILURE"),
        ],
        delivered,
    )
    assert paid == 75000


def test_a_payment_settled_a_few_hours_after_delivery_still_counts():
    delivered = datetime(2026, 8, 29, 10, tzinfo=timezone.utc)
    assert paid_by_delivery([_pay("100.00", "2026-08-29T21:00:00Z")], delivered) == 10000


def test_payments_never_read_are_not_zero():
    delivered = datetime(2026, 8, 29, 10, tzinfo=timezone.utc)
    assert paid_by_delivery(None, delivered) is None
    assert paid_by_delivery([_pay("100.00", "2026-08-29T10:00:00Z")], None) is None


def test_a_delivered_order_with_a_return_is_locked_at_the_cash_paid():
    """The stored figure is Shopify's total after the exchange edited it; the
    base is what she was paid on - the cash, less shipping."""
    decision = base_for_order(
        total_piastres=75500,
        shipping_piastres=11500,
        tax_piastres=0,
        delivered=True,
        stored_base_piastres=64000,
        return_activity=True,
        paid_by_delivery_piastres=65410,
    )
    assert decision.piastres == 53910
    assert decision.is_final


def test_without_a_return_the_old_rule_holds():
    decision = base_for_order(
        total_piastres=75500,
        shipping_piastres=11500,
        tax_piastres=0,
        delivered=True,
        stored_base_piastres=64000,
        return_activity=False,
        paid_by_delivery_piastres=65410,
    )
    assert decision.piastres == 64000


def test_before_delivery_the_base_follows_the_order():
    decision = base_for_order(
        total_piastres=75500,
        shipping_piastres=11500,
        tax_piastres=0,
        delivered=False,
        return_activity=True,
        paid_by_delivery_piastres=65410,
    )
    assert decision.piastres == 64000
    assert not decision.is_final


# ── Through the real path: normalise, index, attribute ─────────────────────────


def _node(order_id="29457", **extra):
    return {
        "id": f"gid://shopify/Order/{order_id}",
        "legacyResourceId": order_id,
        "name": f"#{order_id}",
        "createdAt": "2026-08-25T18:01:00Z",
        "updatedAt": "2026-09-07T19:03:00Z",
        "cancelledAt": None,
        "displayFinancialStatus": "PAID",
        "displayFulfillmentStatus": "FULFILLED",
        "discountCodes": ["NOUR10"],
        "currentSubtotalPriceSet": {"shopMoney": {"amount": "540.00", "currencyCode": "EGP"}},
        # After the exchange: E£540 item + E£115 shipping + E£100 return fee.
        "currentTotalPriceSet": {"shopMoney": {"amount": "755.00", "currencyCode": "EGP"}},
        "totalShippingPriceSet": {"shopMoney": {"amount": "115.00", "currencyCode": "EGP"}},
        "currentTotalTaxSet": {"shopMoney": {"amount": "0.00", "currencyCode": "EGP"}},
        "returnStatus": "RETURNED",
        "fulfillments": [
            _f("DELIVERED", created="2026-08-26T12:19:00Z", delivered="2026-08-29T20:16:00Z"),
            _f("FULFILLED", created="2026-08-31T16:48:00Z"),
        ],
        "transactions": [
            _pay("654.10", "2026-08-29T20:16:00Z"),
            _pay("640.00", "2026-08-30T10:36:00Z"),
        ],
        **extra,
    }


def test_normalising_29457_keeps_the_frozen_facts():
    values = normalise_order(_node())
    assert values["delivery_state"] == DELIVERED
    assert values["paid_by_delivery_piastres"] == 65410
    assert [row["display_status"] for row in values["fulfilments"]] == ["DELIVERED", "FULFILLED"]
    assert values["fulfilments"][0]["company"] == "Bosta"


def test_an_import_that_did_not_ask_for_payments_records_none():
    node = _node()
    del node["transactions"]
    assert normalise_order(node)["paid_by_delivery_piastres"] is None


def test_a_stuck_exchange_is_earned_at_the_cash_paid(db):
    """The 361: first seen after the exchange, stuck pending on a stored base
    read from the post-exchange totals. Re-read under ADR 0051 it is earned,
    and its base is the cash at delivery - not the stored figure."""
    account = UserAccount(
        email="nour@example.com",
        password_hash=hash_password("quiet-harbour-lantern"),
        status="active",
        display_name="Nour",
    )
    db.add(account)
    db.flush()
    affiliate = create_affiliate(db, user_account_id=account.id, name="Nour")
    register_code(db, affiliate, "NOUR10", "2026-01")

    # As it was stored before: the return not yet visible, so in flight, with
    # a base read from the current totals (E£755 - E£115 shipping).
    upsert_order_index(db, normalise_order(_node(returnStatus="NO_RETURN")))
    row = db.get(AttributedOrder, "29457")
    assert row.commission_state == CommissionState.PENDING
    assert row.commission_base_piastres == 64000

    upsert_order_index(db, normalise_order(_node()))
    db.refresh(row)
    assert row.commission_state == CommissionState.EARNED
    # E£654.10 paid by delivery, less E£115 shipping.
    assert row.commission_base_piastres == 53910


def test_a_bulk_reread_does_not_wipe_the_cash_figure(db):
    upsert_order_index(db, normalise_order(_node(discountCodes=[])))
    node = _node(discountCodes=[])
    del node["transactions"]
    order = upsert_order_index(db, normalise_order(node))
    assert order.paid_by_delivery_piastres == 65410


# ── The items frozen with it ───────────────────────────────────────────────────


def test_the_exchange_item_is_not_one_of_the_orders_products():
    assert frozen_lines(DELIVERED_THEN_EXCHANGED, "RETURNED") == {"1"}


def test_an_exchange_item_still_on_hold_is_not_one_either():
    """No fulfilment yet - E-stebdal holds it until the return arrives. The
    order's products are what the counting fulfilments carried, so a line on
    none of them is not one of them."""
    frozen = frozen_lines(DELIVERED_THEN_EXCHANGED[:1], "IN_PROGRESS")
    assert frozen == {"1"}
    assert "2" not in frozen


def test_an_order_without_a_return_is_not_frozen():
    assert frozen_lines(DELIVERED_THEN_EXCHANGED, "NO_RETURN") is None
    assert frozen_lines([_f("FULFILLED", created="2026-08-27T12:55:00Z")], "RETURNED") is None


# ── What is kept, and what stays on a person's list ───────────────────────────


def test_each_fulfilment_is_kept_without_its_tracking_number():
    summary = summarise_fulfilments(
        [_f("FULFILLED", created="2026-08-27T12:55:00Z", company="Aramex", number="998877")]
    )
    assert summary == [
        {
            "status": "SUCCESS",
            "display_status": "FULFILLED",
            "created_at": "2026-08-27T12:55:00Z",
            "delivered_at": None,
            "company": "Aramex",
            "tracked": True,
        }
    ]


def _stuck(db, order_id, fulfilments, placed="2026-07-01T10:00:00+00:00"):
    db.execute(
        text(
            "INSERT INTO order_index (shopify_order_id, order_number, placed_at,"
            " business_month, discount_codes, subtotal_piastres, total_piastres,"
            " shipping_piastres, tax_piastres, currency, delivery_state, fulfilments)"
            " VALUES (:i, :n, :p, '2026-07', ARRAY[]::text[], 0, 0, 0, 0, 'EGP',"
            " 'in_flight', CAST(:f AS jsonb))"
        ),
        {"i": order_id, "n": f"#{order_id}", "p": placed, "f": json.dumps(fulfilments)},
    )
    db.flush()


def _fact(display="FULFILLED", company=None, tracked=False):
    return {
        "status": "SUCCESS",
        "display_status": display,
        "created_at": "2026-07-01T12:00:00Z",
        "delivered_at": None,
        "company": company,
        "tracked": tracked,
    }


def test_the_staff_list_groups_orders_nobody_will_report_on(db):
    _stuck(db, "27611", [_fact()])
    _stuck(db, "29406", [_fact(company="Aramex", tracked=True)])
    _stuck(db, "29533", [_fact(company="Bosta", tracked=True)])
    _stuck(db, "30790", [_fact()], placed=datetime.now(timezone.utc).isoformat())

    result = stale_fulfilments(db, shop_domain="hba.myshopify.com")
    by_reason = {
        group["reason"]: [row["order_number"] for row in group["orders"]]
        for group in result["groups"]
    }

    assert by_reason[NO_TRACKING] == ["#27611"]
    assert by_reason[OTHER_COURIER] == ["#29406"]
    assert by_reason[COURIER_SILENT] == ["#29533"]
    # Recent: still inside Bosta's normal few days, not a person's problem yet.
    assert result["total"] == 3
    first = result["groups"][0]["orders"][0]
    assert first["admin_url"] == "https://hba.myshopify.com/admin/orders/27611"
