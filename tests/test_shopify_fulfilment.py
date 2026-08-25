"""Reading delivery, returns and refunds out of a Shopify order.

Phase 4 Task 2b. Every field these functions read was confirmed against HBA's
live shop first (`GET /api/operations/order-facts`), and the report contained
two findings that shaped the code rather than merely confirming it:

**The order-level status cannot answer "was it delivered?"** Across 529 real
orders `displayFulfillmentStatus` has two values, fulfilled and unfulfilled. In
a sample of 50 it called *fulfilled*, only 35 had actually been delivered - ten
mid-attempt, three out for delivery, one in transit, one failed outright.

**A refund is not always a refund.** One order carried refund line items worth
E£998 against a total refunded of zero: an exchange, where the goods come back
and no money does.
"""

import logging

import pytest

from app.services.shopify.fulfilment import (
    DELIVERED,
    NO_RETURN,
    RETURN_ACTIVITY_STATUSES,
    UNRESOLVED_RETURN_STATUSES,
    DELIVERED_STATUSES,
    FAILED,
    FAILED_STATUSES,
    IN_FLIGHT,
    IN_FLIGHT_STATUSES,
    classify_fulfilment,
    derive_delivery,
    derive_refunds,
    derive_return,
)
from app.services.shopify.normalise import normalise_order


def _fulfilment(status, delivered_at=None):
    return {"displayStatus": status, "deliveredAt": delivered_at}


def _refund(total="0.00", merchandise=()):
    return {
        "totalRefundedSet": {"shopMoney": {"amount": total}},
        "refundLineItems": {
            "nodes": [
                {"subtotalSet": {"shopMoney": {"amount": amount}}}
                for amount in merchandise
            ]
        },
    }


# ── The statuses HBA's shop actually produces ──────────────────────────────────


@pytest.mark.parametrize(
    "status,expected",
    [
        # Every value the live report returned, with its real frequency in a
        # sample of 50 shipped orders noted.
        ("DELIVERED", DELIVERED),  # 35
        ("ATTEMPTED_DELIVERY", IN_FLIGHT),  # 10 - Bosta retries; not a failure
        ("FULFILLED", IN_FLIGHT),  # 4 - shipped, nothing more
        ("OUT_FOR_DELIVERY", IN_FLIGHT),  # 3 - still on the van
        ("IN_TRANSIT", IN_FLIGHT),  # 1
        ("NOT_DELIVERED", FAILED),  # 1
    ],
)
def test_the_live_statuses_classify_as_the_business_says(status, expected):
    """HBA's rule, in their words: delivered and failed delivery are what
    matter, and anything in between is still processing.
    """
    assert classify_fulfilment(status) == expected


@pytest.mark.parametrize("status", ["OUT_FOR_DELIVERY", "ATTEMPTED_DELIVERY", "NOT_DELIVERED"])
def test_a_status_containing_the_word_is_not_a_delivery(status):
    """All three contain "deliver". Matching the substring reads a parcel still
    on the van as money earned - §9.1's defect, rebuilt. Match the set.
    """
    assert classify_fulfilment(status) != DELIVERED


def test_collected_in_person_is_delivered():
    """PICKED_UP means the customer has the goods. Withholding commission
    because the courier called it something else would be wrong.
    """
    assert classify_fulfilment("PICKED_UP") == DELIVERED


def test_the_three_sets_do_not_overlap():
    """If a status were in two sets, which one won would depend on the order
    the code happened to check them in.
    """
    assert not (DELIVERED_STATUSES & FAILED_STATUSES)
    assert not (DELIVERED_STATUSES & IN_FLIGHT_STATUSES)
    assert not (FAILED_STATUSES & IN_FLIGHT_STATUSES)


def test_an_unknown_status_is_pending_and_loud(caplog):
    """A courier integration change introduces new values. Neither earning nor
    voiding on one nobody has classified is the only safe answer - and this is
    what stops it being a silent one.
    """
    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        assert classify_fulfilment("TELEPORTED", order_id="9") == IN_FLIGHT

    assert "ANOMALY unknown_fulfilment_status" in caplog.text
    assert "TELEPORTED" in caplog.text


def test_a_missing_status_is_pending_and_quiet():
    """An absent status is not a surprising status. Reporting it would make the
    anomaly meaningless through volume.
    """
    assert classify_fulfilment(None) == IN_FLIGHT
    assert classify_fulfilment("") == IN_FLIGHT


# ── Reducing several fulfilments to one answer ─────────────────────────────────


def test_an_order_with_no_fulfilment_has_no_delivery_state():
    """Distinct from "not delivered". An order nobody has shipped and an order
    that failed to arrive need different answers - and an unsynced row must not
    read as a failure.
    """
    state, delivered_at, raw = derive_delivery([])
    assert (state, delivered_at, raw) == (None, None, None)


