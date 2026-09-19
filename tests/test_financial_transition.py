"""The pending-inclusive policy, and the backlog the old one left behind.

Batch 1 of the readiness repair: F02, F07, F13 and the audit's A01 and A07.

## What changed

Until this, `calculate_month` counted **delivered orders only** and the
pending-inclusive rules lived in a preview that advertised
`live_transition_not_enabled`. A model with E£10,000 of pending sales at 10%
was shown an entitlement of E£1,000 on one screen and paid E£0 by another.

Now one rule counts for both: pending and delivered count, a failed delivery
does not.

## Why that cannot pay anybody twice

Three guards, and this file exercises each of them:

* approval **settles every order it counted**, so the order carries a link
  naming the payroll that paid it;
* `carried_into` pays only orders their own month's approval *left out* -
  which, under the old rule, is every order still travelling, and under the
  new one is none;
* an order failing after approval becomes a correction against the agreed
  figure (05C), never a silent restatement of it.

## The backlog is finite and reconcilable

Months agreed before the switch have no `policy` in their snapshot, which is
what identifies them. Their pending orders were never paid, are still owed,
and are still carried by the next payroll - exactly as they were. Nothing is
added to that set again, and `test_the_backlog_only_shrinks` is the assertion
that says so.
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
from app.services.commission.calculate import calculate_month
from app.services.compensation import set_terms
from app.services.corrections import correction_for, open_corrections
from app.services.payroll import (
    DELIVERED_ONLY,
    PENDING_INCLUSIVE,
    approve_month,
    carried_into,
    counted_in_snapshot,
    policy_of,
)
from app.services.portal import my_month, my_year
from tests.support_policy import approved_before_the_switch

AUGUST = "2026-08"
SEPTEMBER = "2026-09"


@pytest.fixture(autouse=True)
def _go_live(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)


@pytest.fixture(autouse=True)
def _working_month(monkeypatch):
    monkeypatch.setattr(
        "app.services.portal.working_month", lambda: SEPTEMBER, raising=True
    )


def _model(db, name="Nour", **terms):
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
        compensation_type=terms.pop("compensation_type", CompensationType.COMMISSION),
        commission_rate_bp=terms.pop("commission_rate_bp", 1000),
        **terms,
    )
    affiliate.collaboration_start_month = "2026-01"
    db.flush()
    return affiliate


def _order(db, affiliate, order_id, base, *, month=AUGUST, state=CommissionState.EARNED):
    db.add(
        OrderIndex(
            shopify_order_id=order_id,
            order_number=f"#{order_id}",
            placed_at=datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
            business_month=month,
            discount_codes=[f"{affiliate.name.upper()}10"],
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


def _deliver(db, order_id):
    db.get(AttributedOrder, order_id).commission_state = CommissionState.EARNED
    db.flush()


def _fail(db, order_id):
    db.get(AttributedOrder, order_id).commission_state = CommissionState.VOID
    db.flush()


#: Shared with `test_financial_rules_preview.py`, which needs the same legacy
#: month to check that its reconciliation view still reports the backlog.
_approved_before_the_switch = approved_before_the_switch


# -- The live policy ----------------------------------------------------------


def test_a_pending_order_is_paid_by_the_month_it_belongs_to(db):
    """A01/F02. The audit probe's own figures: E£10,000 pending at 10%.

    It reproduced E£0 live against E£1,000 in the preview. One rule now, and
    it is the agreed one.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 1_000_000, state=CommissionState.PENDING)

    calculation = calculate_month(db, affiliate, AUGUST)

    assert calculation.pending_base_piastres == 1_000_000
    assert calculation.payout_piastres == 100_000


def test_a_failed_delivery_still_counts_for_nothing(db):
    """F02's other half, and D09: a delivery outcome is final."""
    affiliate = _model(db)
    _order(db, affiliate, "1", 1_000_000, state=CommissionState.VOID)

    assert calculate_month(db, affiliate, AUGUST).payout_piastres == 0


