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
    NOTHING_TO_CORRECT,
    OVERPAID,
    UNDERPAID,
    CorrectionMoved,
    capacity_of,
    correction_for,
    open_corrections,
    outstanding_piastres,
    resolve,
)
from app.services.payments import balance_for, record_payment
from app.services.payroll import (
    SourceMoved,
    approve_month,
    blockers_for,
    carried_into,
    deductions_landing_on,
    source_version,
)
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


def _source_version(db, affiliate, month):
    """The fingerprint a reviewer would be shown for this month."""
    _, calculation = blockers_for(db, affiliate, month)
    return source_version(
        calculation,
        list(
            db.scalars(
                select(AttributedOrder)
                .where(AttributedOrder.affiliate_id == affiliate.id)
                .where(AttributedOrder.business_month == month)
                .order_by(AttributedOrder.shopify_order_id)
            )
        ),
        carried_into(db, affiliate, month),
        deductions_landing_on(db, affiliate, month),
    )


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

    **It is still reviewed** (F09). This used to leave the queue empty, so an
    order failing between approval and payment was a change nobody was told
    about. Not inventing a debt is right; hiding the difference is not, and
    they are separate figures now.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    approve_month(db, affiliate, AUGUST)

    _fail(db, "1")
    found = correction_for(db, affiliate, AUGUST)

    assert found.outcome == OVERPAID
    assert found.paid_piastres == 0
    assert found.recoverable_piastres == 0
    # The difference is real, and somebody has to look at it.
    assert found.outstanding_piastres == 200_000
    assert found.needs_review
    assert not found.resolved
    assert [row.month for row in open_corrections(db, affiliate)] == [AUGUST]
    # ...and it adds nothing to what she owes, because she was sent nothing.
    assert outstanding_piastres(db, affiliate) == 0


def test_a_month_awaiting_its_transfer_cannot_be_recovered_from(db):
    """F09/A05. The honest refusal, and it names what to do instead.

    An external transfer that really was made is recorded, and the recovery
    becomes available; one that was never made leaves the agreed figure to be
    paid in full. Neither is a deduction against money that never moved.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    approve_month(db, affiliate, AUGUST)
    _september(db, affiliate, base=5_000_000)
    _fail(db, "1")

    with pytest.raises(ValueError, match="No transfer is recorded"):
        resolve(
            db,
            affiliate,
            AUGUST,
            choice=AdjustmentType.CREDIT,
            reason="nothing was sent",
            destination_month=SEPTEMBER,
        )


def test_recovery_is_capped_at_what_actually_moved(db):
    """Agreed E£2,000, paid E£500, now worth nothing. E£500 is the debt."""
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    snapshot = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, snapshot, 50_000)

    _fail(db, "1")

    assert correction_for(db, affiliate, AUGUST).recoverable_piastres == 50_000


def test_delivery_after_approval_changes_nothing(db):
    """F02, and the reason counting a pending order is safe.

    The month counted it while it was travelling. The courier confirming it is
    evidence about the same sale, not a second one - so there is nothing to
    correct in either direction, and nothing to pay again.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000, state=CommissionState.PENDING)
    snapshot = approve_month(db, affiliate, AUGUST)
    assert snapshot.approved_obligation_piastres == 200_000

    db.scalar(
        select(AttributedOrder).where(AttributedOrder.shopify_order_id == "1")
    ).commission_state = CommissionState.EARNED
    db.flush()

    found = correction_for(db, affiliate, AUGUST)
    assert found is None or found.outcome == NOTHING_TO_CORRECT
    assert open_corrections(db, affiliate) == []


