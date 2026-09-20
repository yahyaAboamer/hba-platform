"""What a correction actually costs, at both ends of it.

The follow-up review of Batch 1 found two arithmetic defects that every
existing test walked past, because each of them needs **two** facts held at
once — two credits rather than one, or a source month's balance rather than
its correction status.

## F1 — the second credit from one source was never released

`_release_deductions_the_month_cannot_take` walked the individual credit rows
and subtracted, from each one, the releases recorded for its whole
source-and-destination *pair*. With one credit those are the same number. With
two, the release written for the first was subtracted from the second as well,
the second looked fully released already, and half the deduction stayed on a
month that had nothing to pay it with.

## F2 — a correction reduced the month it came from, twice over

`balance_for` subtracted every outgoing credit and write-off from whatever the
month still owed. A month agreed at E£2,000 with E£1,000 sent and E£200
carried forward reported E£800 left to send. The E£200 was then recovered
*again* out of the destination month, so HBA kept it twice and the model was
paid E£1,800 against an agreement of E£2,000.

Absorbing had the mirror-image fault: HBA "taking the loss" reduced the money
HBA still owed her, which is the opposite of taking a loss.

The invariant both of these break is one sentence. **An agreed month's unpaid
obligation is settled by paying it** (05B). A correction decides what happens
to money that has *already moved*; it has no business touching money that has
not.

These are regression tests. Each was written to fail against ea46413 and named
so the failure says which half of the review it belongs to.
"""

from datetime import datetime, timezone

import pytest

from app.core.passwords import hash_password
from app.models.affiliates import AccountKind
from app.models.attributed_orders import AttributedOrder, CommissionState
from app.models.compensation import CompensationType
from app.models.identity import UserAccount
from app.models.orders import OrderIndex
from app.models.payments import AdjustmentType, PayrollAdjustment
from app.services.affiliates import create_affiliate
from app.services.codes import register_code
from app.services.compensation import set_terms
from app.services.corrections import correction_for, resolve
from app.services.payments import balance_for, credited_into, record_payment
from app.services.payroll import approve_month, get_month
from app.services.targets import record_actuals, set_requirements, verify

JUNE = "2026-06"
JULY = "2026-07"
AUGUST = "2026-08"
SEPTEMBER = "2026-09"
OCTOBER = "2026-10"


@pytest.fixture(autouse=True)
def _go_live(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)


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
    affiliate.collaboration_start_month = "2026-01"
    db.flush()
    return affiliate


def _order(db, affiliate, order_id, base, *, month, state=CommissionState.EARNED):
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


def _fail(db, order_id):
    db.get(AttributedOrder, order_id).commission_state = CommissionState.VOID
    db.flush()


def _adjustments(db, affiliate, kind):
    """Every adjustment of one kind, as (source month, destination, amount)."""
    from app.models.payroll import PayrollMonth

    months = {
        row.id: row.month
        for row in db.scalars(
            __import__("sqlalchemy")
            .select(PayrollMonth)
            .where(PayrollMonth.affiliate_id == affiliate.id)
        )
    }
    rows = db.scalars(
        __import__("sqlalchemy")
        .select(PayrollAdjustment)
        .where(PayrollAdjustment.type == kind)
        .order_by(PayrollAdjustment.id)
    )
    return [
        (
            months.get(row.source_payroll_month_id),
            months.get(row.destination_payroll_month_id),
            row.amount_piastres,
        )
        for row in rows
        if row.source_payroll_month_id in months
    ]


# -- F1. Two credits from one source ------------------------------------------


def _source_overpaid_twice(db, affiliate, *, first, second, destination_worth):
    """August agreed at E£2,000, paid in full, and failing in two instalments.

    Each failure is carried separately into the destination month, which is why
    two credits share one source-and-destination pair — the shape the release
    accounting got wrong. The destination is left worth `destination_worth`
    when it is agreed.
    """
    _order(db, affiliate, "aug-1", first * 10, month=AUGUST)
    _order(db, affiliate, "aug-2", second * 10, month=AUGUST)
    _order(db, affiliate, "aug-keep", 1_000_000, month=AUGUST)
    august = approve_month(db, affiliate, AUGUST)
    record_payment(
        db,
        affiliate,
        amount_piastres=august.approved_obligation_piastres,
        allocations={august.id: august.approved_obligation_piastres},
    )

    # The destination has to be worth enough to accept both carries at the time
    # they are made. It falls later, which is the whole situation.
    _order(db, affiliate, "oct-big", (first + second) * 10, month=OCTOBER)
    if destination_worth:
        _order(db, affiliate, "oct-keep", destination_worth * 10, month=OCTOBER)

    _fail(db, "aug-1")
    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="first failure",
        destination_month=OCTOBER,
    )
    _fail(db, "aug-2")
    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="second failure",
        destination_month=OCTOBER,
    )
    assert credited_into(db, get_month(db, affiliate, OCTOBER)) == first + second

    # And now the destination itself loses the sale it was going to pay with.
    _fail(db, "oct-big")
    return approve_month(db, affiliate, OCTOBER)