def test_a_delivered_order_carries_when():
    state, delivered_at, raw = derive_delivery(
        [_fulfilment("DELIVERED", "2026-04-20T10:00:00Z")]
    )
    assert state == DELIVERED
    assert delivered_at.isoformat().startswith("2026-04-20T10:00")
    assert raw == "DELIVERED"


def test_a_split_shipment_is_delivered_only_when_the_last_parcel_lands():
    """Paying when the first of two parcels arrives pays for goods the customer
    does not have yet.
    """
    state, _, _ = derive_delivery(
        [
            _fulfilment("DELIVERED", "2026-04-18T10:00:00Z"),
            _fulfilment("IN_TRANSIT"),
        ]
    )
    assert state == IN_FLIGHT


def test_the_delivery_date_is_the_latest_parcel_not_the_first():
    """When the customer had all of it."""
    _, delivered_at, _ = derive_delivery(
        [
            _fulfilment("DELIVERED", "2026-04-18T10:00:00Z"),
            _fulfilment("DELIVERED", "2026-04-22T09:00:00Z"),
        ]
    )
    assert delivered_at.isoformat().startswith("2026-04-22")


def test_an_order_that_wholly_failed_is_failed():
    state, _, _ = derive_delivery([_fulfilment("NOT_DELIVERED")])
    assert state == FAILED


def test_one_parcel_arrived_and_one_failed_resolves_neither_way():
    """Genuinely ambiguous: part of the order is with the customer and part
    never will be. Earning would pay for goods that came back; voiding would
    refuse commission on goods she sold. It waits - see docs/limits.md.
    """
    state, _, _ = derive_delivery(
        [_fulfilment("DELIVERED", "2026-04-18T10:00:00Z"), _fulfilment("FAILURE")]
    )
    assert state == IN_FLIGHT


def test_delivered_with_no_timestamp_is_still_delivered():
    """Some couriers report the status without a date. Refusing to call it
    delivered would leave the order pending for ever.
    """
    state, delivered_at, _ = derive_delivery([_fulfilment("DELIVERED")])
    assert state == DELIVERED
    assert delivered_at is None


# ── Returns, which freeze the base ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "status,unresolved,activity",
    [
        # (still being decided, anything ever happened)
        ("NO_RETURN", False, False),  # 44 of 50 in the live sample
        ("REQUESTED", True, True),
        ("IN_PROGRESS", True, True),  # 6 of 50
        ("INSPECTION_COMPLETE", True, True),
        # Resolved. The goods are back and the decision is made - but the base
        # stays frozen, because the subtotal E-stebdal left behind is the
        # inflated number the freeze exists to keep out.
        ("RETURNED", False, True),
        ("RETURN_FAILED", False, True),
        (None, False, False),
    ],
)
def test_being_decided_and_having_happened_are_different_questions(
    status, unresolved, activity
):
    """Conflating them is a bug this module already made once.

    One set for both would leave `RETURNED` looking open for ever: the order
    would never earn and never void, and nothing would report it.
    """
    name, is_open, had_activity = derive_return(status)
    assert is_open is unresolved
    assert had_activity is activity
    assert name == (status.upper() if status else None)


def test_a_completed_return_stops_blocking_the_order():
    """The order has to resolve. Whether it earns or voids is then decided by
    whether money actually went back - not by the return status.
    """
    _, is_open, had_activity = derive_return("RETURNED")
    assert is_open is False, "a finished return would park the order for ever"
    assert had_activity is True, "the base must stay frozen"


def test_the_base_stays_frozen_after_the_return_finishes():
    """Unfreezing on completion would let the post-exchange subtotal back in -
    the E£1,675-instead-of-E£1,062 reading on #29115.
    """
    assert derive_return("RETURNED")[2] is True
    assert derive_return("RETURN_FAILED")[2] is True


def test_every_unresolved_status_also_counts_as_activity():
    """A return cannot be being decided without having happened. If these ever
    disagreed, an order could block earning while its base stayed live.
    """
    assert UNRESOLVED_RETURN_STATUSES <= RETURN_ACTIVITY_STATUSES


def test_no_return_is_the_only_quiet_value():
    assert NO_RETURN not in RETURN_ACTIVITY_STATUSES
    assert NO_RETURN not in UNRESOLVED_RETURN_STATUSES


def test_six_of_fifty_live_orders_had_a_return_open():
    """Not a hypothetical. The freeze applies to about one order in eight."""
    sample = ["NO_RETURN"] * 44 + ["IN_PROGRESS"] * 6
    assert sum(1 for status in sample if derive_return(status)[1]) == 6


# ── Telling a return from an exchange, without classifying either ──────────────


def test_an_exchange_and_a_return_look_identical_while_open():
    """E-stebdal opens the same Shopify return for both. The platform does not
    need to tell them apart: both freeze the base and both block earning, so
    neither is paid while it is open.
    """
    assert derive_return("IN_PROGRESS") == ("IN_PROGRESS", True, True)