def test_a_month_worth_more_than_agreed_is_not_a_correction_against_her(db):
    """HBA owes her, and that is settled by agreeing the higher figure - not by
    an adjustment taking money back.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    approve_month(db, affiliate, AUGUST)

    # An order attributed to August after August was agreed. Its sales are
    # real and the agreed figure did not include them.
    _order(db, affiliate, "2", 1_000_000)

    found = correction_for(db, affiliate, AUGUST)

    assert found.outcome == UNDERPAID
    assert found.recoverable_piastres == 0
    assert found.outstanding_piastres == 0
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


def test_absorbing_an_overpayment_records_an_acceptance_and_recovers_nothing(db):
    """§11.5's other half. HBA takes the loss; she owes nothing.

    **This used to assert a `writeoff`, and F2 is why it does not now.** Both
    words were right about the intention and only one of them is right about
    the arithmetic: a write-off reduces what a month still owes - *we are not
    sending the rest* - and absorbing a correction must not, or HBA's loss
    comes out of her money. The row type is what carries that difference, so
    absorbing records an `accepted`.

    Nothing about a write-off changed. It is still what closes an overpayment
    and still what forgives a remainder nobody will chase; it is simply not
    what this act is.
    """
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

    assert written.type == AdjustmentType.ACCEPTED
    assert written.amount_piastres == 200_000
    assert written.destination_payroll_month_id is None
    assert correction_for(db, affiliate, AUGUST).resolved is True
    assert open_corrections(db, affiliate) == []
    # Paid in full and agreed at that figure, so nothing is outstanding - and
    # the acceptance did not make it so, which is the point of the type.
    assert balance_for(db, affiliate, AUGUST)["balance_piastres"] == 0


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


def test_a_carry_bigger_than_the_month_applies_what_fits_and_keeps_the_rest(db):
    """F12, and the case this service was built for.

    Earning E£500 against a E£2,000 deduction applies E£500, sends nothing,
    and leaves E£1,500 outstanding for a later month - this year or any other.
    It used to be refused outright, on the reasoning that a remainder nothing
    is tracking is worse than a refusal. The remainder is tracked now: the
    month's whole difference is compared with everything already carried or
    absorbed, so it cannot be forgotten and cannot be taken twice.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    august = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, august, 200_000)
    _september(db, affiliate, base=500_000)
    _fail(db, "1")

    adjustment = resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="as much as September can take",
        destination_month=SEPTEMBER,
    )

    # September was worth E£500 and is consumed entirely; nothing is sent, and
    # no zero-value transfer stands in for the settlement.
    assert adjustment.amount_piastres == 50_000
    assert balance_for(db, affiliate, SEPTEMBER)["balance_piastres"] == 0

    remaining = correction_for(db, affiliate, AUGUST)
    assert remaining.resolved_piastres == 50_000
    assert remaining.outstanding_piastres == 150_000
    assert not remaining.resolved
    assert [row.month for row in open_corrections(db, affiliate)] == [AUGUST]


def test_a_remainder_waits_for_a_month_with_room_in_a_later_year(db):
    """F12: remainders persist across years, with no four-month limit."""
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    august = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, august, 200_000)
    _september(db, affiliate, base=500_000)
    _fail(db, "1")

    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="September takes what it can",
        destination_month=SEPTEMBER,
    )

    # The following February, with room for the rest of it.
    _order(db, affiliate, "9", 9_000_000, month="2027-02")
    approve_month(db, affiliate, "2027-02")

    second = resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="the remainder, the following year",
        destination_month="2027-02",
    )

    assert second.amount_piastres == 150_000
    settled = correction_for(db, affiliate, AUGUST)
    assert settled.resolved_piastres == 200_000
    assert settled.outstanding_piastres == 0
    assert settled.resolved
    assert open_corrections(db, affiliate) == []


