"""What happens to an agreed month whose evidence moves afterwards.

Phase 05C. 05B refused to unmake an agreement; this is the other half - the
agreement stands and the difference is recorded against it.

The distinction the whole batch turns on:

    agreed, and the source has not moved      nothing to say
    agreed, worth less now, money paid        an overpayment to carry or absorb
    agreed, worth less now, nothing paid      no debt - money that never moved
    agreed, worth more now                    HBA owes her; not a correction

**Guarantee-aware, and that is not a special case here.** A failed sale above a
guaranteed minimum costs nothing at all, because the guarantee is a floor. The
comparison runs the real engine twice rather than comparing commissions, so §15
is applied by the one implementation that knows it.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.passwords import hash_password
from app.models.affiliates import AccountKind
from app.models.attributed_orders import AttributedOrder, CommissionState
from app.models.compensation import CompensationType
from app.models.identity import UserAccount
from app.models.orders import OrderIndex
from app.services.affiliates import create_affiliate
from app.services.codes import register_code
from app.services.compensation import set_terms
from app.models.payments import AdjustmentType
from app.services.corrections import (
    OVERPAID,
    UNDERPAID,
    capacity_of,
    correction_for,
    open_corrections,
    outstanding_piastres,
    resolve,
)
from app.services.payments import record_payment
from app.services.payroll import approve_month
from app.services.targets import record_actuals, set_requirements, verify

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


def _fail(db, order_id):
    """The webhook that arrives weeks after the month closed."""
    row = db.scalar(
        select(AttributedOrder).where(AttributedOrder.shopify_order_id == order_id)
    )
    row.commission_state = CommissionState.VOID
    db.flush()


def _paid(db, affiliate, snapshot, piastres):
    record_payment(
        db,
        affiliate,
        amount_piastres=piastres,
        allocations={snapshot.id: piastres},
    )
    db.flush()


# -- Nothing to correct -------------------------------------------------------


def test_a_month_nobody_has_agreed_has_no_correction(db):
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)

    assert correction_for(db, affiliate, AUGUST) is None


def test_an_agreed_month_whose_source_has_not_moved_has_no_correction(db):
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    approve_month(db, affiliate, AUGUST)

    assert correction_for(db, affiliate, AUGUST) is None


def test_a_month_agreed_before_the_fingerprint_existed_reports_nothing(
    db, monkeypatch
):
    """Unknown is not the same as moved.

    Months agreed before 05B have no fingerprint to compare against. Reporting
    a correction for them would put a figure in front of somebody that nothing
    can substantiate, about a month that is closed.
    """
    # Approved as it would have been before 05B. The snapshot cannot simply be
    # edited afterwards - `payroll_snapshot` is append-only and the database
    # refuses it, which is the guard working.
    monkeypatch.setattr(
        "app.services.payroll.source_version", lambda *_args, **_kw: None
    )

    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    snapshot = approve_month(db, affiliate, AUGUST)
    assert snapshot.payload_json["source_version"] is None

    monkeypatch.undo()
    _fail(db, "1")

    assert correction_for(db, affiliate, AUGUST) is None


# -- An overpayment -----------------------------------------------------------


def test_an_order_failing_after_approval_is_an_overpayment(db):
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    snapshot = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, snapshot, snapshot.approved_obligation_piastres)

    _fail(db, "1")
    found = correction_for(db, affiliate, AUGUST)

    assert found.outcome == OVERPAID
    assert found.agreed_piastres == 200_000
    assert found.now_piastres == 0
    assert found.recoverable_piastres == 200_000


def test_nothing_is_recoverable_from_a_month_that_was_never_paid(db):
    """A debt is money that moved. A month agreed and not yet paid simply pays
    less when it is paid - there is nothing to take back.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    approve_month(db, affiliate, AUGUST)

    _fail(db, "1")
    found = correction_for(db, affiliate, AUGUST)

    assert found.outcome == OVERPAID
    assert found.paid_piastres == 0
    assert found.recoverable_piastres == 0
    assert open_corrections(db, affiliate) == []