def test_approval_records_which_rule_agreed_the_figure(db):
    """F02. A month must be able to say what it counted, long afterwards.

    Every later question about it - was this order paid, is that difference a
    correction - is answered from this rather than from whatever the
    calculator does today.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 1_000_000, state=CommissionState.PENDING)

    snapshot = approve_month(db, affiliate, AUGUST)

    assert policy_of(snapshot) == PENDING_INCLUSIVE
    assert counted_in_snapshot(snapshot, "1")


def test_a_snapshot_without_the_flag_is_read_as_the_old_rule(db):
    """Every month agreed before the switch carries no flag, and that is what
    identifies it. Absent means delivered-only, and a pending order in one was
    not paid by it."""
    affiliate = _model(db)
    _order(db, affiliate, "1", 1_000_000, state=CommissionState.PENDING)
    with _approved_before_the_switch():
        snapshot = approve_month(db, affiliate, AUGUST)

    assert policy_of(snapshot) == DELIVERED_ONLY
    assert not counted_in_snapshot(snapshot, "1")


# -- Never twice --------------------------------------------------------------


def test_delivery_after_approval_does_not_pay_the_order_again(db):
    """The guarantee the whole policy rests on.

    August counts a pending order and agrees the figure. The parcel arrives in
    September. September must not pay for it, and August must not become worth
    more - it already paid.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 1_000_000, state=CommissionState.PENDING)
    august = approve_month(db, affiliate, AUGUST)
    assert august.approved_obligation_piastres == 100_000

    _deliver(db, "1")

    assert carried_into(db, affiliate, SEPTEMBER) == []
    assert calculate_month(db, affiliate, SEPTEMBER).payout_piastres == 0
    # And August is unchanged, so nothing is offered as a correction either.
    assert calculate_month(db, affiliate, AUGUST).payout_piastres == 100_000
    assert open_corrections(db, affiliate) == []


def test_the_backlog_only_shrinks(db):
    """A month agreed under the old rule still owes what it left out, and a
    month agreed under the new one leaves nothing behind.

    That is the whole transition: the set of carriable orders is identified
    from each snapshot's own frozen evidence, it is finite, and nothing is
    added to it again.
    """
    affiliate = _model(db)
    # August: agreed under the old rule with an order still travelling.
    _order(db, affiliate, "old", 1_000_000, state=CommissionState.PENDING)
    with _approved_before_the_switch():
        approve_month(db, affiliate, AUGUST)
    _deliver(db, "old")

    # September: agreed under the new one, also with an order travelling.
    _order(db, affiliate, "new", 500_000, month=SEPTEMBER, state=CommissionState.PENDING)

    carried = carried_into(db, affiliate, SEPTEMBER)
    assert [row.shopify_order_id for row in carried] == ["old"]

    september = calculate_month(db, affiliate, SEPTEMBER)
    # Its own pending order, plus the one August never paid for.
    assert september.carried_base_piastres == 1_000_000
    assert september.payout_piastres == 150_000

    approve_month(db, affiliate, SEPTEMBER)
    _deliver(db, "new")

    # Nothing is left for October to carry: September paid for both.
    assert carried_into(db, affiliate, "2026-10") == []


def test_a_legacy_carried_order_is_not_paid_twice_after_it_is_carried(db):
    """Once a later payroll pays a backlog order, no month offers it again -
    including the month it belongs to."""
    affiliate = _model(db)
    _order(db, affiliate, "old", 1_000_000, state=CommissionState.PENDING)
    with _approved_before_the_switch():
        approve_month(db, affiliate, AUGUST)
    _deliver(db, "old")
    approve_month(db, affiliate, SEPTEMBER)

    assert carried_into(db, affiliate, "2026-10") == []
    # August's own recalculation excludes it too, so it does not resurface as
    # a difference against the month that never paid it.
    assert calculate_month(db, affiliate, AUGUST).payout_piastres == 0
    assert open_corrections(db, affiliate) == []


# -- Her own performance moves; her agreed money does not ---------------------