def test_a_second_failure_reopens_only_the_new_difference(db):
    """F11, and the defect this repair was written for.

    One agreed month, two failed orders and a credit in between. Treating any
    earlier resolution as *this month is dealt with* hid the second failure
    completely: the queue reported nothing, whatever the new difference was.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 1_000_000)
    _order(db, affiliate, "2", 1_000_000)
    august = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, august, 200_000)
    _september(db, affiliate, base=9_000_000)

    _fail(db, "1")
    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="the first parcel came back",
        destination_month=SEPTEMBER,
    )
    assert correction_for(db, affiliate, AUGUST).resolved
    assert open_corrections(db, affiliate) == []

    # Weeks later, the second parcel fails too.
    _fail(db, "2")

    again = correction_for(db, affiliate, AUGUST)
    assert again.shortfall_piastres == 200_000
    assert again.resolved_piastres == 100_000
    # Only the new difference, never the whole month a second time.
    assert again.outstanding_piastres == 100_000
    assert again.recoverable_piastres == 100_000
    assert not again.resolved
    assert [row.month for row in open_corrections(db, affiliate)] == [AUGUST]


def test_the_same_correction_cannot_be_recovered_twice_by_a_retry(db):
    """A repeated submission is refused, not applied again.

    Partial settlement is legitimate now, so a second identical request is no
    longer harmlessly idempotent - it would carry the same money into the same
    month twice. The figure the screen showed is sent back with the choice,
    and a request that no longer matches it is answered *look again*.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    august = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, august, 200_000)
    _september(db, affiliate, base=9_000_000)
    _fail(db, "1")

    shown = correction_for(db, affiliate, AUGUST).outstanding_piastres
    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="carried",
        destination_month=SEPTEMBER,
        expected_outstanding_piastres=shown,
    )

    with pytest.raises(CorrectionMoved):
        resolve(
            db,
            affiliate,
            AUGUST,
            choice=AdjustmentType.CREDIT,
            reason="carried",
            destination_month=SEPTEMBER,
            expected_outstanding_piastres=shown,
        )

    assert correction_for(db, affiliate, AUGUST).resolved_piastres == 200_000


def test_resolving_a_correction_leaves_the_agreement_and_the_transfer_alone(db):
    """05B/F07, asserted rather than assumed.

    The whole design rests on this: an agreed month is not unmade and a
    transfer that happened does not un-happen. A correction is recorded
    *against* them. So the snapshot's figure, its frozen payload, its content
    hash and the payment row are all read before and after, and none of them
    may move.
    """
    from app.models.payments import PaymentTransaction

    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    august = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, august, 200_000)
    _september(db, affiliate, base=9_000_000)

    before = (
        august.approved_obligation_piastres,
        august.content_hash,
        dict(august.payload_json),
        august.version,
    )
    transfer = db.scalars(select(PaymentTransaction)).one()
    sent = (transfer.id, transfer.amount_piastres, transfer.occurred_at)

    _fail(db, "1")
    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="the parcel came back",
        destination_month=SEPTEMBER,
    )
    db.flush()
    db.expire_all()

    after = db.get(type(august), august.id)
    assert (
        after.approved_obligation_piastres,
        after.content_hash,
        dict(after.payload_json),
        after.version,
    ) == before
    still = db.scalars(select(PaymentTransaction)).one()
    assert (still.id, still.amount_piastres, still.occurred_at) == sent


