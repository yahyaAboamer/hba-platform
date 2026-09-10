"""How often her code was used, where she stands, and whether she is keeping up.

Phase 07A. D03 and D08, both answered 11 September 2026, in the owner's own
figures wherever he gave them.

The two distinctions this file exists to hold:

    a use is a delivery outcome        not a financial one
    unrecorded is not behind           it measures HBA, not her
"""

from datetime import date, datetime, timezone

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
from app.services.pace import (
    BEHIND,
    NO_TARGET,
    NOT_RECORDED,
    NOT_STARTED,
    ON_TRACK,
    expected_by,
    pace_for,
    week_bounds,
)
from app.services.performance import month_performance, rank, uses_for
from app.services.shopify.fulfilment import DELIVERED, FAILED, IN_FLIGHT
from app.services.targets import get_target, record_actuals, set_requirements

AUGUST = "2026-08"


def _model(db, name):
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


def _order(db, affiliate, order_id, base, *, delivery, state, month=AUGUST):
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
            delivery_state=delivery,
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


# -- D03: what a use is --------------------------------------------------------


def test_a_delivered_order_is_a_use_and_a_failed_one_is_not(db):
    affiliate = _model(db, "Nour")
    _order(db, affiliate, "1", 100_000, delivery=DELIVERED, state=CommissionState.EARNED)
    _order(db, affiliate, "2", 100_000, delivery=FAILED, state=CommissionState.VOID)

    assert uses_for(db, affiliate, AUGUST) == 1


def test_anything_in_between_counts_until_it_resolves(db):
    """The owner's words. An order still moving is a use; it stops being one
    only if the delivery fails.
    """
    affiliate = _model(db, "Nour")
    _order(
        db, affiliate, "1", 100_000, delivery=IN_FLIGHT, state=CommissionState.PENDING
    )

    assert uses_for(db, affiliate, AUGUST) == 1


def test_an_order_shopify_has_not_answered_for_yet_still_counts(db):
    """A `NULL` delivery state is *anything in between*, not *failed*.

    Written because SQL makes this easy to get backwards: `!= 'failed'` is
    neither true nor false against NULL, so the obvious comparison silently
    drops exactly the orders D03 says to keep.
    """
    affiliate = _model(db, "Nour")
    _order(db, affiliate, "1", 100_000, delivery=None, state=CommissionState.PENDING)

    assert uses_for(db, affiliate, AUGUST) == 1


def test_a_refund_is_a_financial_event_and_does_not_remove_a_use(db):
    """**The mistake this rule exists to prevent.**

    `commission_state` folds cancelled, fully refunded and failed delivery into
    one `void`, and it is the obvious field to reach for. A delivered order
    that was later refunded pays nothing - and it was still delivered, so it is
    still a use.
    """
    affiliate = _model(db, "Nour")
    _order(db, affiliate, "1", 100_000, delivery=DELIVERED, state=CommissionState.VOID)

    assert uses_for(db, affiliate, AUGUST) == 1


def test_uses_and_sales_do_not_move_together(db):
    """Correct rather than a fault, and the reason her card explains itself: a
    parcel going out raises her uses and not her sales.
    """
    affiliate = _model(db, "Nour")
    _order(db, affiliate, "1", 100_000, delivery=DELIVERED, state=CommissionState.EARNED)
    _order(
        db, affiliate, "2", 900_000, delivery=IN_FLIGHT, state=CommissionState.PENDING
    )

    board = month_performance(db, AUGUST)

    assert board[0].uses == 2
    assert board[0].sales_piastres == 100_000


# -- D03: ranking --------------------------------------------------------------


def test_the_board_is_ordered_by_sales_not_by_uses(db):
    quiet = _model(db, "Sara")
    loud = _model(db, "Nour")
    _order(db, quiet, "1", 900_000, delivery=DELIVERED, state=CommissionState.EARNED)
    for index in range(4):
        _order(
            db,
            loud,
            f"n{index}",
            10_000,
            delivery=DELIVERED,
            state=CommissionState.EARNED,
        )

    board = month_performance(db, AUGUST)

    assert [row.name for row in board] == ["Sara", "Nour"]
    assert board[0].uses == 1 and board[1].uses == 4


