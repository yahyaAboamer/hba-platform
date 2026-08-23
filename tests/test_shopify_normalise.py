"""Turning a Shopify order node into an order_index row.

This is the boundary where raw Shopify data enters the platform, so the money
and timezone rules are enforced here and tested here.
"""

import pytest

from app.services.shopify.normalise import money_to_piastres, normalise_order


def _node(**overrides) -> dict:
    node = {
        "id": "gid://shopify/Order/5123456789",
        "legacyResourceId": "5123456789",
        "name": "#29115",
        "createdAt": "2026-08-18T16:36:00Z",
        "updatedAt": "2026-08-20T09:00:00Z",
        "cancelledAt": None,
        "displayFinancialStatus": "PARTIALLY_PAID",
        "displayFulfillmentStatus": "FULFILLED",
        "discountCodes": ["HBA10"],
        "currentSubtotalPriceSet": {"shopMoney": {"amount": "1675.00", "currencyCode": "EGP"}},
        "currentTotalPriceSet": {"shopMoney": {"amount": "1752.00", "currencyCode": "EGP"}},
        "totalShippingPriceSet": {"shopMoney": {"amount": "95.00", "currencyCode": "EGP"}},
        "currentTotalTaxSet": {"shopMoney": {"amount": "0.00", "currencyCode": "EGP"}},
    }
    node.update(overrides)
    return node


# ── Money ──────────────────────────────────────────────────────────────────────


def test_money_becomes_integer_piastres():
    assert money_to_piastres("1157.00") == 115_700
    assert money_to_piastres("0.05") == 5
    assert money_to_piastres("1675") == 167_500


def test_money_never_goes_through_a_float():
    """0.07 and 0.29 are not exactly representable in binary; Decimal is."""
    assert money_to_piastres("1234.07") == 123_407
    assert money_to_piastres("0.29") == 29
    assert money_to_piastres("19.99") == 1999


def test_money_rounds_a_third_decimal_rather_than_truncating():
    # Shopify can return extra precision on a multi-currency shop.
    assert money_to_piastres("10.005") == 1001
    assert money_to_piastres("10.004") == 1000


def test_absent_money_is_zero_not_an_error():
    assert money_to_piastres(None) == 0
    assert money_to_piastres("") == 0


def test_a_float_is_refused():
    """Accepting one would mean precision was already lost upstream."""
    with pytest.raises(TypeError):
        money_to_piastres(1157.00)


def test_an_unparseable_amount_is_refused():
    with pytest.raises(ValueError):
        money_to_piastres("not-a-number")


# ── Identity ───────────────────────────────────────────────────────────────────


def test_identifiers_are_taken_from_the_node():
    row = normalise_order(_node())
    assert row["shopify_order_id"] == "5123456789"
    assert row["shopify_order_gid"] == "gid://shopify/Order/5123456789"
    assert row["order_number"] == "#29115"


def test_the_id_falls_back_to_the_tail_of_the_gid():
    """A bulk export omits legacyResourceId on some object shapes."""
    row = normalise_order(_node(legacyResourceId=None))
    assert row["shopify_order_id"] == "5123456789"


def test_a_node_without_any_identifier_is_refused():
    with pytest.raises(ValueError):
        normalise_order(_node(legacyResourceId=None, id=None))


def test_a_node_without_a_creation_time_is_refused():
    """Without it there is no business month, so the order cannot be placed."""
    with pytest.raises(ValueError):
        normalise_order(_node(createdAt=None))


# ── The business month ─────────────────────────────────────────────────────────


def test_the_business_month_is_derived_in_cairo():
    """Spec section 7. This decides which payroll month the order belongs to."""
    # 21:30 UTC on 31 August is 00:30 on 1 September in Cairo (UTC+3).
    assert normalise_order(_node(createdAt="2026-08-31T21:30:00Z"))["business_month"] == "2026-09"
    # 20:00 UTC the same evening is still 31 August in Cairo.
    assert normalise_order(_node(createdAt="2026-08-31T20:00:00Z"))["business_month"] == "2026-08"