def test_a_difference_larger_than_the_transfer_stays_open_and_says_why(db):
    """The other way nothing can be recovered, and it is not the same thing.

    Agreed E£2,000, E£100 sent, the order then failed: E£100 is recoverable
    and E£1,900 of the difference is against money that has not been
    transferred at all. Taking that back would be recovering what never
    moved; hiding it would lose the difference. It waits, and becomes
    recoverable the moment the rest is sent.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    august = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, august, 10_000)
    _september(db, affiliate, base=3_000_000)
    _fail(db, "1")

    # The queue says so before anybody decides anything: E£100 recoverable,
    # E£2,000 of difference, and a reason naming which is which.
    left = correction_for(db, affiliate, AUGUST)
    assert left.resolved_piastres == 0
    assert left.outstanding_piastres == 200_000
    assert left.recoverable_piastres == 10_000
    # No reason yet: something *can* be recovered, so there is an ordinary
    # decision to make and nothing to explain.
    assert left.review_reason is None
    assert [row.month for row in open_corrections(db, affiliate)] == [AUGUST]

    # Carrying takes what actually moved, and only that. The rest stays open.
    carried = resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="recover what was sent",
        destination_month=SEPTEMBER,
    )
    assert carried.amount_piastres == 10_000
    still = correction_for(db, affiliate, AUGUST)
    assert still.outstanding_piastres == 190_000
    assert still.recoverable_piastres == 0
    # And now the reason: what is left is difference against money that was
    # never sent, which is why the next paragraph cannot carry it anywhere.
    assert still.review_reason == "difference_exceeds_what_was_sent"

    # **R4, and F2's correction to it.** What is left is difference against
    # money that was never sent: nothing to carry, and absorbing is the answer
    # that finishes the review. It takes the whole remaining difference rather
    # than a part of it - absorbing recovers nothing either way, so there is
    # no partial version of it to want.
    #
    # **This test used to absorb first and carry second**, and the order is
    # what changed. Absorbing now closes the review completely, so anything
    # recoverable has to be recovered before it rather than after. That is the
    # order somebody would choose anyway: take back what moved, then decide
    # about what did not.
    with pytest.raises(ValueError, match="nothing to carry"):
        resolve(
            db,
            affiliate,
            AUGUST,
            choice=AdjustmentType.CREDIT,
            reason="nowhere to carry it",
            destination_month=SEPTEMBER,
        )

    before = balance_for(db, affiliate, AUGUST)["balance_piastres"]
    absorbed = resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.WRITEOFF,
        reason="HBA absorbs what was never sent",
    )
    assert absorbed.type == AdjustmentType.ACCEPTED
    assert absorbed.amount_piastres == 190_000
    assert correction_for(db, affiliate, AUGUST).outstanding_piastres == 0
    # **The property R4 owns, which F2 widened**: absorbing moves nothing. Not
    # the difference against money that never left, and - since F2 - not the
    # money still to send either.
    assert balance_for(db, affiliate, AUGUST)["balance_piastres"] == before
    assert before == 190_000


def test_a_destination_that_falls_before_approval_hands_back_what_it_cannot_take(db):
    """R1, and the defect the follow-up review reproduced.

    E£200 is carried into September while September is earning E£200. An
    order then fails and September is agreed at E£100. The month cannot take
    the whole deduction, and what it cannot take must go back to the
    correction it came from - not sit on September as a E£100 *overpayment*
    on a month nothing was ever transferred for.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    august = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, august, 200_000)
    # September is worth E£200 when the carry is accepted.
    _order(db, affiliate, "sep-big", 1_000_000, month=SEPTEMBER)
    _order(db, affiliate, "sep-small", 1_000_000, month=SEPTEMBER)
    _fail(db, "1")

    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="carried into September",
        destination_month=SEPTEMBER,
    )
    assert correction_for(db, affiliate, AUGUST).outstanding_piastres == 0

    # One of September's orders fails before the month is agreed.
    _fail(db, "sep-small")
    approve_month(db, affiliate, SEPTEMBER)

    balance = balance_for(db, affiliate, SEPTEMBER)
    assert balance["obligation_piastres"] == 100_000
    # It took what it could, and no more.
    assert balance["credited_piastres"] == 100_000
    assert balance["balance_piastres"] == 0
    assert balance["state"] != "overpaid"

    # The rest is open again, against the month it came from.
    again = correction_for(db, affiliate, AUGUST)
    assert again.resolved_piastres == 100_000
    assert again.outstanding_piastres == 100_000
    assert again.recoverable_piastres == 100_000
    assert [row.month for row in open_corrections(db, affiliate)] == [AUGUST]


def test_a_destination_that_falls_to_nothing_hands_all_of_it_back(db):
    """R1. The same, with no room left at all."""
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    august = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, august, 200_000)
    _order(db, affiliate, "sep-1", 2_000_000, month=SEPTEMBER)
    _fail(db, "1")

    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="carried into September",
        destination_month=SEPTEMBER,
    )

    _fail(db, "sep-1")
    approve_month(db, affiliate, SEPTEMBER)

    assert balance_for(db, affiliate, SEPTEMBER)["credited_piastres"] == 0
    assert correction_for(db, affiliate, AUGUST).outstanding_piastres == 200_000