@pytest.mark.parametrize(
    "rows, expected",
    [
        pytest.param(
            [(1, "A", 500, 10), (2, "B", 500, 10), (3, "C", 300, 5)],
            [1, 1, 3],
            id="tie_on_both_skips_second",
        ),
        pytest.param(
            [(1, "A", 500, 10), (2, "B", 500, 4), (3, "C", 500, 1)],
            [1, 2, 3],
            id="uses_break_a_sales_tie",
        ),
        pytest.param(
            [(1, "A", 500, 5), (2, "B", 500, 5), (3, "C", 500, 5)],
            [1, 1, 1],
            id="three_level_all_first",
        ),
        pytest.param(
            [(1, "A", 900, 1), (2, "B", 500, 9), (3, "C", 500, 9), (4, "D", 100, 0)],
            [1, 2, 2, 4],
            id="a_shared_second_skips_third",
        ),
    ],
)
def test_equal_standings_share_a_rank_and_use_the_places_up(rows, expected):
    """The owner's own example: *two as first, then there is no second, and we
    jump on the third.* `1, 1, 2` would say three models occupy two places.
    """
    assert [row.rank for row in rank(rows)] == expected


def test_uses_break_a_tie_before_a_rank_is_shared(db):
    even = _model(db, "Sara")
    busier = _model(db, "Nour")
    _order(db, even, "1", 500_000, delivery=DELIVERED, state=CommissionState.EARNED)
    _order(db, busier, "2", 400_000, delivery=DELIVERED, state=CommissionState.EARNED)
    _order(db, busier, "3", 100_000, delivery=DELIVERED, state=CommissionState.EARNED)

    board = {row.name: row for row in month_performance(db, AUGUST)}

    assert board["Nour"].sales_piastres == board["Sara"].sales_piastres
    assert board["Nour"].rank == 1, "two uses beats one at the same sales"
    assert board["Sara"].rank == 2


# -- D08: the weekly line ------------------------------------------------------


@pytest.mark.parametrize(
    "required, weekly",
    [
        pytest.param(5, [2, 3, 4, 5], id="five_rounds_up_to_two_in_week_one"),
        pytest.param(16, [4, 8, 12, 16], id="sixteen_is_four_a_week"),
        pytest.param(0, [0, 0, 0, 0], id="nothing_asked_is_never_behind"),
        pytest.param(1, [1, 1, 1, 1], id="one_is_due_from_the_first_week"),
    ],
)
def test_the_line_is_a_quarter_a_week_rounded_up(required, weekly):
    """Both figures are the owner's: *five stories, then by week one he should
    have done two*, and *sixteen divided by four, which is four targets*.
    """
    assert [expected_by(required, week) for week in (1, 2, 3, 4)] == weekly


@pytest.mark.parametrize(
    "day, week",
    [
        pytest.param(1, 1, id="first_day"),
        pytest.param(7, 1, id="last_day_of_week_one"),
        pytest.param(8, 2, id="week_two_starts_on_the_eighth"),
        pytest.param(22, 4, id="week_four_starts_on_the_twenty_second"),
        pytest.param(29, 4, id="the_leftover_days_belong_to_week_four"),
        pytest.param(31, 4, id="and_so_does_the_last_day_of_the_month"),
    ],
)
def test_the_fourth_week_absorbs_whatever_the_month_has_left(day, week):
    """August 2026 begins on a Saturday, so its fourth week ends on the 28th
    with three days to go. Those days are week four, because the final check is
    the end of the month - a model who finishes on the 31st was never behind.
    """
    assert week_bounds(AUGUST, date(2026, 8, day))[0] == week


def test_a_month_with_no_target_is_not_a_model_who_is_behind(db):
    affiliate = _model(db, "Nour")

    assert pace_for(db, affiliate, AUGUST, today=date(2026, 8, 20)).state == NO_TARGET


