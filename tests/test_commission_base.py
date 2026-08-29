"""What is this order worth? §9.3, ADR 0011, ADR 0025.

Order `#29115` is the acceptance test, not an illustration. The customer paid
**E£1,157**, of which E£95 was shipping, so the base is **E£1,062**. Mid-exchange
Shopify reported three items totalling E£1,675 and the old dashboard calculated
on roughly E£1,557 — about **47% too much on a single order**.

The base moves until delivery and then stops. An exchange can only happen to a
parcel the customer already has, so freezing on delivery is strictly earlier than
freezing on return activity — and needs no assumption about what E-stebdal does
first, which is a thing nobody at HBA can observe.
"""

import pytest

from app.services.commission.base import base_for_order, commission_base

#: #29115, in piastres. E£1,157 paid, E£95 of it shipping, no tax.
PAID = 115_700
SHIPPING = 9_500
TAX = 0
EXPECTED_BASE = 106_200

#: What Shopify reports once E-stebdal has added the replacement without
#: removing the returned item: 3 items, E£1,675.
INFLATED_PAID = 167_500 + SHIPPING


# ── The worked example ─────────────────────────────────────────────────────────


def test_order_29115_is_worth_exactly_one_thousand_and_sixty_two_pounds():
    """1,157 − 95 = 1,062. The number this whole phase exists to get right."""
    assert commission_base(PAID, SHIPPING, TAX) == EXPECTED_BASE


def test_shipping_and_tax_belong_to_hba_not_the_model():
    assert commission_base(100_000, 9_500, 4_000) == 86_500


def test_the_discount_is_already_in_the_figure():
    """A E£1,000 jacket on a 10% code arrives inside a total of E£900. Nothing
    here needs the code's percentage, and using one would be a bug - it records
    what HBA expects, not what the customer paid.
    """
    assert commission_base(90_000, 0, 0) == 90_000


def test_a_base_can_never_go_negative():
    """A refund larger than the order would otherwise produce one, and a
    negative base subtracts from everything else they earned that month.
    """
    assert commission_base(5_000, 9_500, 0) == 0


def test_an_order_that_is_all_shipping_is_worth_nothing():
    assert commission_base(9_500, 9_500, 0) == 0


# ── Moving, then fixed ─────────────────────────────────────────────────────────


def test_the_base_follows_shopify_until_the_parcel_arrives():
    """A genuine edit before it ships should be reflected."""
    decision = base_for_order(
        total_piastres=PAID, shipping_piastres=SHIPPING, tax_piastres=TAX
    )

    assert decision.piastres == EXPECTED_BASE
    assert decision.is_final is False


def test_delivery_fixes_the_figure():
    decision = base_for_order(
        total_piastres=PAID,
        shipping_piastres=SHIPPING,
        tax_piastres=TAX,
        delivered=True,
        stored_base_piastres=EXPECTED_BASE,
    )

    assert decision.piastres == EXPECTED_BASE
    assert decision.is_final is True


def test_the_exchange_inflation_cannot_reach_a_delivered_order():
    """The defect this module exists to prevent. Shopify now says E£1,675 of
    goods; the base still says E£1,062. Reading the live figure would calculate
    47% too much.
    """
    decision = base_for_order(
        total_piastres=INFLATED_PAID,
        shipping_piastres=SHIPPING,
        tax_piastres=TAX,
        delivered=True,
        stored_base_piastres=EXPECTED_BASE,
    )

    assert decision.piastres == EXPECTED_BASE
    assert decision.piastres != commission_base(INFLATED_PAID, SHIPPING, TAX)


def test_a_cheaper_exchange_cannot_reduce_it_either():
    """ADR 0025 is symmetric. An exchange for something cheaper leaves the model
    exactly where they were - they sold the original, and the swap is HBA's
    service, not theirs.
    """
    decision = base_for_order(
        total_piastres=60_000 + SHIPPING,
        shipping_piastres=SHIPPING,
        tax_piastres=TAX,
        delivered=True,
        stored_base_piastres=EXPECTED_BASE,
    )

    assert decision.piastres == EXPECTED_BASE


def test_a_refund_after_delivery_is_ignored():
    """The accepted exposure, stated as a test so nobody mistakes it for an
    oversight. Six of 537 live orders showed money going back - 1.1%.
    """
    decision = base_for_order(
        total_piastres=0,
        shipping_piastres=0,
        tax_piastres=0,
        delivered=True,
        stored_base_piastres=EXPECTED_BASE,
    )

    assert decision.piastres == EXPECTED_BASE


def test_an_order_first_seen_after_delivery_takes_what_shopify_shows():
    """No previous value to keep. For a historical import of an order already
    mid-exchange that is the inflated figure, and it cannot be recovered from
    data the platform never saw. Recorded in docs/limits.md.
    """
    decision = base_for_order(
        total_piastres=INFLATED_PAID,
        shipping_piastres=SHIPPING,
        tax_piastres=TAX,
        delivered=True,
        stored_base_piastres=None,
    )

    assert decision.piastres == commission_base(INFLATED_PAID, SHIPPING, TAX)
    assert decision.is_final is True


@pytest.mark.parametrize("delivered", [True, False])
def test_the_figure_is_always_the_goods_not_the_total(delivered):
    """Shipping never enters, in either state. HBA's return fee is HBA's cost of
    handling a return, and it could not reach this figure even if the base were
    still moving.
    """
    decision = base_for_order(
        total_piastres=PAID,
        shipping_piastres=SHIPPING,
        tax_piastres=TAX,
        delivered=delivered,
    )

    assert decision.piastres == EXPECTED_BASE