def test_two_corrections_sharing_a_destination_are_released_in_turn(db):
    """R1. The month pays what it has, oldest claim first.

    Two months are corrected and both carried into October. October is then
    agreed at less than the two together, so the later claim gives way: the
    earlier one was accepted when the month had room for it.
    """
    affiliate = _model(db)
    _order(db, affiliate, "jun", 1_000_000, month="2026-06")
    june = approve_month(db, affiliate, "2026-06")
    _paid(db, affiliate, june, 100_000)
    _order(db, affiliate, "jul", 1_000_000, month="2026-07")
    july = approve_month(db, affiliate, "2026-07")
    _paid(db, affiliate, july, 100_000)
    _order(db, affiliate, "oct", 3_000_000, month="2026-10")
    _fail(db, "jun")
    _fail(db, "jul")

    for source in ("2026-06", "2026-07"):
        resolve(
            db,
            affiliate,
            source,
            choice=AdjustmentType.CREDIT,
            reason=f"carried from {source}",
            destination_month="2026-10",
        )

    # October is agreed at E£150 against E£200 of accepted deductions.
    _order(db, affiliate, "oct-lost", 1_500_000, month="2026-10")
    _fail(db, "oct-lost")
    db.get(AttributedOrder, "oct").commission_base_piastres = 1_500_000
    db.flush()
    approve_month(db, affiliate, "2026-10")

    assert balance_for(db, affiliate, "2026-10")["credited_piastres"] == 150_000
    # June keeps what it claimed first; July gives back the shortfall.
    assert correction_for(db, affiliate, "2026-06").outstanding_piastres == 0
    assert correction_for(db, affiliate, "2026-07").outstanding_piastres == 50_000


def test_a_deduction_accepted_after_the_preview_invalidates_the_approval(db):
    """R1, F07. Approval freezes accepted deductions, so it checks them.

    A reviewer opens September, sees what it will pay, and somebody carries a
    correction into it before they commit. The settlement they were shown is
    not the settlement they would be agreeing, and the fingerprint says so.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    august = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, august, 200_000)
    _order(db, affiliate, "sep-1", 5_000_000, month=SEPTEMBER)

    shown = _source_version(db, affiliate, SEPTEMBER)
    _fail(db, "1")
    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="carried while the reviewer was looking",
        destination_month=SEPTEMBER,
    )

    with pytest.raises(SourceMoved):
        approve_month(db, affiliate, SEPTEMBER, expected_source_version=shown)


def test_a_remainder_released_in_one_year_is_carried_in_the_next(db):
    """R1, F12. What a month could not take waits as long as it needs to."""
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    august = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, august, 200_000)
    _order(db, affiliate, "sep-1", 2_000_000, month=SEPTEMBER)
    _fail(db, "1")
    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="carried into September",
        destination_month=SEPTEMBER,
    )
    _fail(db, "sep-1")
    approve_month(db, affiliate, SEPTEMBER)
    assert correction_for(db, affiliate, AUGUST).outstanding_piastres == 200_000

    _order(db, affiliate, "feb", 9_000_000, month="2027-02")
    approve_month(db, affiliate, "2027-02")
    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="the remainder, the following year",
        destination_month="2027-02",
    )

    assert correction_for(db, affiliate, AUGUST).outstanding_piastres == 0
    assert balance_for(db, affiliate, "2027-02")["credited_piastres"] == 200_000


# -- R4: a decision on a month nothing was sent for ---------------------------


def test_hba_can_absorb_a_difference_on_a_month_nothing_was_sent_for(db):
    """R4. Visibility was not the whole workflow.

    Approved E£2,000, revised to E£1,800, no transfer recorded. The queue
    showed it and refused every way of finishing with it. Absorbing is a real
    answer - the agreed figure stands and HBA takes the difference - and it
    is recorded without pretending money moved.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 1_800_000)
    _order(db, affiliate, "2", 200_000)
    approve_month(db, affiliate, AUGUST)
    _fail(db, "2")

    found = correction_for(db, affiliate, AUGUST)
    assert found.recoverable_piastres == 0
    assert found.review_reason == "no_transfer_recorded"

    decision = resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.WRITEOFF,
        reason="HBA keeps its promise and absorbs the difference",
    )

    assert decision.type == AdjustmentType.ACCEPTED
    assert decision.amount_piastres == 20_000
    # The review is finished...
    settled = correction_for(db, affiliate, AUGUST)
    assert settled.outstanding_piastres == 0
    assert settled.resolved
    assert open_corrections(db, affiliate) == []
    # ...and the agreed payable is exactly where the agreement put it.
    balance = balance_for(db, affiliate, AUGUST)
    assert balance["obligation_piastres"] == 200_000
    assert balance["balance_piastres"] == 200_000
    assert balance["paid_piastres"] == 0