def test_counts_not_recorded_since_this_week_began_are_not_a_verdict(db):
    """**The check that stops this measuring HBA instead of her.**

    One cumulative pair per month and no weekly history, so a figure last typed
    in week one cannot answer a question about week three. It says nothing has
    been recorded, which is what is true.
    """
    affiliate = _model(db, "Nour")
    target = set_requirements(db, affiliate, AUGUST, videos=8, stories=8)
    record_actuals(
        db,
        target,
        videos=2,
        stories=2,
        # Recorded on the 8th: week two.
        recorded_at=datetime(2026, 8, 8, 9, tzinfo=timezone.utc),
    )
    db.flush()

    # Asked in week three, about counts last touched in week two.
    found = pace_for(db, affiliate, AUGUST, today=date(2026, 8, 20))

    assert found.state == NOT_RECORDED
    assert found.week == 3
    # The figure is still carried, so a screen can say what it last knew
    # rather than showing a blank beside the words.
    assert found.done == 4


def test_recorded_this_week_and_short_of_the_line_is_behind(db):
    affiliate = _model(db, "Nour")
    target = set_requirements(db, affiliate, AUGUST, videos=8, stories=8)
    record_actuals(
        db,
        target,
        videos=2,
        stories=2,
        recorded_at=datetime(2026, 8, 18, 9, tzinfo=timezone.utc),
    )
    db.flush()

    found = pace_for(db, affiliate, AUGUST, today=date(2026, 8, 20))

    assert found.state == BEHIND
    assert (found.week, found.expected_by_now, found.done) == (3, 12, 4)


def test_the_mix_does_not_matter_only_the_total(db):
    """*So maybe he made two videos, two stories. Maybe he have made three
    videos, one story and so on.* Sixteen targets is four a week in any mix.
    """
    affiliate = _model(db, "Nour")
    target = set_requirements(db, affiliate, AUGUST, videos=4, stories=12)
    record_actuals(
        db,
        target,
        videos=4,
        stories=0,
        recorded_at=datetime(2026, 8, 3, 9, tzinfo=timezone.utc),
    )
    db.flush()

    found = pace_for(db, affiliate, AUGUST, today=date(2026, 8, 5))

    assert found.required == 16
    assert found.expected_by_now == 4
    assert found.state == ON_TRACK, "four videos and no stories still clears four"


def test_a_month_the_calendar_has_not_reached_is_not_behind(db):
    affiliate = _model(db, "Nour")
    set_requirements(db, affiliate, AUGUST, videos=8, stories=8)
    db.flush()

    assert pace_for(db, affiliate, AUGUST, today=date(2026, 7, 30)).state == NOT_STARTED


# -- Targets fixed across a year -----------------------------------------------


def test_setting_a_year_writes_every_month_of_it(db):
    """Owner, 11 September 2026: *the required targets for a single model is
    fixed along all year.* Setting them is normally a year-wide act; varying
    one month is the exception you opt out into.
    """
    from app.services.targets import set_requirements_for_year

    affiliate = _model(db, "Nour")

    report = set_requirements_for_year(
        db, affiliate, AUGUST, videos=6, stories=10
    )

    assert len(report["applied"]) == 12
    assert report["skipped"] == []
    for index in (1, 8, 12):
        target = get_target(db, affiliate, f"2026-{index:02d}")
        assert (target.required_videos, target.required_stories) == (6, 10)


def test_a_year_includes_months_already_gone(db):
    """Asked directly whether the whole year meant this month onward or every
    month including ones already past, the owner chose **January included**.

    The consequence was put to him and is asserted here rather than left
    implicit: a month that was already counted can change what it means. March
    was achieved at four of four; after the year is raised to eight it is not.
    """
    from app.services.targets import set_requirements_for_year

    affiliate = _model(db, "Nour")
    march = set_requirements(db, affiliate, "2026-03", videos=2, stories=2)
    record_actuals(db, march, videos=2, stories=2)
    db.flush()
    assert march.is_achieved is True

    set_requirements_for_year(db, affiliate, AUGUST, videos=4, stories=4)

    assert get_target(db, affiliate, "2026-03").is_achieved is False, (
        "raising the year re-decides a month that was already counted - "
        "chosen knowingly, and the reason the save reports what it touched"
    )


