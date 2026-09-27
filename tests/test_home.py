"""Her Home in one read - batch L, the owner's decisions of 27 September.

Three things this file holds:

    the comparison is like for like   1st-10th against 1st-10th, not a
                                      finished month against a young one
    the chips add up to the uses      a cancelled order is a use no chip
                                      used to show (FITBROS10, September)
    sales mean one thing              the whole-month sum is Home's figure
"""

from datetime import date, datetime, timezone

from app.core.passwords import hash_password
from app.models.affiliates import AccountKind
from app.models.attributed_orders import AttributedOrder, CommissionState
from app.models.compensation import CompensationType
from app.models.identity import UserAccount
from app.models.orders import OrderIndex
from app.services.affiliates import create_affiliate
from app.services.codes import register_code
from app.services.compensation import set_terms
from app.services.home import comparison, order_outcomes, sales_through, share_link
from app.services.performance import uses_for
from app.services.portal import my_month
from app.services.shopify.fulfilment import DELIVERED, FAILED, IN_FLIGHT

SEPTEMBER = "2026-09"
AUGUST = "2026-08"


def _model(db, name="Nour"):
    account = UserAccount(
        email=f"{name.lower()}@example.com",
        password_hash=hash_password("quiet-harbour-lantern"),
        status="active",
        display_name=name,
    )
    db.add(account)
    db.flush()
    affiliate = create_affiliate(
        db, user_account_id=account.id, name=name, account_kind=AccountKind.MODEL
    )
    register_code(db, affiliate, f"{name.upper()}10", "2026-01")
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    db.flush()
    return affiliate


def _order(
    db, affiliate, order_id, base, *, placed, state, delivery=DELIVERED, cancelled=False
):
    """An order placed at `placed` (UTC), in the business month it falls in."""
    month = placed.strftime("%Y-%m")
    db.add(
        OrderIndex(
            shopify_order_id=order_id,
            order_number=f"#{order_id}",
            placed_at=placed,
            business_month=month,
            discount_codes=[f"{affiliate.name.upper()}10"],
            subtotal_piastres=base,
            total_piastres=base,
            shipping_piastres=0,
            tax_piastres=0,
            currency="EGP",
            delivery_state=delivery,
            cancelled_at=placed if cancelled else None,
            financial_status="voided" if cancelled else "paid",
        )
    )
    db.flush()
    db.add(
        AttributedOrder(
            shopify_order_id=order_id,
            affiliate_id=affiliate.id,
            business_month=month,
            commission_base_piastres=base,
            commission_state=state,
        )
    )
    db.flush()


def _utc(y, m, d, h=12):
    return datetime(y, m, d, h, tzinfo=timezone.utc)


# -- Like for like ------------------------------------------------------------


def test_a_running_month_is_compared_with_the_same_days_of_the_last(db):
    """The owner's example: on the 10th, the 1st-10th of each month. August's
    big finish after the 10th must not count against a September ten days old."""
    nour = _model(db)
    _order(db, nour, "a1", 100_000, placed=_utc(2026, 8, 3), state=CommissionState.EARNED)
    _order(db, nour, "a2", 900_000, placed=_utc(2026, 8, 25), state=CommissionState.EARNED)
    _order(db, nour, "s1", 150_000, placed=_utc(2026, 9, 6), state=CommissionState.PENDING)

    result = comparison(db, nour.id, SEPTEMBER, date(2026, 9, 10))

    assert result["running"] is True
    assert result["window"] == "1–10 Aug"
    assert result["before_piastres"] == 100_000
    assert result["now_piastres"] == 150_000
    assert result["change_pct"] == 50


def test_the_day_is_cairos_not_utcs(db):
    """23:00 UTC on the 10th is already the 11th in Cairo, so it is outside a
    1st-10th window."""
    nour = _model(db)
    _order(db, nour, "a1", 100_000, placed=_utc(2026, 8, 5), state=CommissionState.EARNED)
    _order(db, nour, "a2", 500_000, placed=_utc(2026, 8, 10, 23), state=CommissionState.EARNED)

    result = comparison(db, nour.id, SEPTEMBER, date(2026, 9, 10))

    assert result["before_piastres"] == 100_000


