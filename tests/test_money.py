"""Money arithmetic.

Every rule here comes from spec section 9.6. These tests are the guard on the
single most consequential module in the platform: if this is wrong, every
affiliate is paid the wrong amount and nobody notices for months.
"""

from decimal import Decimal

import pytest

from app.core.money import (
    commission_numerator,
    exact_commission_piastres,
    format_egp,
    round_half_up_to_pounds,
)


# ── Multiply first, divide once ────────────────────────────────────────────────


def test_numerator_multiplies_without_dividing():
    # 106,237 piastres at 10% (1000 basis points)
    assert commission_numerator(106_237, 1000) == 106_237_000


def test_exact_commission_keeps_the_fractional_piastre():
    # 106,237,000 / 10,000 = 10,623.7 piastres — the fraction must survive
    assert exact_commission_piastres(106_237_000) == Decimal("10623.7")


def test_summing_before_dividing_loses_nothing():
    # Three orders that each produce a fractional piastre individually.
    orders = [(106_237, 1000), (33_333, 1000), (66_667, 1000)]
    total = sum(commission_numerator(base, rate) for base, rate in orders)
    # 106237 + 33333 + 66667 = 206,237 piastres; at 10% that is 20,623.7 exactly
    assert exact_commission_piastres(total) == Decimal("20623.7")


def test_dividing_per_order_would_have_lost_money():
    """The reason multiply-then-divide-once exists.

    Truncating each order to whole piastres before summing loses a piastre per
    order. Across a month of orders that is a real, silent shortfall.
    """
    orders = [(106_237, 1000), (33_333, 1000), (66_667, 1000)]

    truncated_per_order = sum(
        int(exact_commission_piastres(commission_numerator(base, rate)))
        for base, rate in orders
    )
    exact_total = exact_commission_piastres(
        sum(commission_numerator(base, rate) for base, rate in orders)
    )

    assert truncated_per_order == 20_622
    assert exact_total == Decimal("20623.7")
    assert exact_total - truncated_per_order == Decimal("1.7")


def test_many_small_orders_stay_exact():
    # 1,000 orders of 1 piastre at 33.33% each contribute 0.3333 piastres.
    orders = [(1, 3333)] * 1000
    total = sum(commission_numerator(base, rate) for base, rate in orders)
    assert exact_commission_piastres(total) == Decimal("333.3")


# ── Rounding: half-up, once, on the total ──────────────────────────────────────


def test_rounds_half_up_not_bankers():
    # E£10,608.50 must round UP to E£10,609.
    assert round_half_up_to_pounds(Decimal("1060850")) == 1_060_900


def test_python_round_would_get_it_wrong():
    """Proof, in the suite, of why the built-in round() is never used here.

    Python rounds half to even. E£10,608.50 becomes E£10,608 and E£10,609.50
    becomes E£10,610 — the affiliate is underpaid half the time, and the
    behaviour looks arbitrary to anyone reading a payslip.
    """
    assert round(Decimal("10608.50")) == 10608   # rounds down to even
    assert round(Decimal("10609.50")) == 10610   # rounds up to even
    assert round_half_up_to_pounds(Decimal("1060850")) == 1_060_900  # always up
    assert round_half_up_to_pounds(Decimal("1060950")) == 1_061_000  # always up


def test_rounds_down_below_half():
    # E£10,608.37 rounds down to E£10,608
    assert round_half_up_to_pounds(Decimal("1060837")) == 1_060_800


def test_rounds_up_above_half():
    # E£10,608.61 rounds up to E£10,609
    assert round_half_up_to_pounds(Decimal("1060861")) == 1_060_900


def test_rounded_result_is_always_whole_pounds():
    for value in ["0", "1", "49", "50", "51", "1060837", "999999"]:
        assert round_half_up_to_pounds(Decimal(value)) % 100 == 0


def test_fractional_piastres_round_correctly():
    # The exact value carries a fraction; rounding still lands on whole pounds.
    assert round_half_up_to_pounds(Decimal("10623.7")) == 10_600   # E£106.237 -> E£106
    assert round_half_up_to_pounds(Decimal("10650.0")) == 10_700   # E£106.50  -> E£107


