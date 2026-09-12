"""What the owner is told about a month.

Phase 07B, A01. The property this file exists to hold is arithmetic rather than
wording: **the parts of an expected payout add up to the payout**, on every
arrangement and in every mixture of them.

A month's figure is exact until one half-up rounding at the end (ADR 0003,
0004). Three components rounded separately and added would report a total the
payroll screen disagrees with by a pound — on the screen whose only job is to
say how much money to find.
"""

from datetime import datetime, timezone

import pytest

from app.core.passwords import hash_password
from app.models.affiliates import AccountKind
from app.models.attributed_orders import AttributedOrder, CommissionState
from app.models.compensation import CompensationType
from app.models.identity import UserAccount
from app.models.orders import OrderIndex
from app.services.affiliates import create_affiliate
from app.services.codes import register_code
from app.services.compensation import set_terms
from app.services.overview import month_summary
from app.services.shopify.fulfilment import DELIVERED
from app.services.targets import record_actuals, set_requirements, verify

AUGUST = "2026-08"


@pytest.fixture(autouse=True)
def _go_live(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)


@pytest.fixture(autouse=True)
def _working_month(monkeypatch):
    monkeypatch.setattr(
        "app.services.portal.working_month", lambda: AUGUST, raising=True
    )


def _model(db, name, kind=AccountKind.MODEL, **terms):
    account = UserAccount(
        email=f"{name.lower()}@example.com",
        password_hash=hash_password("quiet-harbour-lantern"),
        status="active",
        display_name=name,
    )
    db.add(account)
    db.flush()
    affiliate = create_affiliate(
        db, user_account_id=account.id, name=name, account_kind=kind
    )
    # An onboarded model. `create_affiliate` leaves a new one *pending* -
    # applied, not yet approved - and A01 counts the ones actually earning.
    affiliate.status = "active"
    register_code(db, affiliate, f"{name.upper()}10", "2026-01")
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=terms.pop("compensation_type", CompensationType.COMMISSION),
        commission_rate_bp=terms.pop("commission_rate_bp", 1000),
        **terms,
    )
    db.flush()
    return affiliate