def test_two_equal_credits_from_one_source_are_both_released(db):
    """F1. The reproduction, at its plainest.

    Two carries of E£1,000 land on October; October is agreed at nothing. Both
    have to come back. Releasing one of them and calling the other applied
    leaves E£1,000 of deduction sitting on a month with no money in it, and
    tells August its difference is settled when half of it is not.
    """
    affiliate = _model(db)
    _source_overpaid_twice(
        db, affiliate, first=100_000, second=100_000, destination_worth=0
    )

    assert credited_into(db, get_month(db, affiliate, OCTOBER)) == 0
    assert _adjustments(db, affiliate, AdjustmentType.RELEASE) == [
        (AUGUST, OCTOBER, 200_000)
    ]
    # And the source correction opens again by exactly what could not land.
    assert correction_for(db, affiliate, AUGUST).outstanding_piastres == 200_000


def test_unequal_credits_release_only_what_the_month_cannot_take(db):
    """F1. A partial release, which is the ordinary case.

    E£1,200 and E£800 land on October; October is agreed at E£500. It keeps
    E£500 and hands back E£1,500 — not "the newest credit and then nothing".
    """
    affiliate = _model(db)
    _source_overpaid_twice(
        db, affiliate, first=120_000, second=80_000, destination_worth=50_000
    )

    assert credited_into(db, get_month(db, affiliate, OCTOBER)) == 50_000
    assert _adjustments(db, affiliate, AdjustmentType.RELEASE) == [
        (AUGUST, OCTOBER, 150_000)
    ]
    assert correction_for(db, affiliate, AUGUST).outstanding_piastres == 150_000
    # The month is square: it was agreed at E£500 and E£500 of deduction is on
    # it, so nothing is sent and nothing is owed.
    assert balance_for(db, affiliate, OCTOBER)["balance_piastres"] == 0


def test_a_second_release_pass_gives_nothing_back_twice(db):
    """F1. Netting has to be idempotent, or a retry doubles the remainder.

    The helper is called again with the month already agreed and already
    released. There is nothing left over-applied, so it must find nothing.
    """
    from app.services.payroll import _release_deductions_the_month_cannot_take

    affiliate = _model(db)
    snapshot = _source_overpaid_twice(
        db, affiliate, first=100_000, second=100_000, destination_worth=0
    )

    again = _release_deductions_the_month_cannot_take(
        db, affiliate, get_month(db, affiliate, OCTOBER), snapshot
    )
    assert again == 0
    assert _adjustments(db, affiliate, AdjustmentType.RELEASE) == [
        (AUGUST, OCTOBER, 200_000)
    ]
    assert correction_for(db, affiliate, AUGUST).outstanding_piastres == 200_000


def test_two_sources_are_released_newest_first(db):
    """F1. Two months carried into one, and only some room to share.

    June and July are each owed E£1,000 back out of September, which is agreed
    at E£500. The newest carry is the one that over-committed the month, so
    July gives back everything and June gives back half — and each release goes
    home to its own source, not to whichever one the loop reached first.
    """
    affiliate = _model(db)
    for month, order in ((JUNE, "jun"), (JULY, "jul")):
        _order(db, affiliate, order, 1_000_000, month=month)
        snapshot = approve_month(db, affiliate, month)
        record_payment(
            db,
            affiliate,
            amount_piastres=100_000,
            allocations={snapshot.id: 100_000},
        )
    _order(db, affiliate, "sep-big", 2_000_000, month=SEPTEMBER)
    _order(db, affiliate, "sep-keep", 500_000, month=SEPTEMBER)

    for month, order in ((JUNE, "jun"), (JULY, "jul")):
        _fail(db, order)
        resolve(
            db,
            affiliate,
            month,
            choice=AdjustmentType.CREDIT,
            reason=f"carried from {month}",
            destination_month=SEPTEMBER,
        )
    assert credited_into(db, get_month(db, affiliate, SEPTEMBER)) == 200_000

    _fail(db, "sep-big")
    approve_month(db, affiliate, SEPTEMBER)

    assert credited_into(db, get_month(db, affiliate, SEPTEMBER)) == 50_000
    assert _adjustments(db, affiliate, AdjustmentType.RELEASE) == [
        (JULY, SEPTEMBER, 100_000),
        (JUNE, SEPTEMBER, 50_000),
    ]
    assert correction_for(db, affiliate, JULY).outstanding_piastres == 100_000
    assert correction_for(db, affiliate, JUNE).outstanding_piastres == 50_000