def test_the_winter_boundary_differs_from_the_summer_one():
    """Egypt is UTC+2 in December, so the same clock time falls differently."""
    assert normalise_order(_node(createdAt="2026-12-31T21:30:00Z"))["business_month"] == "2026-12"
    assert normalise_order(_node(createdAt="2026-12-31T22:30:00Z"))["business_month"] == "2027-01"


def test_the_utc_prefix_would_have_given_the_wrong_month():
    """Proof that reading the timestamp's own prefix is not good enough."""
    created = "2026-08-31T21:30:00Z"
    assert created[:7] == "2026-08"  # the naive answer
    assert normalise_order(_node(createdAt=created))["business_month"] == "2026-09"


# ── Discount codes ─────────────────────────────────────────────────────────────


def test_discount_codes_are_normalised_to_uppercase():
    row = normalise_order(_node(discountCodes=["hba10", " Nour10 ", "SUMMER"]))
    assert row["discount_codes"] == ["HBA10", "NOUR10", "SUMMER"]


def test_blank_discount_codes_are_dropped():
    row = normalise_order(_node(discountCodes=["HBA10", "", None, "   "]))
    assert row["discount_codes"] == ["HBA10"]


def test_an_order_with_no_codes_is_still_indexed():
    """Most orders carry no affiliate code, and they are still recorded.

    Without them, "was this code used before it was registered?" could only be
    answered by re-scanning all of Shopify.
    """
    row = normalise_order(_node(discountCodes=[]))
    assert row["discount_codes"] == []
    assert row["shopify_order_id"] == "5123456789"


def test_multiple_codes_are_all_kept():
    """Attribution needs every code, not just the first."""
    row = normalise_order(_node(discountCodes=["NOUR10", "FREESHIP"]))
    assert row["discount_codes"] == ["NOUR10", "FREESHIP"]


# ── Everything else ────────────────────────────────────────────────────────────


def test_money_fields_are_piastres():
    row = normalise_order(_node())
    assert row["subtotal_piastres"] == 167_500
    assert row["total_piastres"] == 175_200
    assert row["shipping_piastres"] == 9_500
    assert row["tax_piastres"] == 0


def test_statuses_are_lowercased():
    row = normalise_order(_node())
    assert row["financial_status"] == "partially_paid"
    assert row["fulfillment_status"] == "fulfilled"


def test_partially_paid_is_carried_through_verbatim():
    """The status the old dashboard ignored entirely (spec section 9.1).

    Nothing acts on it yet - commission arrives in Phase 4 - but it has to be
    recorded now, or the information is simply not there when it matters.
    """
    assert normalise_order(_node())["financial_status"] == "partially_paid"


def test_a_cancelled_order_records_when():
    assert normalise_order(_node(cancelledAt="2026-08-19T10:00:00Z"))["cancelled_at"] is not None


def test_currency_is_captured():
    assert normalise_order(_node())["currency"] == "EGP"


def test_a_missing_money_block_does_not_crash():
    """Shopify omits fields the token has no scope for."""
    row = normalise_order(_node(totalShippingPriceSet=None, currentTotalTaxSet=None))
    assert row["shipping_piastres"] == 0
    assert row["tax_piastres"] == 0


def test_order_29115_matches_the_specification():
    """The real order from spec section 9.1.

    Shopify's subtotal reads 1,675 mid-exchange while only 1,157 was collected.
    Both are recorded as they are; deciding which drives commission is Phase 4's
    job, and it cannot make that decision from data that was never stored.
    """
    row = normalise_order(_node())
    assert row["subtotal_piastres"] == 167_500  # inflated by the open exchange
    assert row["total_piastres"] == 175_200
    assert row["shipping_piastres"] == 9_500
    assert row["financial_status"] == "partially_paid"