def test_zero_and_negative_are_handled():
    assert round_half_up_to_pounds(Decimal("0")) == 0
    # Negatives arise from credits and write-offs; half-up rounds away from zero.
    assert round_half_up_to_pounds(Decimal("-50")) == -100
    assert round_half_up_to_pounds(Decimal("-49")) == 0
    assert round_half_up_to_pounds(Decimal("-1060850")) == -1_060_900


def test_accepts_an_integer_as_well_as_a_decimal():
    assert round_half_up_to_pounds(1_060_837) == 1_060_800


# ── Guard rails ────────────────────────────────────────────────────────────────


def test_rate_must_be_within_range():
    with pytest.raises(ValueError):
        commission_numerator(1000, 0)
    with pytest.raises(ValueError):
        commission_numerator(1000, -100)
    with pytest.raises(ValueError):
        commission_numerator(1000, 10_001)


def test_full_rate_is_allowed():
    # 100% is legitimate; anything above it is not.
    assert commission_numerator(1000, 10_000) == 10_000_000


def test_base_must_not_be_negative():
    with pytest.raises(ValueError):
        commission_numerator(-1, 1000)


def test_zero_base_is_valid():
    assert commission_numerator(0, 1000) == 0
    assert exact_commission_piastres(0) == Decimal("0")


def test_floats_are_refused_outright():
    """A float here is the bug this whole module exists to prevent."""
    with pytest.raises(TypeError):
        commission_numerator(106_237.0, 1000)
    with pytest.raises(TypeError):
        commission_numerator(106_237, 10.5)


def test_booleans_are_refused():
    # bool is a subclass of int; True would silently mean a rate of 1 bp.
    with pytest.raises(TypeError):
        commission_numerator(True, 1000)
    with pytest.raises(TypeError):
        commission_numerator(1000, True)


# ── Display ────────────────────────────────────────────────────────────────────


def test_format_egp_uses_thousands_and_two_decimals():
    assert format_egp(1_060_837) == "E£10,608.37"
    assert format_egp(0) == "E£0.00"
    assert format_egp(5) == "E£0.05"
    assert format_egp(100) == "E£1.00"


def test_format_egp_handles_negatives():
    assert format_egp(-1_060_837) == "-E£10,608.37"


# ── The real order from the specification ──────────────────────────────────────


def test_order_29115_from_the_spec():
    """Spec section 9.1: the exchange-inflation example, computed correctly.

    The customer paid E£1,157.00, of which E£95.00 was shipping. The commission
    base is therefore E£1,062.00. Shopify's subtotal during the in-flight
    exchange showed E£1,675.00, which is what the old dashboard read.
    """
    paid_piastres = 115_700
    shipping_piastres = 9_500
    base = paid_piastres - shipping_piastres
    assert base == 106_200

    exact = exact_commission_piastres(commission_numerator(base, 1000))
    assert exact == Decimal("10620")                 # E£106.20
    assert round_half_up_to_pounds(exact) == 10_600  # E£106.00


def test_order_29115_shows_what_the_old_system_would_have_paid():
    """The same order read from Shopify's inflated subtotal, for comparison."""
    inflated_base = 167_500 - 11_800  # 3 items less the HBA10 discount
    inflated = exact_commission_piastres(commission_numerator(inflated_base, 1000))
    correct = exact_commission_piastres(commission_numerator(106_200, 1000))

    assert inflated == Decimal("15570")  # E£155.70
    assert correct == Decimal("10620")   # E£106.20
    # Roughly 47% too much on a single order.
    assert (inflated - correct) / correct > Decimal("0.46")


def test_rounding_refuses_floats():
    """A float would reintroduce the imprecision this module exists to avoid.

    Decimal(1060850.7) is 1060850.69999999995343..., so a value near a .5
    boundary could round the wrong way and silently change a payout.
    """
    with pytest.raises(TypeError):
        round_half_up_to_pounds(1060850.7)
    with pytest.raises(TypeError):
        round_half_up_to_pounds(0.0)


def test_rounding_refuses_strings_and_booleans():
    with pytest.raises(TypeError):
        round_half_up_to_pounds("1060850")
    with pytest.raises(TypeError):
        round_half_up_to_pounds(True)
