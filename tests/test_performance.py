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
from app.services.targets import record_actuals, set_requirements

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
