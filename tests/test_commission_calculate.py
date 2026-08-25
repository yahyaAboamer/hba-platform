"""What is a model owed for a month? §9.5 and §9.6.

The end of the chain, and the first figure anyone would actually be paid.

The arithmetic rule that matters: `base × rate_bp` produces fractional piastres,
so the numerator is carried **undivided** across every order and divided once
(ADR 0003), then rounded once, half-up, on the final total (ADR 0004). Rounding
per order compounds one error per order — and produces a different number.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.money import format_egp
from app.core.passwords import hash_password
from app.models.affiliates import AccountKind
from app.models.attributed_orders import AttributedOrder, CommissionState
from app.models.compensation import CompensationType
from app.models.identity import UserAccount
from app.models.orders import OrderIndex
from app.services.affiliates import create_affiliate
from app.services.commission.calculate import (
    NO_TERMS,
    TARGETS_UNVERIFIED,
    calculate_month,
)
from app.services.compensation import set_terms

MONTH = "2026-04"


def _affiliate(db, name="Nour", kind=AccountKind.MODEL):
    account = UserAccount(
        email=f"{name.lower()}@example.com",
        password_hash=hash_password("a-long-enough-password"),
        status="active",
        display_name=name,
    )
    db.add(account)
    db.flush()
    return create_affiliate(
        db, user_account_id=account.id, name=name, account_kind=kind
    )


def _earned(
    db,
    affiliate,
    order_id,
    base,
    month=MONTH,
    state=CommissionState.EARNED,
):
    db.add(
        OrderIndex(
            shopify_order_id=order_id,
            order_number=f"#{order_id}",
            placed_at=datetime(2026, 4, 15, 12, tzinfo=timezone.utc),
            business_month=month,
            discount_codes=["NOUR10"],
            subtotal_piastres=base,
            total_piastres=base,
            shipping_piastres=0,
            tax_piastres=0,
            currency="EGP",
        )
    )
    db.flush()
    row = AttributedOrder(
        shopify_order_id=order_id,
        affiliate_id=affiliate.id,
        business_month=month,
        commission_base_piastres=base,
        commission_state=state,
    )
    db.add(row)
    db.flush()
    return row


# ── The arithmetic ─────────────────────────────────────────────────────────────


def test_a_month_with_no_orders_is_worth_nothing(db):
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )

    result = calculate_month(db, affiliate, MONTH)

    assert result.earned_orders == 0
    assert result.payout_piastres == 0
    assert result.is_payable is True


def test_one_order_at_ten_percent(db):
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    _earned(db, affiliate, "1", 106_200)

    result = calculate_month(db, affiliate, MONTH)

    assert result.earned_base_piastres == 106_200
    assert result.commission_piastres == Decimal("10620")
    assert result.payout_piastres == 10_600, "E£106.20 → E£106"


def test_the_fractional_piastre_survives_to_the_end(db):
    """§9.6's worked example: 106,237 × 1000 ÷ 10,000 = 10,623.7. Truncating
    mid-chain would lose the .7, and forty of those add up.
    """
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    _earned(db, affiliate, "1", 106_237)

    result = calculate_month(db, affiliate, MONTH)

    assert result.commission_piastres == Decimal("10623.7")


def test_rounding_per_order_would_give_a_different_answer(db):
    """The reason ADR 0003 exists. Forty orders each ending in a half piastre:
    rounding every one of them first and summing does not produce the same
    figure as summing exactly and rounding once.
    """
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=333,
    )
    for index in range(40):
        _earned(db, affiliate, str(1000 + index), 10_015)

    result = calculate_month(db, affiliate, MONTH)

    exact_once = Decimal(40 * 10_015 * 333) / Decimal(10_000)
    assert result.exact_unrounded_piastres == exact_once

    per_order = sum(
        round(Decimal(10_015 * 333) / Decimal(10_000)) for _ in range(40)
    )
    assert result.exact_unrounded_piastres != Decimal(per_order)


@pytest.mark.parametrize(
    "exact_piastres,expected",
    [
        (1_060_837, 1_060_800),  # E£10,608.37 → E£10,608
        (1_060_850, 1_060_900),  # E£10,608.50 → E£10,609, half-up
        (1_060_849, 1_060_800),
    ],
)
def test_the_total_rounds_half_up_to_whole_pounds(db, exact_piastres, expected):
    """§9.6's own examples. Half-up pays fractionally more about as often as
    fractionally less, averaging to roughly nothing across the programme.
    """
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=10_000,
    )
    _earned(db, affiliate, "1", exact_piastres)

    result = calculate_month(db, affiliate, MONTH)

    assert result.payout_piastres == expected
    assert result.payout_piastres % 100 == 0, "a payout is always whole pounds"


def test_both_figures_come_back(db):
    """The audit has to show what was calculated as well as what will be paid."""
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    _earned(db, affiliate, "1", 106_237)

    result = calculate_month(db, affiliate, MONTH)

    assert result.exact_unrounded_piastres == Decimal("10623.7")
    assert result.payout_piastres == 10_600
    assert format_egp(result.payout_piastres) == "E£106.00"


# ── Which orders count ─────────────────────────────────────────────────────────


def test_only_earned_orders_are_paid(db):
    """Pending is shown separately rather than hidden, so a model can see what
    is coming; void counts for nothing.
    """
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    _earned(db, affiliate, "1", 100_000)
    _earned(db, affiliate, "2", 50_000, state=CommissionState.PENDING)
    _earned(db, affiliate, "3", 70_000, state=CommissionState.VOID)

    result = calculate_month(db, affiliate, MONTH)

    assert result.earned_base_piastres == 100_000
    assert result.pending_orders == 1
    assert result.pending_base_piastres == 50_000
    assert result.void_orders == 1


def test_another_months_orders_are_not_counted(db):
    """August sales means orders placed in August, and that never shifts."""
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    _earned(db, affiliate, "1", 100_000, month=MONTH)
    _earned(db, affiliate, "2", 900_000, month="2026-05")

    result = calculate_month(db, affiliate, MONTH)

    assert result.earned_base_piastres == 100_000


def test_another_models_orders_are_not_counted(db):
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    set_terms(
        db,
        nour,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    _earned(db, nour, "1", 100_000)
    _earned(db, sara, "2", 900_000)

    assert calculate_month(db, nour, MONTH).earned_base_piastres == 100_000


# ── The three ways to be paid ──────────────────────────────────────────────────


def test_commission_only(db):
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1500,
    )
    _earned(db, affiliate, "1", 200_000)

    result = calculate_month(db, affiliate, MONTH)

    assert result.exact_unrounded_piastres == Decimal("30000")
    assert result.payout_piastres == 30_000


def test_a_fixed_salary_is_added_on_top(db):
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.FIXED_PLUS_COMMISSION,
        commission_rate_bp=1000,
        fixed_amount_piastres=500_000,
    )
    _earned(db, affiliate, "1", 200_000)

    result = calculate_month(db, affiliate, MONTH)

    assert result.commission_piastres == Decimal("20000")
    assert result.fixed_piastres == 500_000
    assert result.payout_piastres == 520_000


def test_a_fixed_salary_is_paid_in_a_month_with_no_sales(db):
    """It is a salary. Nothing about it depends on whether she sold anything."""
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.FIXED_PLUS_COMMISSION,
        commission_rate_bp=1000,
        fixed_amount_piastres=500_000,
    )

    result = calculate_month(db, affiliate, MONTH)

    assert result.payout_piastres == 500_000
    assert result.is_payable is True


def test_a_base_guarantee_is_never_resolved_here(db):
    """max(commission, base) is only correct when targets were achieved **and**
    verified, and targets are Phase 5. Assuming they were missed underpays;
    assuming they were met overpays. So it says so instead.
    """
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.BASE_GUARANTEE,
        commission_rate_bp=1000,
        base_amount_piastres=800_000,
    )
    _earned(db, affiliate, "1", 200_000)

    result = calculate_month(db, affiliate, MONTH)

    assert TARGETS_UNVERIFIED in result.blockers
    assert result.is_payable is False
    assert result.commission_piastres == Decimal("20000")
    assert result.base_amount_piastres == 800_000


def test_the_commission_is_still_reported_under_a_guarantee(db):
    """Blocking approval is not the same as knowing nothing. The commission is
    the floor either way, and Phase 5 only decides whether the guarantee lifts
    it.
    """
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.BASE_GUARANTEE,
        commission_rate_bp=1000,
        base_amount_piastres=100,
    )
    _earned(db, affiliate, "1", 200_000)

    result = calculate_month(db, affiliate, MONTH)

    assert result.exact_unrounded_piastres == Decimal("20000")


# ── Terms are the month's own ──────────────────────────────────────────────────


def test_a_month_uses_its_own_rate_not_todays(db):
    """A rate change in June must not silently rewrite what April was worth."""
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        end_month="2026-04",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=800,
    )
    set_terms(
        db,
        affiliate,
        start_month="2026-05",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1200,
    )
    _earned(db, affiliate, "1", 100_000)

    result = calculate_month(db, affiliate, MONTH)

    assert result.commission_rate_bp == 800
    assert result.payout_piastres == 8_000


def test_a_month_with_no_terms_reports_sales_but_refuses_to_pay(db):
    """The sales are real and worth reporting. Guessing at a rate is how
    somebody gets paid the wrong amount for eight months.
    """
    affiliate = _affiliate(db)
    _earned(db, affiliate, "1", 100_000)

    result = calculate_month(db, affiliate, MONTH)

    assert result.earned_base_piastres == 100_000
    assert result.payout_piastres == 0
    assert NO_TERMS in result.blockers
    assert result.is_payable is False


# ── House accounts ─────────────────────────────────────────────────────────────


def test_a_house_account_has_real_sales_and_is_owed_nothing(db):
    """HBA10 is a real code used by real customers and needs a working
    dashboard. Hiding its orders would report HBA's own sales as belonging to
    nobody, which is a different and wrong answer.
    """
    house = _affiliate(db, "House", kind=AccountKind.HOUSE)
    set_terms(
        db,
        house,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    _earned(db, house, "1", 500_000)

    result = calculate_month(db, house, MONTH)

    assert result.earned_base_piastres == 500_000
    assert result.is_house is True
    assert result.payout_piastres == 0
    assert result.is_payable is False