def test_a_month_that_can_take_the_whole_deduction_releases_nothing(db):
    """F1. The ordinary approval, which must stay silent.

    October is agreed at E£2,000 and E£2,000 of deduction lands on it. It takes
    all of it, sends nothing, and writes no release.
    """
    affiliate = _model(db)
    _source_overpaid_twice(
        db, affiliate, first=100_000, second=100_000, destination_worth=200_000
    )

    assert credited_into(db, get_month(db, affiliate, OCTOBER)) == 200_000
    assert _adjustments(db, affiliate, AdjustmentType.RELEASE) == []
    assert correction_for(db, affiliate, AUGUST).outstanding_piastres == 0


def test_the_snapshot_says_what_the_deduction_actually_came_to(db):
    """F1, F07. Frozen evidence of the allocation *and* of what it could do.

    Approval builds its payload before it works out what the month can absorb,
    so the deduction list on its own is the gross request — E£2,000 against a
    month worth nothing. A statement rendered from that would tell somebody
    E£2,000 was deducted, when E£2,000 was asked for and nothing was taken.

    Both figures are frozen: the allocation that was reviewed, and the amount
    it actually came to.
    """
    affiliate = _model(db)
    snapshot = _source_overpaid_twice(
        db, affiliate, first=100_000, second=100_000, destination_worth=0
    )
    body = snapshot.payload_json

    assert [row["amount_piastres"] for row in body["deductions"]] == [
        100_000,
        100_000,
    ], "the reviewed allocation is still frozen exactly as it was agreed"
    assert body["deductions_applied_piastres"] == 0
    assert body["deductions_released_piastres"] == 200_000
    assert body["deductions_released"] == [
        {"from_month": AUGUST, "amount_piastres": 200_000}
    ]


# -- F2. What a correction does to the month it came from ---------------------


def _partly_paid_august(db, affiliate, *, paid):
    """August agreed at E£2,000, `paid` sent, and E£200 of it failing later."""
    _order(db, affiliate, "aug-most", 1_800_000, month=AUGUST)
    _order(db, affiliate, "aug-lost", 200_000, month=AUGUST)
    august = approve_month(db, affiliate, AUGUST)
    assert august.approved_obligation_piastres == 200_000
    if paid:
        record_payment(
            db, affiliate, amount_piastres=paid, allocations={august.id: paid}
        )
    _order(db, affiliate, "sep-1", 5_000_000, month=SEPTEMBER)
    _fail(db, "aug-lost")
    return august


def test_carrying_a_correction_does_not_reduce_what_the_source_still_owes(db):
    """F2. The reproduction. E£1,000 sent of E£2,000, E£200 carried forward.

    August is still owed E£1,000. The E£200 is recovered out of September,
    where the credit lands. Taking it off August as well recovers it twice and
    pays her E£1,800 against an agreement of E£2,000.
    """
    affiliate = _model(db)
    _partly_paid_august(db, affiliate, paid=100_000)

    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="carried into September",
        destination_month=SEPTEMBER,
    )

    august = balance_for(db, affiliate, AUGUST)
    assert august["balance_piastres"] == 100_000, (
        "the agreed figure is still owed; the correction recovers money that "
        "already moved, not money that has not"
    )
    # And the recovery does happen — once, in the month it was carried to.
    approve_month(db, affiliate, SEPTEMBER)
    september = balance_for(db, affiliate, SEPTEMBER)
    assert september["credited_piastres"] == 20_000
    assert september["balance_piastres"] == 480_000

    # The whole of it in one line: what HBA sends from here, against what the
    # two agreements came to less the sale that did not stand.
    assert august["balance_piastres"] + september["balance_piastres"] == (
        200_000 + 500_000 - 100_000 - 20_000
    )