def test_a_failure_after_approval_moves_her_sales_and_not_her_earnings(db):
    """A07/F13, and the two halves that were conflated.

    September's earnings were agreed and are owed; a parcel refused in
    November does not reach back and change them. September's *sales* are a
    fact about September that the refusal corrects - and her month, and the
    chart of her year, have to say so.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    _order(db, affiliate, "2", 1_000_000)
    snapshot = approve_month(db, affiliate, AUGUST)
    assert snapshot.approved_obligation_piastres == 300_000

    before = my_month(db, affiliate, AUGUST)
    assert before["sales"]["earned_piastres"] == 3_000_000
    assert before["amount_piastres"] == 300_000

    _fail(db, "2")

    after = my_month(db, affiliate, AUGUST)
    # Her sales fell by the order that did not arrive...
    assert after["sales"]["earned_piastres"] == 2_000_000
    assert after["orders"]["earned"] == 1
    assert after["orders"]["void"] == 1
    # ...and what was agreed for the month did not move.
    assert after["amount_piastres"] == 300_000
    assert after["state"] == "agreed"


def test_the_statement_names_the_sales_its_commission_came_from(db):
    """A breakdown that does not add up is worse than no breakdown.

    The commission line says *10% of X*, and X has to be the money the
    commission was actually a percentage of. It was the delivered total, which
    stopped being the whole story the moment a pending order started counting.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 1_000_000)
    _order(db, affiliate, "2", 1_000_000, state=CommissionState.PENDING)
    approve_month(db, affiliate, AUGUST)

    month = my_month(db, affiliate, AUGUST)
    line = next(row for row in month["makeup"] if "Commission" in row["label"])

    # E£20,000 of sales, E£2,000 of commission.
    assert "E£20,000.00" in line["detail"]
    assert line["piastres"] == 200_000
    assert month["amount_piastres"] == 200_000


def test_an_old_statement_keeps_saying_what_it_always_said(db):
    """The same line on a month agreed before the switch.

    Its commission was worked out on delivered sales only, so naming the
    counted total would rewrite a closed month's arithmetic on screen.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 1_000_000)
    _order(db, affiliate, "2", 1_000_000, state=CommissionState.PENDING)
    with _approved_before_the_switch():
        approve_month(db, affiliate, AUGUST)

    month = my_month(db, affiliate, AUGUST)
    line = next(row for row in month["makeup"] if "Commission" in row["label"])

    assert "E£10,000.00" in line["detail"]
    assert line["piastres"] == 100_000
    assert month["amount_piastres"] == 100_000


def test_the_year_chart_follows_the_month_it_draws(db):
    """A07. `my_year` builds its sales series from `my_month`, so the chart
    was frozen for exactly as long as the month was."""
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    _order(db, affiliate, "2", 1_000_000)
    approve_month(db, affiliate, AUGUST)

    _fail(db, "2")

    august = next(
        row for row in my_year(db, affiliate)["months"] if row["month"] == AUGUST
    )
    assert august["sales_piastres"] == 2_000_000
    assert august["orders"] == 1
    # The agreed figure is what she was paid, and it is untouched.
    assert august["earned_piastres"] == 300_000


def test_the_destination_month_keeps_its_own_sales(db):
    """F13. A deduction carried into September reduces what September pays,
    never what September sold."""
    from app.models.payments import AdjustmentType
    from app.services.corrections import resolve
    from app.services.payments import record_payment

    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    august = approve_month(db, affiliate, AUGUST)
    record_payment(
        db, affiliate, amount_piastres=200_000, allocations={august.id: 200_000}
    )
    _order(db, affiliate, "2", 5_000_000, month=SEPTEMBER)
    approve_month(db, affiliate, SEPTEMBER)
    _fail(db, "1")

    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="carried into September",
        destination_month=SEPTEMBER,
    )

    september = my_month(db, affiliate, SEPTEMBER)
    assert september["sales"]["earned_piastres"] == 5_000_000
    assert september["amount_piastres"] == 500_000
    # What is *sent* is the month's own earnings less the recovery, and that
    # is the balance's business rather than the month's.
    assert correction_for(db, affiliate, AUGUST).outstanding_piastres == 0