def test_an_agreed_month_is_left_alone_and_named(db, monkeypatch):
    """05B: an agreed month is not unmade, and its snapshot froze the
    requirement it was agreed against. Skipping is forced rather than decided -
    refusing the whole year instead would make this unusable by December.
    """
    from app.config import settings
    from app.services.payroll import approve_month
    from app.services.targets import ALREADY_AGREED, set_requirements_for_year

    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)

    affiliate = _model(db, "Nour")
    _order(db, affiliate, "1", 100_000, delivery=DELIVERED,
           state=CommissionState.EARNED, month="2026-04")
    set_requirements(db, affiliate, "2026-04", videos=1, stories=1)
    approve_month(db, affiliate, "2026-04")
    db.flush()

    report = set_requirements_for_year(
        db, affiliate, AUGUST, videos=9, stories=9
    )

    assert {"month": "2026-04", "why": ALREADY_AGREED} in report["skipped"]
    assert "2026-04" not in report["applied"]
    kept = get_target(db, affiliate, "2026-04")
    assert (kept.required_videos, kept.required_stories) == (1, 1)


def test_counts_are_never_written_across_a_year(db):
    """What she produced is a fact about one month. Only the requirement is
    fixed across the year; recording is per month and stays that way.
    """
    from app.services.targets import set_requirements_for_year

    affiliate = _model(db, "Nour")
    august = set_requirements(db, affiliate, AUGUST, videos=4, stories=4)
    record_actuals(db, august, videos=4, stories=4)
    db.flush()

    set_requirements_for_year(db, affiliate, AUGUST, videos=4, stories=4)

    assert get_target(db, affiliate, "2026-09").actual_videos is None
    assert get_target(db, affiliate, AUGUST).actual_videos == 4


# -- M01: her own Home ---------------------------------------------------------


def test_her_home_carries_how_often_her_code_was_used(db):
    """M01 puts code uses on Home beside her earnings and sales."""
    from app.services.portal import my_month

    affiliate = _model(db, "Nour")
    _order(db, affiliate, "1", 100_000, delivery=DELIVERED, state=CommissionState.EARNED)

    assert my_month(db, affiliate, AUGUST)["orders"]["uses"] == 1


def test_uses_on_home_is_not_the_sum_of_the_counts_beside_it(db):
    """**The reason it is its own figure rather than arithmetic on the others.**

    The counts beside it are *commission* states; a use is a *delivery*
    outcome, and the two disagree in both directions at once:

    * an order delivered and later refunded is `void` and pays nothing, and it
      is still a use - her code brought a parcel to a door;
    * a parcel refused at the door is `void` too, and is not a use.

    Adding earned and pending would be wrong for both. A screen deriving this
    from what is already on it would quietly report the wrong number.
    """
    from app.services.portal import my_month

    affiliate = _model(db, "Nour")
    _order(db, affiliate, "kept", 100_000, delivery=DELIVERED,
           state=CommissionState.EARNED)
    _order(db, affiliate, "refunded", 100_000, delivery=DELIVERED,
           state=CommissionState.VOID)
    _order(db, affiliate, "refused", 100_000, delivery=FAILED,
           state=CommissionState.VOID)

    home = my_month(db, affiliate, AUGUST)["orders"]

    assert (home["earned"], home["pending"], home["void"]) == (1, 0, 2)
    assert home["uses"] == 2, "the refunded delivery counts; the refused one does not"
    assert home["uses"] != home["earned"] + home["pending"]


def test_a_month_with_nothing_in_it_reports_no_uses_rather_than_breaking(db):
    """M01: empty values are not NaN and missing facts are not zero-by-accident.
    Nothing used her code, which is a real answer and reads as one.
    """
    from app.services.portal import my_month

    affiliate = _model(db, "Nour")

    assert my_month(db, affiliate, AUGUST)["orders"]["uses"] == 0
