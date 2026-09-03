"""What a model is told when a settled month is corrected.

A month that has been agreed is meant to be final. When a correction moves one
somebody has already been paid for, the number quietly becoming a different
number is the worst possible way for them to find out.

**Two sentences, on two months, deliberately.** One month was recalculated; a
*different* month is carrying money that did not come from it. Explaining both
on the later month would leave the earlier one showing a changed figure with
nothing attached to it - which is the silence this exists to remove.
"""

from datetime import datetime, timezone

import pytest

from app.core.passwords import hash_password
from app.models.attributed_orders import AttributedOrder, CommissionState
from app.models.compensation import CompensationType
from app.models.identity import UserAccount
from app.models.orders import OrderIndex
from app.models.payments import AdjustmentType
from app.services.affiliates import create_affiliate
from app.services.compensation import set_terms
from app.services.payments import adjust, record_payment
from app.services.payroll import approve_month, reopen_month
from app.services.portal import my_month

MAY = "2026-05"
JULY = "2026-07"


@pytest.fixture(autouse=True)
def _go_live(monkeypatch):
    """A month before go-live cannot be approved at all, and both months here
    are historical without this."""
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)


def _affiliate(db, name="Nour Mahmoud", email="nour@example.com"):
    account = UserAccount(
        email=email,
        password_hash=hash_password("quiet-harbour-lantern"),
        status="active",
        display_name=name,
    )
    db.add(account)
    db.flush()
    affiliate = create_affiliate(db, user_account_id=account.id, name=name)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    db.flush()
    return affiliate


def _order(db, affiliate, order_id, base, month):
    db.add(
        OrderIndex(
            shopify_order_id=order_id,
            order_number=f"#{order_id}",
            placed_at=datetime(2026, 5, 15, 12, tzinfo=timezone.utc),
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
    db.add(
        AttributedOrder(
            shopify_order_id=order_id,
            affiliate_id=affiliate.id,
            business_month=month,
            commission_base_piastres=base,
            commission_state=CommissionState.EARNED,
        )
    )
    db.flush()


def _rate(db, affiliate, rate_bp):
    """Rewrite the arrangement in place - the one way to change a rate now."""
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=rate_bp,
    )
    db.flush()


# ── The month that changed says so ──────────────────────────────────────────


def test_a_month_agreed_once_says_nothing_about_being_recalculated(db):
    """The ordinary case must stay silent. A notice on every settled month
    would train somebody to ignore the one that matters.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 2_000_000, MAY)
    approve_month(db, affiliate, MAY)
    db.flush()

    assert my_month(db, affiliate, MAY)["recalculated"] is None


def test_a_corrected_month_carries_both_figures(db):
    """"It changed" without the old number is not something anybody can check
    against their own record.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 2_000_000, MAY)
    approve_month(db, affiliate, MAY)
    db.flush()

    reopen_month(db, affiliate, MAY, reason="rate was recorded wrongly")
    db.flush()
    _rate(db, affiliate, 1200)
    approve_month(db, affiliate, MAY)
    db.flush()

    changed = my_month(db, affiliate, MAY)["recalculated"]
    assert changed is not None
    assert changed["was_piastres"] == 200_000
    assert changed["now_piastres"] == 240_000


def test_a_correction_that_changed_nothing_says_nothing(db):
    """Reopened, looked at, and agreed at the same figure. Announcing a
    recalculation over an unchanged number invites a question with no answer.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 2_000_000, MAY)
    approve_month(db, affiliate, MAY)
    db.flush()

    reopen_month(db, affiliate, MAY, reason="checking something")
    db.flush()
    approve_month(db, affiliate, MAY)
    db.flush()

    assert my_month(db, affiliate, MAY)["recalculated"] is None


def test_a_month_that_fell_is_reported_the_same_way(db):
    """Downwards matters more, not less - there is no transfer to attach the
    news to, so nothing in their bank account will explain it.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 2_000_000, MAY)
    approve_month(db, affiliate, MAY)
    db.flush()

    reopen_month(db, affiliate, MAY, reason="rate was too high")
    db.flush()
    _rate(db, affiliate, 800)
    approve_month(db, affiliate, MAY)
    db.flush()

    changed = my_month(db, affiliate, MAY)["recalculated"]
    assert changed["was_piastres"] == 200_000
    assert changed["now_piastres"] == 160_000


# ── The month carrying the money says where it came from ────────────────────


def test_a_month_carrying_a_credit_names_the_month_it_came_from(db):
    """Without this, July simply contains more money than its own orders
    explain, which reads as an error in the platform.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 2_000_000, MAY)
    may = approve_month(db, affiliate, MAY)
    _order(db, affiliate, "2", 3_000_000, JULY)
    approve_month(db, affiliate, JULY)
    # A credit carries an excess (ADR 0035): May agreed E£2,000 and was sent
    # E£2,600.
    record_payment(
        db, affiliate, amount_piastres=260_000, allocations={may.id: 260_000}
    )
    db.flush()

    adjust(
        db,
        affiliate,
        kind=AdjustmentType.CREDIT,
        source_month=MAY,
        destination_month=JULY,
        amount_piastres=60_000,
        reason="overpaid in May after the rate was corrected",
    )
    db.flush()

    credits = my_month(db, affiliate, JULY)["credited_from"]
    assert credits == [{"month": MAY, "piastres": 60_000}]


def test_the_month_the_credit_came_from_does_not_claim_to_carry_it(db):
    """The two sentences sit on two different months on purpose. May was
    recalculated; July is carrying the difference.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 2_000_000, MAY)
    may = approve_month(db, affiliate, MAY)
    _order(db, affiliate, "2", 3_000_000, JULY)
    approve_month(db, affiliate, JULY)
    # A credit carries an excess (ADR 0035): May agreed E£2,000 and was sent
    # E£2,600.
    record_payment(
        db, affiliate, amount_piastres=260_000, allocations={may.id: 260_000}
    )
    db.flush()

    adjust(
        db,
        affiliate,
        kind=AdjustmentType.CREDIT,
        source_month=MAY,
        destination_month=JULY,
        amount_piastres=60_000,
        reason="overpaid in May",
    )
    db.flush()

    assert my_month(db, affiliate, MAY)["credited_from"] == []


def test_an_absorbed_overpayment_lands_on_nobodys_month(db):
    """A write-off goes nowhere - that is what absorbing means. No month
    should claim to be carrying money HBA decided to swallow.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 2_000_000, MAY)
    approve_month(db, affiliate, MAY)
    _order(db, affiliate, "2", 3_000_000, JULY)
    approve_month(db, affiliate, JULY)
    db.flush()

    adjust(
        db,
        affiliate,
        kind=AdjustmentType.WRITEOFF,
        source_month=MAY,
        amount_piastres=60_000,
        reason="HBA absorbs it",
    )
    db.flush()

    assert my_month(db, affiliate, JULY)["credited_from"] == []
    assert my_month(db, affiliate, MAY)["credited_from"] == []