def test_absorbing_a_correction_does_not_forgive_what_is_still_owed(db):
    """F2. HBA taking the loss cannot mean paying her less.

    Same month, absorbed instead of carried. HBA eats the E£200 over-agreement;
    the E£1,000 it has not yet sent is untouched by that decision.
    """
    affiliate = _model(db)
    _partly_paid_august(db, affiliate, paid=100_000)

    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.WRITEOFF,
        reason="HBA absorbs it",
    )

    assert balance_for(db, affiliate, AUGUST)["balance_piastres"] == 100_000
    assert correction_for(db, affiliate, AUGUST).outstanding_piastres == 0


def test_a_fully_paid_month_is_square_after_the_carry(db):
    """F2. The case the old arithmetic happened to get right, held in place.

    Everything agreed was sent, so nothing is outstanding, and the E£200 comes
    back out of September rather than out of a balance that is already zero.
    """
    affiliate = _model(db)
    _partly_paid_august(db, affiliate, paid=200_000)

    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="carried into September",
        destination_month=SEPTEMBER,
    )

    approve_month(db, affiliate, SEPTEMBER)
    assert balance_for(db, affiliate, AUGUST)["balance_piastres"] == 0
    assert balance_for(db, affiliate, SEPTEMBER)["balance_piastres"] == 480_000


def test_an_unpaid_month_keeps_its_whole_obligation_when_absorbed(db):
    """F2, R4. Nothing was sent, so nothing can come back.

    The difference is real and somebody decides about it. What they decide
    cannot be *she is owed E£200 less*.
    """
    affiliate = _model(db)
    _partly_paid_august(db, affiliate, paid=0)

    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.WRITEOFF,
        reason="nothing was sent; HBA absorbs the difference",
    )

    assert balance_for(db, affiliate, AUGUST)["balance_piastres"] == 200_000
    assert _adjustments(db, affiliate, AdjustmentType.ACCEPTED) == [
        (AUGUST, None, 20_000)
    ]


def test_an_overpaid_month_is_still_closed_by_its_adjustment(db):
    """ADR 0035, unchanged. The case the subtraction was written for.

    More was sent than the month was ever agreed at. *That* is an excess a
    credit or a write-off closes, and the fix for F2 must not reach it: the
    difference runs the other way, and so does the arithmetic.
    """
    affiliate = _model(db)
    _order(db, affiliate, "aug-1", 2_000_000, month=AUGUST)
    august = approve_month(db, affiliate, AUGUST)
    record_payment(
        db, affiliate, amount_piastres=250_000, allocations={august.id: 250_000}
    )

    assert balance_for(db, affiliate, AUGUST)["balance_piastres"] == -50_000

    _order(db, affiliate, "sep-1", 5_000_000, month=SEPTEMBER)
    from app.services.payments import adjust

    adjust(
        db,
        affiliate,
        kind=AdjustmentType.CREDIT,
        source_month=AUGUST,
        destination_month=SEPTEMBER,
        amount_piastres=50_000,
        reason="the overpayment carries into September",
    )

    assert balance_for(db, affiliate, AUGUST)["balance_piastres"] == 0
    approve_month(db, affiliate, SEPTEMBER)
    assert balance_for(db, affiliate, SEPTEMBER)["credited_piastres"] == 50_000


def _arrangement(db, name, **terms):
    """A model on one of the other two arrangements, from August."""
    affiliate = _model(db, name=name)
    set_terms(db, affiliate, start_month=AUGUST, **terms)
    return affiliate


def test_a_salary_month_still_owes_its_fixed_part_after_a_correction(db):
    """F2. Both halves of `fixed_plus_commission` are paid, and stay payable.

    E£1,000 salary and E£2,000 commission agreed, half of it sent, and E£200 of
    the commission lost to a refused parcel. Carrying that E£200 forward
    recovers it from September. What August has not yet sent — salary included
    — is not a second place to recover it from.
    """
    affiliate = _arrangement(
        db,
        "Mariam",
        compensation_type=CompensationType.FIXED_PLUS_COMMISSION,
        commission_rate_bp=1000,
        fixed_amount_piastres=100_000,
    )
    _order(db, affiliate, "aug-most", 1_800_000, month=AUGUST)
    _order(db, affiliate, "aug-lost", 200_000, month=AUGUST)
    august = approve_month(db, affiliate, AUGUST)
    assert august.approved_obligation_piastres == 300_000
    record_payment(
        db, affiliate, amount_piastres=150_000, allocations={august.id: 150_000}
    )
    _order(db, affiliate, "sep-1", 5_000_000, month=SEPTEMBER)
    _fail(db, "aug-lost")

    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="carried into September",
        destination_month=SEPTEMBER,
    )

    assert correction_for(db, affiliate, AUGUST).agreed_piastres == 300_000
    assert balance_for(db, affiliate, AUGUST)["balance_piastres"] == 150_000


