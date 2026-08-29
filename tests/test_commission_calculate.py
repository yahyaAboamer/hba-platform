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
    NO_TARGET,
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
    """It is a salary. Nothing about it depends on whether they sold anything."""
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


# -- The base guarantee, resolved ---------------------------------------------
#
# Section 9.5 pays max(commission, base amount) - but only when targets were
# achieved **and** verified. Section 11.3's rule underneath it: missing
# information blocks a month, poor performance does not.


def _target(db, affiliate, *, required=(8, 5), actual=None, verified=False):
    from app.services.targets import record_actuals, set_requirements, verify

    target = set_requirements(
        db, affiliate, MONTH, videos=required[0], stories=required[1]
    )
    if actual is not None:
        record_actuals(db, target, videos=actual[0], stories=actual[1])
        if verified:
            verify(db, target)
    return target


def _guaranteed(db, affiliate, *, base=800_000, rate_bp=1000):
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.BASE_GUARANTEE,
        commission_rate_bp=rate_bp,
        base_amount_piastres=base,
    )


def test_achieved_and_verified_applies_the_guarantee(db):
    """Their commission is 200 pounds; the guarantee is 8,000. They are paid the
    guarantee.
    """
    affiliate = _affiliate(db)
    _guaranteed(db, affiliate, base=800_000)
    _target(db, affiliate, actual=(8, 5), verified=True)
    _earned(db, affiliate, "1", 200_000)

    result = calculate_month(db, affiliate, MONTH)

    assert result.is_payable is True
    assert result.guarantee_applied is True
    assert result.payout_piastres == 800_000


def test_the_guarantee_never_caps_a_higher_commission(db):
    """Section 9.5 says this explicitly because it is the intuitive mistake.
    They sold a great deal; they keep all of it.
    """
    affiliate = _affiliate(db)
    _guaranteed(db, affiliate, base=800_000)
    _target(db, affiliate, actual=(8, 5), verified=True)
    _earned(db, affiliate, "1", 20_000_000)

    result = calculate_month(db, affiliate, MONTH)

    assert result.payout_piastres == 2_000_000
    assert result.guarantee_applied is False


def test_the_guarantee_is_never_added_on_top(db):
    """max(commission, base), not commission + base."""
    affiliate = _affiliate(db)
    _guaranteed(db, affiliate, base=800_000)
    _target(db, affiliate, actual=(8, 5), verified=True)
    _earned(db, affiliate, "1", 200_000)

    result = calculate_month(db, affiliate, MONTH)

    assert result.payout_piastres == 800_000
    assert result.payout_piastres != 800_000 + 20_000


def test_a_missed_target_pays_commission_and_approves(db):
    """The block is never a punishment for a quiet month. They are paid what they
    earned, promptly, and the month closes.
    """
    affiliate = _affiliate(db)
    _guaranteed(db, affiliate, base=800_000)
    _target(db, affiliate, required=(8, 5), actual=(8, 4), verified=True)
    _earned(db, affiliate, "1", 200_000)

    result = calculate_month(db, affiliate, MONTH)

    assert result.target_achieved is False
    assert result.is_payable is True, "missing the target is not a blocker"
    assert result.guarantee_applied is False
    assert result.payout_piastres == 20_000


def test_no_target_recorded_blocks_the_month(db):
    """Nobody has said what they were asked for, so nobody can say whether the
    guarantee applies. Section 11.3 blocks on missing information.
    """
    affiliate = _affiliate(db)
    _guaranteed(db, affiliate)
    _earned(db, affiliate, "1", 200_000)

    result = calculate_month(db, affiliate, MONTH)

    assert result.target_achieved is None
    assert NO_TARGET in result.blockers
    assert result.is_payable is False


def test_requirements_set_but_nothing_recorded_also_blocks(db):
    """A requirement with no actual is still nobody knowing what they did."""
    affiliate = _affiliate(db)
    _guaranteed(db, affiliate)
    _target(db, affiliate)
    _earned(db, affiliate, "1", 200_000)

    result = calculate_month(db, affiliate, MONTH)

    assert NO_TARGET in result.blockers


def test_achieved_but_unverified_blocks(db):
    """Verification is what unlocks the guarantee, not a formality. One person
    recording a number that pays a guarantee is one person deciding what
    somebody is owed.
    """
    affiliate = _affiliate(db)
    _guaranteed(db, affiliate)
    _target(db, affiliate, actual=(8, 5), verified=False)
    _earned(db, affiliate, "1", 200_000)

    result = calculate_month(db, affiliate, MONTH)

    assert result.target_achieved is True
    assert result.target_verified is False
    assert TARGETS_UNVERIFIED in result.blockers
    assert result.is_payable is False


def test_a_missed_target_needs_no_verification_to_approve(db):
    """Section 11.3: recorded and not achieved is allowed. Requiring
    verification of a miss would block a model for having a quiet month.
    """
    affiliate = _affiliate(db)
    _guaranteed(db, affiliate)
    _target(db, affiliate, required=(8, 5), actual=(1, 1), verified=False)

    result = calculate_month(db, affiliate, MONTH)

    assert result.is_payable is True
    assert result.blockers == []


def test_a_commission_model_is_unaffected_by_a_missing_target(db):
    """Section 15: targets are informational for them. Blocking their month over a
    management figure would stop a payment for a reason that has nothing to do
    with what they are owed.
    """
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    _earned(db, affiliate, "1", 200_000)

    result = calculate_month(db, affiliate, MONTH)

    assert result.target_achieved is None
    assert result.is_payable is True
    assert result.payout_piastres == 20_000


def test_a_fixed_salary_model_is_unaffected_too(db):
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

    assert result.is_payable is True
    assert result.payout_piastres == 500_000


def test_re_recording_actuals_re_blocks_the_month(db):
    """A correction clears the verification, so the guarantee stops applying
    until somebody confirms the new numbers. That is the point of clearing it.
    """
    from app.services.targets import record_actuals

    affiliate = _affiliate(db)
    _guaranteed(db, affiliate)
    target = _target(db, affiliate, actual=(8, 5), verified=True)
    assert calculate_month(db, affiliate, MONTH).is_payable is True

    record_actuals(db, target, videos=9, stories=6)

    result = calculate_month(db, affiliate, MONTH)
    assert TARGETS_UNVERIFIED in result.blockers


def test_a_guaranteed_house_account_is_still_owed_nothing(db):
    affiliate = _affiliate(db, "House", kind=AccountKind.HOUSE)
    _guaranteed(db, affiliate, base=800_000)
    _target(db, affiliate, actual=(8, 5), verified=True)

    result = calculate_month(db, affiliate, MONTH)

    assert result.payout_piastres == 0
    assert result.is_payable is False


def test_another_months_target_does_not_decide_this_one(db):
    """Each month stands alone. April's guarantee must not turn on May's
    posting.
    """
    from app.services.targets import record_actuals, set_requirements, verify

    affiliate = _affiliate(db)
    _guaranteed(db, affiliate)
    other = set_requirements(db, affiliate, "2026-05", videos=8, stories=5)
    record_actuals(db, other, videos=8, stories=5)
    verify(db, other)

    result = calculate_month(db, affiliate, MONTH)

    assert NO_TARGET in result.blockers