def test_recovery_is_capped_at_what_actually_moved(db):
    """Agreed E£2,000, paid E£500, now worth nothing. E£500 is the debt."""
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    snapshot = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, snapshot, 50_000)

    _fail(db, "1")

    assert correction_for(db, affiliate, AUGUST).recoverable_piastres == 50_000


def test_a_month_worth_more_than_agreed_is_not_a_correction_against_her(db):
    """HBA owes her, and that is settled by agreeing the higher figure - not by
    an adjustment taking money back.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000, state=CommissionState.PENDING)
    approve_month(db, affiliate, AUGUST)

    db.scalar(
        select(AttributedOrder).where(AttributedOrder.shopify_order_id == "1")
    ).commission_state = CommissionState.EARNED
    db.flush()

    found = correction_for(db, affiliate, AUGUST)

    assert found.outcome == UNDERPAID
    assert found.recoverable_piastres == 0
    assert open_corrections(db, affiliate) == []


# -- The guarantee ------------------------------------------------------------


def test_a_failed_sale_above_a_guarantee_costs_nothing(db):
    """§15, and the case that would manufacture a debt if it were got wrong.

    She is on an E£8,000 floor and sold E£100,000 at 10%. One E£20,000 order
    fails. Her commission falls from E£10,000 to E£8,000 - and her *pay* does
    not move at all, because the floor was already carrying it.
    """
    affiliate = _model(
        db,
        compensation_type=CompensationType.BASE_GUARANTEE,
        base_amount_piastres=800_000,
    )
    _order(db, affiliate, "1", 8_000_000)
    _order(db, affiliate, "2", 2_000_000)
    target = set_requirements(db, affiliate, AUGUST, videos=4, stories=8)
    record_actuals(db, target, videos=4, stories=8)
    verify(db, target)
    db.flush()

    snapshot = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, snapshot, snapshot.approved_obligation_piastres)
    assert snapshot.approved_obligation_piastres == 1_000_000

    _fail(db, "2")
    found = correction_for(db, affiliate, AUGUST)

    assert found.now_piastres == 800_000
    assert found.recoverable_piastres == 200_000
    # And a further failure that takes the commission below the floor costs
    # nothing more: the guarantee is what she is paid from there down.
    _fail(db, "1")
    assert correction_for(db, affiliate, AUGUST).now_piastres == 800_000


# -- Carrying it, absorbing it, and D04 ---------------------------------------


def _september(db, affiliate, base=900_000):
    """A later month, agreed, with money still owed on it."""
    _order(db, affiliate, "sep-1", base, month=SEPTEMBER)
    return approve_month(db, affiliate, SEPTEMBER)


def test_absorbing_an_overpayment_records_a_write_off_and_recovers_nothing(db):
    """§11.5's other half. HBA takes the loss; she owes nothing."""
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    snapshot = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, snapshot, 200_000)
    _fail(db, "1")

    written = resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.WRITEOFF,
        reason="Parcel refused; not worth chasing",
    )

    assert written.type == AdjustmentType.WRITEOFF
    assert written.amount_piastres == 200_000
    assert written.destination_payroll_month_id is None
    assert correction_for(db, affiliate, AUGUST).resolved is True
    assert open_corrections(db, affiliate) == []


def test_carrying_an_overpayment_lands_it_in_a_later_month(db):
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    snapshot = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, snapshot, 200_000)
    _september(db, affiliate, base=3_000_000)
    _fail(db, "1")

    carried = resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="Recovering August's refused parcel from September",
        destination_month=SEPTEMBER,
    )

    assert carried.type == AdjustmentType.CREDIT
    assert carried.amount_piastres == 200_000
    assert open_corrections(db, affiliate) == []


def test_the_amount_is_not_the_callers_to_choose(db):
    """`resolve` takes no amount. A caller supplying its own could recover more
    than was ever paid, or recover twice, and the ledger would afterwards say
    only that somebody chose that.
    """
    import inspect

    assert "amount_piastres" not in inspect.signature(resolve).parameters