def test_a_qualified_guarantee_month_still_owes_what_it_was_agreed_at(db):
    """F2, D04. A month that met and verified its targets, then lost a sale.

    The guarantee is the floor, not the figure: this month earned above it, so
    the failure moves the total and the floor never comes into it. What was
    agreed was agreed (05B), and half of it is still to send after the
    correction is carried.
    """
    affiliate = _arrangement(
        db,
        "Salma",
        compensation_type=CompensationType.BASE_GUARANTEE,
        commission_rate_bp=1000,
        base_amount_piastres=100_000,
    )
    target = set_requirements(db, affiliate, AUGUST, videos=4, stories=8)
    record_actuals(db, target, videos=4, stories=8)
    verify(db, target)

    _order(db, affiliate, "aug-most", 1_800_000, month=AUGUST)
    _order(db, affiliate, "aug-lost", 200_000, month=AUGUST)
    august = approve_month(db, affiliate, AUGUST)
    assert august.approved_obligation_piastres == 200_000
    record_payment(
        db, affiliate, amount_piastres=100_000, allocations={august.id: 100_000}
    )
    _order(db, affiliate, "sep-1", 5_000_000, month=SEPTEMBER)
    _fail(db, "aug-lost")

    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="carried into September",
        destination_month=SEPTEMBER,
    )

    assert balance_for(db, affiliate, AUGUST)["balance_piastres"] == 100_000


def test_a_released_carry_reopens_an_overpaid_month_too(db):
    """F1 and ADR 0035 together, and a gap the first F2 fix opened.

    August was **overpaid**: E£2,500 sent against an agreed E£2,000. The E£500
    is carried into October, and October turns out to be worth nothing, so the
    carry comes straight back.

    The recovery bounced, so August is overpaid again by exactly E£500. A
    release that nets out of the correction but not out of the balance would
    leave the credit counted and the release ignored, and August would read as
    settled on a recovery that never happened.
    """
    affiliate = _model(db)
    _order(db, affiliate, "aug-1", 2_000_000, month=AUGUST)
    august = approve_month(db, affiliate, AUGUST)
    record_payment(
        db, affiliate, amount_piastres=250_000, allocations={august.id: 250_000}
    )
    assert balance_for(db, affiliate, AUGUST)["balance_piastres"] == -50_000

    _order(db, affiliate, "oct-1", 500_000, month=OCTOBER)
    from app.services.payments import adjust

    adjust(
        db,
        affiliate,
        kind=AdjustmentType.CREDIT,
        source_month=AUGUST,
        destination_month=OCTOBER,
        amount_piastres=50_000,
        reason="the overpayment carries into October",
    )
    assert balance_for(db, affiliate, AUGUST)["balance_piastres"] == 0

    # October loses the sale it was going to absorb the deduction with.
    _fail(db, "oct-1")
    approve_month(db, affiliate, OCTOBER)

    assert credited_into(db, get_month(db, affiliate, OCTOBER)) == 0
    assert balance_for(db, affiliate, AUGUST)["balance_piastres"] == -50_000, (
        "the recovery bounced, so the overpayment is open again"
    )


def test_a_released_carry_leaves_the_source_owed_exactly_what_it_was(db):
    """F1 and F2 together, which is where a double count would hide.

    August is owed E£1,000 and carries E£2,000 into an October that turns out
    to be worth nothing. The release reopens the correction; neither the credit
    nor the release may move what August is still owed, and the E£2,000 must
    end up applied nowhere at all.
    """
    affiliate = _model(db)
    _order(db, affiliate, "aug-most", 1_800_000, month=AUGUST)
    _order(db, affiliate, "aug-lost", 200_000, month=AUGUST)
    august = approve_month(db, affiliate, AUGUST)
    record_payment(
        db, affiliate, amount_piastres=100_000, allocations={august.id: 100_000}
    )
    _order(db, affiliate, "oct-big", 2_000_000, month=OCTOBER)
    _fail(db, "aug-lost")
    resolve(
        db,
        affiliate,
        AUGUST,
        choice=AdjustmentType.CREDIT,
        reason="carried into October",
        destination_month=OCTOBER,
    )
    _fail(db, "oct-big")
    approve_month(db, affiliate, OCTOBER)

    assert balance_for(db, affiliate, AUGUST)["balance_piastres"] == 100_000
    assert credited_into(db, get_month(db, affiliate, OCTOBER)) == 0
    assert correction_for(db, affiliate, AUGUST).outstanding_piastres == 20_000