def test_what_separates_them_is_whether_money_moved():
    """Once resolved, one fact decides it - and it is a fact, not a judgement.

        an exchange returns goods and no money
        a return  returns goods and money
    """
    exchange_total, exchange_goods = derive_refunds(
        {"refunds": [_refund("0.00", ["998.00"])]}
    )
    return_total, return_goods = derive_refunds(
        {"refunds": [_refund("600.00", ["600.00"])]}
    )

    assert exchange_goods > 0 and exchange_total == 0, "goods back, no money"
    assert return_goods > 0 and return_total > 0, "goods back, money back"


# ── Refunds: two numbers, because they disagree ────────────────────────────────


def test_an_exchange_returns_goods_and_no_money():
    """The live finding. E£998 of merchandise came back against a total
    refunded of zero, because the customer swapped rather than got paid.

    Subtracting the merchandise would cut E£998 from a base where the customer
    paid in full and kept goods of equal value - underpaying the model on
    precisely the case ADR 0011's freeze exists to protect.
    """
    total, merchandise = derive_refunds({"refunds": [_refund("0.00", ["998.00"])]})
    assert total == 0
    assert merchandise == 99_800


def test_a_genuine_refund_moves_both_numbers():
    """Jacket kept, pants returned and refunded. Both figures agree, and Task 3
    can reduce the base with confidence.
    """
    total, merchandise = derive_refunds({"refunds": [_refund("600.00", ["600.00"])]})
    assert (total, merchandise) == (60_000, 60_000)


def test_refunded_shipping_shows_in_the_total_but_not_the_merchandise():
    """§9.3 reduces the base by merchandise only - shipping was never in the
    base, so subtracting it would take the model's commission twice.
    """
    total, merchandise = derive_refunds({"refunds": [_refund("695.00", ["600.00"])]})
    assert total == 69_500
    assert merchandise == 60_000


def test_several_refunds_on_one_order_add_up():
    total, merchandise = derive_refunds(
        {"refunds": [_refund("200.00", ["200.00"]), _refund("150.00", ["150.00"])]}
    )
    assert (total, merchandise) == (35_000, 35_000)


def test_refunds_are_read_from_either_shape():
    """Which shape Shopify uses is an API-version detail. The live shop
    accepted the connection form; the list form has to keep working if it ever
    changes back.
    """
    as_list = derive_refunds({"refunds": [_refund("100.00", ["100.00"])]})
    as_connection = derive_refunds({"refunds": {"nodes": [_refund("100.00", ["100.00"])]}})
    assert as_list == as_connection


def test_an_order_with_no_refunds_is_zero_not_unknown():
    """Nothing came back and we never asked are the same thing for money."""
    assert derive_refunds({}) == (0, 0)


# ── The whole normaliser ───────────────────────────────────────────────────────


def _node(**extra):
    return {
        "legacyResourceId": "29115",
        "name": "#29115",
        "createdAt": "2026-04-15T12:00:00Z",
        "displayFulfillmentStatus": "FULFILLED",
        **extra,
    }


def test_an_order_carries_its_delivery_facts_the_moment_it_is_indexed():
    """Derived at ingestion rather than fetched later. Registering a code
    backfills its history, and reading these from Shopify per order at that
    point would be thousands of calls for facts already in hand.
    """
    values = normalise_order(
        _node(
            fulfillments=[_fulfilment("DELIVERED", "2026-04-20T10:00:00Z")],
            returnStatus="NO_RETURN",
            refunds=[_refund("0.00", ["998.00"])],
        )
    )

    assert values["delivery_state"] == DELIVERED
    assert values["delivery_status"] == "DELIVERED"
    assert values["delivered_at"] is not None
    assert values["return_open"] is False
    assert values["return_activity"] is False
    assert values["refunded_total_piastres"] == 0
    assert values["refunded_merchandise_piastres"] == 99_800


def test_shipped_is_kept_separate_from_delivered():
    """The order-level status said fulfilled for all 50 sampled orders; only 35
    were delivered. Both are stored because they answer different questions,
    and only one of them is allowed to pay anybody.
    """
    values = normalise_order(
        _node(fulfillments=[_fulfilment("OUT_FOR_DELIVERY")], returnStatus="NO_RETURN")
    )

    assert values["fulfillment_status"] == "fulfilled"
    assert values["delivery_state"] == IN_FLIGHT


def test_an_order_shopify_told_us_nothing_about_stays_unknown():
    """An order indexed before these fields were ever requested must not read
    as a failed delivery.
    """
    values = normalise_order(_node())

    assert values["delivery_state"] is None
    assert values["delivery_status"] is None
    assert values["return_status"] is None
    assert values["return_open"] is False
    assert values["return_activity"] is False