def test_absorbing_before_payment_leaves_the_transfer_still_to_make(db):
    """R4. No fabricated transfer, and no fabricated debt either."""
    affiliate = _model(db)
    _order(db, affiliate, "1", 1_800_000)
    _order(db, affiliate, "2", 200_000)
    august = approve_month(db, affiliate, AUGUST)
    _fail(db, "2")
    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.WRITEOFF,
        reason="absorbed",
    )

    # The transfer is made afterwards, for the figure that was agreed.
    _paid(db, affiliate, august, 200_000)

    assert balance_for(db, affiliate, AUGUST)["balance_piastres"] == 0
    # Recording it does not reopen a difference that was already decided.
    assert open_corrections(db, affiliate) == []


def test_a_later_failure_after_an_absorption_offers_only_the_new_difference(db):
    """R4 with F11: the cumulative rule still governs."""
    affiliate = _model(db)
    _order(db, affiliate, "1", 1_600_000)
    _order(db, affiliate, "2", 200_000)
    _order(db, affiliate, "3", 200_000)
    august = approve_month(db, affiliate, AUGUST)
    _fail(db, "2")
    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.WRITEOFF,
        reason="absorbed the first",
    )
    _paid(db, affiliate, august, 200_000)

    _fail(db, "3")

    again = correction_for(db, affiliate, AUGUST)
    assert again.shortfall_piastres == 40_000
    assert again.resolved_piastres == 20_000
    assert again.outstanding_piastres == 20_000
    assert again.recoverable_piastres == 20_000


def test_a_month_with_no_room_is_refused_rather_than_settled_for_nothing(db):
    """F12: never a zero-value adjustment standing in for a settlement."""
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    august = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, august, 200_000)
    _fail(db, "1")

    # September has no sales at all, so there is nothing for a deduction to
    # come out of.
    with pytest.raises(ValueError, match="no room"):
        resolve(
            db,
            affiliate,
            AUGUST,
            choice=AdjustmentType.CREDIT,
            reason="nothing to take it from",
            destination_month=SEPTEMBER,
        )

    assert correction_for(db, affiliate, AUGUST).resolved_piastres == 0


def test_a_deduction_can_be_accepted_against_a_month_not_yet_approved(db):
    """F07/F12. The timing the old rule had backwards.

    An overpayment is found in early October; October is not agreed until
    November. Capacity that waited for approval left two choices - write off
    money that should have carried, or remember to come back - and §11.5
    exists to stop anybody relying on the second.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000)
    august = approve_month(db, affiliate, AUGUST)
    _paid(db, affiliate, august, 200_000)
    # September's sales exist; nobody has agreed the month.
    _order(db, affiliate, "2", 5_000_000, month=SEPTEMBER)
    _fail(db, "1")

    assert capacity_of(db, affiliate, SEPTEMBER) == 500_000

    adjustment = resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="carried into the open month",
        destination_month=SEPTEMBER,
    )
    assert adjustment.amount_piastres == 200_000

    # And it is part of what September's approval agrees: the month is worth
    # E£500 and E£200 of it is already spoken for.
    approve_month(db, affiliate, SEPTEMBER)
    assert balance_for(db, affiliate, SEPTEMBER)["balance_piastres"] == 300_000


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