def test_a_correction_can_only_be_resolved_once(db):
    """Idempotence, and it is what a retried request looks like."""
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    snapshot = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, snapshot, 200_000)
    _fail(db, "1")

    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.WRITEOFF,
        reason="absorbed",
    )

    with pytest.raises(ValueError, match="already been"):
        resolve(
            db,
            affiliate,
            AUGUST,
            choice=AdjustmentType.WRITEOFF,
            reason="absorbed again",
        )


def test_a_whole_month_can_be_consumed_including_below_a_guarantee(db):
    """**D04, answered 10 September 2026: the whole month, floor included.**

    She is on an E£8,000 guaranteed minimum. September's commission comes to
    E£9,000, so that is what September is worth. An E£9,000 debt from August
    takes all of it and September settles at zero - **in a month she met and
    verified her targets in**, which is the month the guarantee was a promise
    about.

    August is the debt rather than the demonstration: its target was missed, so
    the guarantee never applied there and the failed order costs the whole
    commission. That is what makes a debt big enough to eat a floor.

    The platform recommended protecting the floor and was overruled. This test
    exists so the behaviour reads as a decision somebody made rather than
    something a later reader has to reverse-engineer from a payment of nothing.
    """
    affiliate = _model(
        db,
        compensation_type=CompensationType.BASE_GUARANTEE,
        base_amount_piastres=800_000,
    )
    missed = set_requirements(db, affiliate, AUGUST, videos=4, stories=8)
    record_actuals(db, missed, videos=0, stories=0)
    verify(db, missed)
    met = set_requirements(db, affiliate, SEPTEMBER, videos=4, stories=8)
    record_actuals(db, met, videos=4, stories=8)
    verify(db, met)
    db.flush()

    _order(db, affiliate, "1", 9_000_000)
    august = approve_month(db, affiliate, AUGUST)
    assert august.approved_obligation_piastres == 900_000, "guarantee missed"
    _paid(db, affiliate, august, 900_000)

    september = _september(db, affiliate, base=9_000_000)
    assert september.approved_obligation_piastres == 900_000

    _fail(db, "1")
    assert correction_for(db, affiliate, AUGUST).recoverable_piastres == 900_000
    assert capacity_of(db, affiliate, SEPTEMBER) == 900_000

    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="August's order was refused",
        destination_month=SEPTEMBER,
    )

    from app.services.payments import balance_for

    # Nothing to send her for September, and she qualified for her guarantee
    # in it. D04 says that is the right answer; the screens have to say why.
    assert balance_for(db, affiliate, SEPTEMBER)["balance_piastres"] == 0


def test_two_corrections_cannot_both_spend_one_month(db):
    """Shared destination capacity. Without this the second carry would
    quietly overdraw a month the first had already taken.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    august = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, august, 200_000)
    _september(db, affiliate, base=2_500_000)
    _fail(db, "1")

    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="first",
        destination_month=SEPTEMBER,
    )

    # September was worth E£250 and E£200 of it is spoken for.
    assert capacity_of(db, affiliate, SEPTEMBER) == 50_000


def test_a_carry_bigger_than_the_month_is_refused_rather_than_part_applied(db):
    """A partial recovery leaves a remainder nothing is tracking, and not
    forgetting a difference is the whole point of this service.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    august = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, august, 200_000)
    _september(db, affiliate, base=500_000)
    _fail(db, "1")

    with pytest.raises(ValueError, match="can take"):
        resolve(
            db,
            affiliate,
            AUGUST,
            choice=AdjustmentType.CREDIT,
            reason="too big",
            destination_month=SEPTEMBER,
        )

    assert open_corrections(db, affiliate) != []


def test_everything_outstanding_is_added_up_across_her_months(db):
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    august = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, august, 200_000)
    september = _september(db, affiliate, base=1_000_000)
    _paid(db, affiliate, september, 100_000)

    _fail(db, "1")
    _fail(db, "sep-1")

    assert outstanding_piastres(db, affiliate) == 300_000
    assert [row.month for row in open_corrections(db, affiliate)] == [
        SEPTEMBER,
        AUGUST,
    ]


# -- What she is told ----------------------------------------------------------