def test_a_shorter_previous_month_stops_at_its_last_day(db):
    """The 31st against a 30-day month compares with all 30 of its days."""
    nour = _model(db)
    _order(db, nour, "s1", 100_000, placed=_utc(2026, 9, 30), state=CommissionState.EARNED)
    _order(db, nour, "o1", 100_000, placed=_utc(2026, 10, 2), state=CommissionState.EARNED)

    result = comparison(db, nour.id, "2026-10", date(2026, 10, 31))

    assert result["window"] == "1–30 Sep"
    assert result["before_piastres"] == 100_000


def test_a_finished_month_is_compared_whole(db):
    nour = _model(db)
    _order(db, nour, "a1", 200_000, placed=_utc(2026, 8, 25), state=CommissionState.EARNED)
    _order(db, nour, "j1", 100_000, placed=_utc(2026, 7, 28), state=CommissionState.EARNED)

    result = comparison(db, nour.id, AUGUST, date(2026, 9, 27))

    assert result["running"] is False
    assert result["window"] == "all of Jul"
    assert result["change_pct"] == 100


def test_nothing_last_month_means_no_comparison(db):
    """A percentage of nothing is not a number."""
    nour = _model(db)
    _order(db, nour, "s1", 150_000, placed=_utc(2026, 9, 6), state=CommissionState.EARNED)

    assert comparison(db, nour.id, SEPTEMBER, date(2026, 9, 10)) is None


def test_a_failed_delivery_is_not_a_sale_in_the_comparison(db):
    nour = _model(db)
    _order(db, nour, "a1", 100_000, placed=_utc(2026, 8, 3), state=CommissionState.EARNED)
    _order(
        db, nour, "a2", 400_000, placed=_utc(2026, 8, 4),
        state=CommissionState.VOID, delivery=FAILED,
    )

    assert sales_through(db, nour.id, AUGUST, date(2026, 8, 10)) == 100_000


def test_whole_month_sales_are_homes_sales_figure(db):
    """One meaning of *sales*: the comparison's whole month equals the figure
    Home prints as sales."""
    nour = _model(db)
    _order(db, nour, "s1", 120_000, placed=_utc(2026, 9, 2), state=CommissionState.EARNED)
    _order(
        db, nour, "s2", 80_000, placed=_utc(2026, 9, 3),
        state=CommissionState.PENDING, delivery=IN_FLIGHT,
    )
    _order(
        db, nour, "s3", 50_000, placed=_utc(2026, 9, 4),
        state=CommissionState.VOID, delivery=FAILED,
    )

    assert sales_through(db, nour.id, SEPTEMBER, None) == (
        my_month(db, nour, SEPTEMBER)["sales"]["counted_piastres"]
    )


# -- Every order has a place ---------------------------------------------------


def test_the_outcomes_add_up_to_the_uses(db):
    """FITBROS10's September in miniature: delivered, pending and cancelled
    orders are all uses; only the chips used to leave the cancelled out."""
    nour = _model(db)
    _order(db, nour, "d1", 100_000, placed=_utc(2026, 9, 2), state=CommissionState.EARNED)
    _order(db, nour, "d2", 100_000, placed=_utc(2026, 9, 3), state=CommissionState.EARNED)
    _order(
        db, nour, "p1", 100_000, placed=_utc(2026, 9, 4),
        state=CommissionState.PENDING, delivery=IN_FLIGHT,
    )
    _order(
        db, nour, "c1", 100_000, placed=_utc(2026, 9, 5),
        state=CommissionState.VOID, delivery=None, cancelled=True,
    )
    _order(
        db, nour, "f1", 100_000, placed=_utc(2026, 9, 6),
        state=CommissionState.VOID, delivery=FAILED,
    )

    outcomes = order_outcomes(db, nour.id, SEPTEMBER)

    assert outcomes == {
        "delivered": 2, "pending": 1, "failed": 1, "cancelled": 1, "refunded": 0,
    }
    uses = uses_for(db, nour, SEPTEMBER)
    assert uses == 4
    assert uses == sum(outcomes.values()) - outcomes["failed"]


# -- Sharing -------------------------------------------------------------------


def test_the_share_link_is_shopifys_discount_link(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "shopify_shop_domain", "https://hba-wear.myshopify.com/")

    assert share_link(db, "NOUR10") == "https://hba-wear.myshopify.com/discount/NOUR10"
    assert share_link(db, None) is None


def test_no_shop_means_no_link(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "shopify_shop_domain", "")

    assert share_link(db, "NOUR10") is None