def _order(db, affiliate, order_id, base, *, month=AUGUST):
    db.add(
        OrderIndex(
            shopify_order_id=order_id,
            order_number=f"#{order_id}",
            placed_at=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
            business_month=month,
            discount_codes=[f"{affiliate.name.upper()}10"],
            subtotal_piastres=base,
            total_piastres=base,
            shipping_piastres=0,
            tax_piastres=0,
            currency="EGP",
            delivery_state=DELIVERED,
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


def _hit_target(db, affiliate, month=AUGUST):
    target = set_requirements(db, affiliate, month, videos=4, stories=4)
    record_actuals(db, target, videos=4, stories=4)
    verify(db, target)
    db.flush()


# -- The breakdown adds up -----------------------------------------------------


def test_a_commission_month_is_all_commission(db):
    affiliate = _model(db, "Nour")
    _order(db, affiliate, "1", 2_000_000)

    found = month_summary(db, AUGUST).breakdown

    assert found.payout_piastres == 200_000
    assert found.commission_piastres == 200_000
    assert found.fixed_piastres == 0
    assert found.guarantee_top_up_piastres == 0


def test_a_salary_and_commission_month_reports_both(db):
    """`fixed_plus_commission` pays **both** - the arrangement this codebase
    warns is most often got wrong, so the breakdown names each half.
    """
    affiliate = _model(
        db,
        "Nour",
        compensation_type=CompensationType.FIXED_PLUS_COMMISSION,
        fixed_amount_piastres=500_000,
    )
    _order(db, affiliate, "1", 2_000_000)

    found = month_summary(db, AUGUST).breakdown

    assert found.fixed_piastres == 500_000
    assert found.commission_piastres == 200_000
    assert found.payout_piastres == 700_000


def test_a_guarantee_that_applied_shows_what_the_floor_added(db):
    """She sold E£1,000 of commission against an E£3,000 floor. The owner needs
    to see that E£2,000 of the payout is the guarantee rather than sales - it
    is the figure that answers *what is this costing us beyond what they sold*.
    """
    affiliate = _model(
        db,
        "Nour",
        compensation_type=CompensationType.BASE_GUARANTEE,
        base_amount_piastres=300_000,
    )
    _order(db, affiliate, "1", 1_000_000)
    _hit_target(db, affiliate)

    found = month_summary(db, AUGUST).breakdown

    assert found.payout_piastres == 300_000
    assert found.commission_piastres == 100_000
    assert found.guarantee_top_up_piastres == 200_000


def test_a_guarantee_she_beat_adds_no_top_up(db):
    affiliate = _model(
        db,
        "Nour",
        compensation_type=CompensationType.BASE_GUARANTEE,
        base_amount_piastres=100_000,
    )
    _order(db, affiliate, "1", 5_000_000)
    _hit_target(db, affiliate)

    found = month_summary(db, AUGUST).breakdown

    assert found.payout_piastres == 500_000
    assert found.guarantee_top_up_piastres == 0
    assert found.commission_piastres == 500_000


@pytest.mark.parametrize("base", [1_000_001, 1_500_555, 3_333_333, 7_777_777])
def test_the_parts_always_add_to_the_payout(db, base):
    """**The property, across arrangements and awkward figures.**

    A payout is exact until one half-up rounding. Parts rounded separately
    would drift, and the owner's total would stop matching the payroll screen -
    which is the one comparison somebody will make.
    """
    commission = _model(db, "Nour")
    salaried = _model(
        db,
        "Sara",
        compensation_type=CompensationType.FIXED_PLUS_COMMISSION,
        fixed_amount_piastres=333_333,
    )
    guaranteed = _model(
        db,
        "Mona",
        compensation_type=CompensationType.BASE_GUARANTEE,
        base_amount_piastres=250_000,
    )
    for index, affiliate in enumerate((commission, salaried, guaranteed)):
        _order(db, affiliate, f"o{index}", base)
    _hit_target(db, guaranteed)

    found = month_summary(db, AUGUST).breakdown

    assert (
        found.commission_piastres
        + found.fixed_piastres
        + found.guarantee_top_up_piastres
        == found.payout_piastres
    )


def test_a_blocked_month_contributes_no_money_and_is_counted(db):
    """A figure that cannot be approved is not money to find. It is a row to
    fix, and the two must never be added together.
    """
    affiliate = _model(
        db,
        "Nour",
        compensation_type=CompensationType.BASE_GUARANTEE,
        base_amount_piastres=300_000,
    )
    _order(db, affiliate, "1", 1_000_000)
    # No target recorded, so §11.3 blocks the month.

    found = month_summary(db, AUGUST)

    assert found.blocked == 1
    assert found.ready == 0
    assert found.breakdown.payout_piastres == 0


# -- Who is in it --------------------------------------------------------------


def test_a_house_account_is_in_no_count_no_total_and_no_board(db):
    """§8, §17. A house code has real sales and no payee."""
    model = _model(db, "Nour")
    house = _model(db, "House", kind=AccountKind.HOUSE)
    _order(db, model, "1", 1_000_000)
    _order(db, house, "2", 9_000_000)

    found = month_summary(db, AUGUST)

    assert found.active_models == 1
    assert [row["name"] for row in found.top] == ["Nour"]
    assert found.sales_piastres == 1_000_000


def test_the_top_three_share_a_place_rather_than_cutting_one_off(db):
    """D03's rule, and the reason the list is by *place* rather than by count:
    three models level at the top are all shown, because a list that kept two
    of them would have picked a winner the rule did not.
    """
    for name in ("Nour", "Sara", "Mona", "Aya"):
        affiliate = _model(db, name)
        _order(db, affiliate, f"{name}-1", 1_000_000 if name != "Aya" else 10_000)

    found = month_summary(db, AUGUST)

    assert [row["rank"] for row in found.top] == [1, 1, 1]
    assert "Aya" not in [row["name"] for row in found.top]


def test_a_month_nobody_sold_in_has_an_empty_board_rather_than_zeroes(db):
    """A leaderboard of zeroes all sharing first place is arithmetically true
    and says nothing. Nobody sold, so nobody is top.
    """
    _model(db, "Nour")

    assert month_summary(db, AUGUST).top == []


def test_content_needing_review_is_counted_by_why(db):
    """A01, and D08's distinction: two of the three are HBA's own work rather
    than a verdict on a model, so they are counted separately.
    """
    nothing_asked = _model(db, "Nour")
    _order(db, nothing_asked, "1", 1_000_000)

    found = month_summary(db, AUGUST)

    assert found.needs_review.get("no_target") == 1


# -- W11: which products sell through the codes --------------------------------


def _line(db, order_id, *, product_id, title, quantity, paid, listed=None):
    """A line on an order, with what was actually paid for it."""
    from app.models.catalogue import OrderLineItem

    db.add(
        OrderLineItem(
            shopify_line_item_id=f"{order_id}-{title}",
            shopify_order_id=order_id,
            shopify_product_id=product_id,
            title=title,
            quantity=quantity,
            discounted_total_piastres=paid,
            original_total_piastres=listed if listed is not None else paid,
        )
    )
    db.flush()


def test_products_are_ranked_by_what_was_actually_paid(db):
    """**W11 rules out the easy version.** Summing undiscounted prices would
    credit the shop with money it never took - on a ten per cent code that is a
    ten per cent lie on every row.
    """
    from app.services.performance import top_products

    affiliate = _model(db, "Nour")
    _order(db, affiliate, "1", 1_000_000)
    _line(db, "1", product_id="P1", title="Trousers", quantity=1,
          paid=400_000, listed=500_000)
    _line(db, "1", product_id="P2", title="Blouse", quantity=1,
          paid=450_000, listed=460_000)

    found = top_products(db, AUGUST)["products"]

    # By what was paid, the blouse leads. By the list price the trousers would.
    assert [row.title for row in found] == ["Blouse", "Trousers"]
    assert found[0].sales_piastres == 450_000


def test_quantities_are_counted(db):
    from app.services.performance import top_products

    affiliate = _model(db, "Nour")
    _order(db, affiliate, "1", 1_000_000)
    _line(db, "1", product_id="P1", title="Trousers", quantity=3, paid=300_000)

    found = top_products(db, AUGUST)["products"][0]

    assert found.quantity == 3
    assert found.sales_piastres == 300_000


def test_a_renamed_product_is_still_one_product(db):
    """Grouped by the stable id, never by the name. A product renamed between
    two orders is the same product, and two products can share a name.
    """
    from app.services.performance import top_products

    affiliate = _model(db, "Nour")
    _order(db, affiliate, "1", 1_000_000)
    _order(db, affiliate, "2", 1_000_000)
    _line(db, "1", product_id="P1", title="Wide-leg trousers", quantity=1,
          paid=100_000)
    _line(db, "2", product_id="P1", title="Wide leg trouser", quantity=1,
          paid=100_000)

    found = top_products(db, AUGUST)["products"]

    assert len(found) == 1
    assert found[0].quantity == 2


def test_only_counted_orders_sell_anything(db):
    """A pending order has not sold yet and a failed one never will. The same
    basis every other screen calls sales.
    """
    from app.services.performance import top_products

    affiliate = _model(db, "Nour")
    _order(db, affiliate, "1", 1_000_000)
    pending = AttributedOrder(
        shopify_order_id="2",
        affiliate_id=affiliate.id,
        business_month=AUGUST,
        commission_base_piastres=900_000,
        commission_state=CommissionState.PENDING,
    )
    db.add(
        OrderIndex(
            shopify_order_id="2",
            order_number="#2",
            placed_at=datetime(2026, 8, 5, 12, tzinfo=timezone.utc),
            business_month=AUGUST,
            discount_codes=["NOUR10"],
            subtotal_piastres=900_000,
            total_piastres=900_000,
            shipping_piastres=0,
            tax_piastres=0,
            currency="EGP",
            delivery_state=DELIVERED,
        )
    )
    db.flush()
    db.add(pending)
    db.flush()
    _line(db, "1", product_id="P1", title="Counted", quantity=1, paid=100_000)
    _line(db, "2", product_id="P2", title="Still travelling", quantity=1,
          paid=900_000)

    found = top_products(db, AUGUST)["products"]

    assert [row.title for row in found] == ["Counted"]


def test_a_product_deleted_from_shopify_is_reported_not_dropped(db):
    """It has no id to group by, and dropping it would make this screen's
    total disagree with the sales figures beside it.
    """
    from app.services.performance import top_products

    affiliate = _model(db, "Nour")
    _order(db, affiliate, "1", 1_000_000)
    _line(db, "1", product_id="P1", title="Still listed", quantity=1,
          paid=100_000)
    _line(db, "1", product_id=None, title="Deleted", quantity=1, paid=60_000)

    found = top_products(db, AUGUST)

    assert [row.title for row in found["products"]] == ["Still listed"]
    assert found["no_longer_in_shopify_piastres"] == 60_000
    assert found["total_piastres"] == 160_000


def test_selling_a_product_does_not_require_owning_it(db):
    """**W11's first sentence**, and the distinction this analytic exists to
    keep: selling through a code, owning something from the wardrobe and being
    asked to feature it are three different things. She never received this.
    """
    from app.services.performance import top_products

    affiliate = _model(db, "Nour")
    _order(db, affiliate, "1", 1_000_000)
    _line(db, "1", product_id="P9", title="Never sent to her", quantity=1,
          paid=100_000)

    assert top_products(db, AUGUST)["products"][0].shopify_product_id == "P9"


# -- the content panel names the models, rather than counting them -----------
#
# C1 of the design-parity correction. The approved Home shows a table of
# models with videos, stories and last update; what shipped showed two lines
# of aggregate counts, which tells the owner a number and then makes her go
# and find out which models it means.


def test_the_content_panel_carries_a_row_for_every_model(db):
    """**The API answers for everybody; the panel reviews six.**

    The approved Home shows only the models needing review, worst first, at
    most six — a model who has produced everything asked of her is not
    something to review, and listing her pushes somebody who needs chasing off
    the bottom.

    That narrowing belongs to the screen, not to this read: the same rows feed
    the roster's content column, which *does* answer for every model. Filtering
    here would make the two disagree and leave no way to ask the broader
    question at all.
    """
    first = _model(db, "Nour")
    second = _model(db, "Salma")
    set_requirements(db, first, AUGUST, videos=6, stories=12)
    set_requirements(db, second, AUGUST, videos=6, stories=12)
    db.flush()

    summary = month_summary(db, AUGUST)

    assert [row["name"] for row in summary.content] == ["Nour", "Salma"]
    assert all(row["required_videos"] == 6 for row in summary.content)


def test_nothing_asked_for_is_not_the_same_as_nothing_produced(db):
    """A missing target row and a row of zeroes mean opposite things.

    *Nobody asked her for anything* is HBA's own omission; *she has produced
    nothing* is a fact about her month. Collapsing both to `0` would put a
    model in front of the owner as behind when the gap is HBA's.
    """
    asked = _model(db, "Nour")
    unasked = _model(db, "Salma")
    target = set_requirements(db, asked, AUGUST, videos=6, stories=12)
    record_actuals(db, target, videos=0, stories=0)
    db.flush()

    rows = {row["name"]: row for row in month_summary(db, AUGUST).content}

    assert rows["Nour"]["required_videos"] == 6
    assert rows["Nour"]["actual_videos"] == 0, "asked, and has produced none"
    assert rows["Salma"]["required_videos"] is None, "nobody asked her"
    assert rows["Salma"]["actual_videos"] is None


def test_the_least_done_comes_first_and_the_untouched_before_that(db):
    """**Worst first**, because this panel exists to be acted on.

    Alphabetical order would put whoever is fine at the top on a good day and
    bury the model who has not started.
    """
    done = _model(db, "Aya")
    started = _model(db, "Nour")
    untouched = _model(db, "Salma")
    for affiliate, videos in ((done, 6), (started, 1)):
        target = set_requirements(db, affiliate, AUGUST, videos=6, stories=12)
        record_actuals(db, target, videos=videos, stories=0)
    set_requirements(db, untouched, AUGUST, videos=6, stories=12)
    db.flush()

    order = [row["name"] for row in month_summary(db, AUGUST).content]

    assert order == ["Salma", "Nour", "Aya"], "untouched, least done, most done"


def test_a_recorded_month_carries_when_it_was_last_touched(db):
    """The design's *last update* column, and its *No update yet*.

    A stale count read as current is D08's whole worry: it must be possible to
    tell *nothing happened this week* from *nobody wrote it down*.
    """
    affiliate = _model(db, "Nour")
    target = set_requirements(db, affiliate, AUGUST, videos=6, stories=12)
    record_actuals(
        db,
        target,
        videos=2,
        stories=1,
        recorded_at=datetime(2026, 8, 14, 9, tzinfo=timezone.utc),
    )
    db.flush()

    row = month_summary(db, AUGUST).content[0]

    assert row["last_update"].startswith("2026-08-14")


def test_the_content_panel_leaves_house_accounts_out(db):
    """A house code has sales and nobody to ask for a video.

    It is excluded once, where every other figure excludes it, so it cannot
    appear here as a model who has recorded nothing.
    """
    _model(db, "Nour")
    _model(db, "Shop", kind=AccountKind.HOUSE)
    db.flush()

    assert [row["name"] for row in month_summary(db, AUGUST).content] == ["Nour"]


def test_the_leaderboard_carries_the_code_she_had_that_month(db):
    """The design shows the discount code under the name.

    Read for the month rather than as *her code now*, so a code that changes
    hands cannot relabel a month that is already settled.
    """
    affiliate = _model(db, "Nour")
    _order(db, affiliate, "1", 2_000_000)
    db.flush()

    assert month_summary(db, AUGUST).top[0]["code"] == "NOUR10"


def test_the_sales_card_says_how_many_models_it_counted(db):
    """The export writes the denominator under the figure.

    A total with no denominator cannot tell a quiet month from a feed that
    stopped, and those are the two readings the owner most needs kept apart.
    Counted on sales rather than on status: a model who is active and sold
    nothing did not contribute to the number above it.
    """
    selling = _model(db, "Nour")
    _model(db, "Salma")
    _order(db, selling, "1", 2_000_000)
    db.flush()

    summary = month_summary(db, AUGUST)

    assert summary.active_models == 2
    assert summary.selling_models == 1


# -- The year under the month (the chart at the foot of the approved Home) ----


def test_the_year_runs_january_to_the_month_being_looked_at(db):
    """Eleven bars for November, eight for August. The year, to date.

    Not a rolling twelve: the export's axis reads *January – November 2026*,
    and a chart that starts in the middle of last year answers a question
    nobody asked while hiding the one people do — how this year is going.
    """
    from app.services.overview import sales_by_month

    model = _model(db, "Nour", compensation_type=CompensationType.COMMISSION,
                   commission_rate_bp=1000)
    _order(db, model, 5001, 300_00, month="2026-03")
    _order(db, model, 5002, 700_00, month=AUGUST)

    year = sales_by_month(db, AUGUST)

    assert [row["month"] for row in year] == [
        f"2026-{index:02d}" for index in range(1, 9)
    ]


def test_a_month_with_no_orders_is_a_zero_rather_than_a_gap(db):
    """A chart that drops an empty month draws it as though it never was."""
    from app.services.overview import sales_by_month

    model = _model(db, "Nour", compensation_type=CompensationType.COMMISSION,
                   commission_rate_bp=1000)
    _order(db, model, 5003, 500_00, month=AUGUST)

    year = {row["month"]: row["sales_piastres"] for row in sales_by_month(db, AUGUST)}

    assert year["2026-03"] == 0
    assert year[AUGUST] == 500_00


def test_the_year_counts_generated_sales_and_not_a_house_code(db):
    """*Sales generated by models.* A house code has sales and no model."""
    from app.services.overview import sales_by_month

    model = _model(db, "Nour", compensation_type=CompensationType.COMMISSION,
                   commission_rate_bp=1000)
    house = _model(db, "House", kind=AccountKind.HOUSE)
    _order(db, model, 5004, 400_00)
    _order(db, house, 5005, 900_00)

    year = {row["month"]: row["sales_piastres"] for row in sales_by_month(db, AUGUST)}

    assert year[AUGUST] == 400_00


def test_the_year_matches_the_figure_on_the_sales_card(db):
    """One number, said twice on one screen, must be one number.

    The card and the chart's own month are the same fact — *what models
    generated in this month* — and a reader who saw them disagree would be
    right to stop trusting both.
    """
    from app.services.overview import sales_by_month

    model = _model(db, "Nour", compensation_type=CompensationType.COMMISSION,
                   commission_rate_bp=1000)
    _order(db, model, 5006, 650_00)
    _hit_target(db, model)

    card = month_summary(db, AUGUST)
    year = {row["month"]: row["sales_piastres"] for row in sales_by_month(db, AUGUST)}

    assert year[AUGUST] == card.sales_piastres