def test_a_month_swallowed_by_a_correction_explains_itself_to_her(db):
    """**D04's obligation on the interface.**

    A carried correction can take a whole month, so she can open one she met
    her targets in and find nothing owed. The reasoning is invisible from her
    side — she never saw the refused parcel — so the sentence is the only thing
    between that and a support message.

    Written by the service (§11.5: *a credit she cannot see is a credit she
    cannot check*), and asserted here rather than in the browser, because a
    sentence the browser assembles is one no test can hold to account.
    """
    from app.services.portal import my_month

    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    august = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, august, 200_000)
    _september(db, affiliate, base=3_000_000)
    _fail(db, "1")

    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="The parcel was refused",
        destination_month=SEPTEMBER,
    )

    said = my_month(db, affiliate, SEPTEMBER)["credited_from"][0]["text"]

    assert "August 2026" in said
    assert "E£2,000.00" in said
    # **Never "includes".** The old wording read as money added to the month,
    # which is the opposite of what a credit does.
    assert "includes" not in said.lower()
    assert "not being sent again" in said


def test_the_month_the_overpayment_came_from_still_reads_as_agreed(db):
    """§11.1. The agreement stands; the correction is recorded against it.

    Her August still shows what August was agreed at. A figure that dropped
    under the word "agreed" would present a working number as a debt, which is
    what the whole snapshot design exists to prevent.
    """
    from app.services.portal import my_month

    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    august = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, august, 200_000)
    _september(db, affiliate, base=3_000_000)
    _fail(db, "1")

    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="The parcel was refused",
        destination_month=SEPTEMBER,
    )

    assert my_month(db, affiliate, AUGUST)["amount_piastres"] == 200_000


# -- AC43, in its own numbers -------------------------------------------------


@pytest.mark.parametrize(
    "met, expected",
    [
        pytest.param(True, 10_000, id="target_met_recovers_100"),
        pytest.param(False, 20_000, id="target_missed_recovers_200"),
    ],
)
def test_a_guarantee_month_recovers_exactly_what_the_acceptance_check_says(
    db, met, expected
):
    """AC43, asserted in the figures the check is written in.

    Commission of E£2,100 falls to E£1,900 against a guaranteed minimum of
    E£2,000.

    * **Targets met**: she was paid E£2,100 and the month is now worth E£2,000,
      because the floor catches it. **E£100.**
    * **Targets missed**: the guarantee never applied, so the month is worth
      its commission both times. **E£200.**

    The same failed order, and the recovery differs by a factor of two
    depending on a target. Nothing in `corrections` knows that - it runs the
    engine twice and §15 does the rest.
    """
    affiliate = _model(
        db,
        compensation_type=CompensationType.BASE_GUARANTEE,
        base_amount_piastres=200_000,
    )
    target = set_requirements(db, affiliate, AUGUST, videos=4, stories=8)
    record_actuals(db, target, videos=4 if met else 0, stories=8 if met else 0)
    verify(db, target)
    db.flush()

    # E£2,100 of commission at 10% is E£21,000 of sales: E£19,000 that stays
    # and E£2,000 that fails. In piastres throughout, which is the whole
    # currency of the engine - the acceptance check is written in pounds and
    # the two are a factor of a hundred apart.
    _order(db, affiliate, "keeps", 1_900_000)
    _order(db, affiliate, "fails", 200_000)

    snapshot = approve_month(db, affiliate, AUGUST)
    assert snapshot.approved_obligation_piastres == 210_000
    _paid(db, affiliate, snapshot, 210_000)

    _fail(db, "fails")

    assert correction_for(db, affiliate, AUGUST).recoverable_piastres == expected


def test_the_outstanding_total_can_reuse_a_list_it_is_given(db):
    """Each correction runs its month's whole calculation, so a screen showing
    the list and the total would otherwise do the work twice.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    august = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, august, 200_000)
    _fail(db, "1")

    rows = open_corrections(db, affiliate)

    assert outstanding_piastres(db, affiliate, rows) == outstanding_piastres(
        db, affiliate
    )
