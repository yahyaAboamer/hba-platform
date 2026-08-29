"""The payment ledger, and what is still owed.

Phase 7 Tasks 1-3. §14, §11.1, §17.

Two things this exists to make impossible. **A payment that cannot be
reconciled against a bank statement** — hence append-only. And **allocating more
than was sent** — hence a database trigger rather than a review comment.

And one it exists to make unmistakable: a reopened month has **no answer**, not
a balance of zero. Saying "nothing outstanding" about a month paid in full
against a superseded version is the most misleading thing this module could do.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.passwords import hash_password
from app.models.affiliates import AccountKind
from app.models.attributed_orders import AttributedOrder, CommissionState
from app.models.compensation import CompensationType
from app.models.identity import UserAccount
from app.models.orders import OrderIndex
from app.models.payments import (
    AdjustmentType,
    PaymentAllocation,
    PaymentTransaction,
    PayrollAdjustment,
)
from app.services.affiliates import create_affiliate
from app.services.compensation import set_terms
from app.services.payments import (
    allocate,
    balance_due,
    balance_for,
    payments_for,
    record_payment,
)
from app.services.payments_state import SettlementState
from app.services.payouts import set_destination
from app.services.payroll import approve_month, get_month, reopen_month

AUGUST = "2026-08"
SEPTEMBER = "2026-09"


@pytest.fixture(autouse=True)
def _go_live(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)


def _affiliate(db, name="Nour", kind=AccountKind.MODEL):
    account = UserAccount(
        email=f"{name.lower()}@example.com",
        password_hash=hash_password("a-long-enough-password"),
        status="active",
        display_name=name,
    )
    db.add(account)
    db.flush()
    affiliate = create_affiliate(
        db, user_account_id=account.id, name=name, account_kind=kind
    )
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    return affiliate


def _order(db, affiliate, order_id, base, *, month=AUGUST):
    db.add(
        OrderIndex(
            shopify_order_id=order_id,
            order_number=f"#{order_id}",
            placed_at=datetime(2026, 8, 15, 12, tzinfo=timezone.utc),
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


def _owed(db, affiliate, month=AUGUST, base=2_000_000):
    """An approved month with a round obligation. 10% of E£20,000 = E£2,000."""
    _order(db, affiliate, f"{affiliate.id}-{month}", base, month=month)
    return approve_month(db, affiliate, month)


# ── What is owed ───────────────────────────────────────────────────────────────


def test_an_approved_month_starts_unpaid(db):
    affiliate = _affiliate(db)
    _owed(db, affiliate)

    balance = balance_for(db, affiliate, AUGUST)

    assert balance["state"] == SettlementState.UNPAID
    assert balance["obligation_piastres"] == 200_000
    assert balance["balance_piastres"] == 200_000


def test_a_part_payment_leaves_the_rest_owed(db):
    affiliate = _affiliate(db)
    snapshot = _owed(db, affiliate)

    record_payment(db, affiliate, amount_piastres=80_000,
                   allocations={snapshot.id: 80_000})

    balance = balance_for(db, affiliate, AUGUST)
    assert balance["state"] == SettlementState.PARTIALLY_PAID
    assert balance["balance_piastres"] == 120_000


def test_paying_it_all_settles_it(db):
    affiliate = _affiliate(db)
    snapshot = _owed(db, affiliate)

    record_payment(db, affiliate, amount_piastres=200_000,
                   allocations={snapshot.id: 200_000})

    assert balance_for(db, affiliate, AUGUST)["state"] == SettlementState.SETTLED
    assert balance_due(db, affiliate, AUGUST) == 0


def test_two_transfers_can_settle_one_month(db):
    """InstaPay limits force a split. Two transfers settling one month is
    ordinary, and the old system could not represent it.
    """
    affiliate = _affiliate(db)
    snapshot = _owed(db, affiliate)

    record_payment(db, affiliate, amount_piastres=120_000,
                   allocations={snapshot.id: 120_000})
    record_payment(db, affiliate, amount_piastres=80_000,
                   allocations={snapshot.id: 80_000})

    assert balance_for(db, affiliate, AUGUST)["state"] == SettlementState.SETTLED


def test_one_transfer_can_cover_two_months(db):
    """§8's worked example: a single E£10,000 transfer applied to August and
    September **without pretending two transfers occurred**.
    """
    affiliate = _affiliate(db)
    august = _owed(db, affiliate, AUGUST, base=1_400_000)
    september = _owed(db, affiliate, SEPTEMBER, base=600_000)

    record_payment(
        db,
        affiliate,
        amount_piastres=200_000,
        allocations={august.id: 140_000, september.id: 60_000},
    )

    assert balance_for(db, affiliate, AUGUST)["state"] == SettlementState.SETTLED
    assert balance_for(db, affiliate, SEPTEMBER)["state"] == SettlementState.SETTLED
    assert len(payments_for(db, affiliate)) == 1, "one transfer, not two"


def test_overpaying_is_reported_not_refused(db):
    """Not an error - a rounding split, a fee covered, or a month reopened to a
    lower figure after it was paid. It is reported so somebody can decide on a
    credit or a write-off.
    """
    affiliate = _affiliate(db)
    snapshot = _owed(db, affiliate)

    record_payment(db, affiliate, amount_piastres=250_000,
                   allocations={snapshot.id: 250_000})

    balance = balance_for(db, affiliate, AUGUST)
    assert balance["state"] == SettlementState.OVERPAID
    assert balance["balance_piastres"] == -50_000


def test_a_month_owing_nothing_is_settled_not_unpaid(db):
    """A model with no sales is not carrying a debt of zero, and showing one on
    her row would have somebody chasing it.
    """
    affiliate = _affiliate(db)
    approve_month(db, affiliate, AUGUST)

    assert balance_for(db, affiliate, AUGUST)["state"] == SettlementState.SETTLED


def test_the_balance_shows_what_makes_it_up(db):
    """A balance nobody can take apart is a balance nobody can argue with."""
    affiliate = _affiliate(db)
    snapshot = _owed(db, affiliate)
    record_payment(db, affiliate, amount_piastres=50_000,
                   allocations={snapshot.id: 50_000})

    balance = balance_for(db, affiliate, AUGUST)

    assert balance["obligation_piastres"] == 200_000
    assert balance["paid_piastres"] == 50_000
    assert balance["version"] == 1


# ── A reopened month has no answer ─────────────────────────────────────────────


def test_a_month_never_approved_has_nothing_to_settle(db):
    affiliate = _affiliate(db)

    assert balance_for(db, affiliate, AUGUST)["state"] == (
        SettlementState.NOT_APPROVED
    )


def test_a_reopened_month_is_unanswerable_not_settled(db):
    """The most misleading thing this module could do is say "nothing
    outstanding" about a month paid in full against a superseded version.
    """
    affiliate = _affiliate(db)
    snapshot = _owed(db, affiliate)
    record_payment(db, affiliate, amount_piastres=200_000,
                   allocations={snapshot.id: 200_000})
    reopen_month(db, affiliate, AUGUST, reason="an order was not hers")

    balance = balance_for(db, affiliate, AUGUST)

    assert balance["state"] == SettlementState.NOT_APPROVED
    assert balance["reopened"] is True


def test_the_allocation_survives_a_reopen(db):
    """§11.5. Money that moved does not un-move because a calculation was
    revisited - and the allocation names the **version** it settled, which is
    what makes that expressible.
    """
    affiliate = _affiliate(db)
    snapshot = _owed(db, affiliate)
    record_payment(db, affiliate, amount_piastres=200_000,
                   allocations={snapshot.id: 200_000})
    reopen_month(db, affiliate, AUGUST, reason="recalculating")

    still_there = db.scalars(
        text("SELECT allocated_piastres FROM payment_allocation")
    ).all()
    assert still_there == [200_000]


def test_money_already_sent_still_counts_after_a_reopen(db):
    """The bug that could have paid somebody twice.

    A payment settles the **version** it was allocated to, and that stays true
    - §11.5 keeps it attached there. What is *owed*, though, is a question
    about the month, and the two diverge the moment a month is agreed again.

    This test previously asserted `paid_piastres == 0` after re-approval, on
    the reasoning that carrying the allocation across would claim version 2 had
    been paid when it had not. Right about the version, wrong about the
    balance: the screen then told somebody to send the whole new figure to a
    model who had already received most of it.
    """
    affiliate = _affiliate(db)
    _owed(db, affiliate)
    snapshot = get_month(db, affiliate, AUGUST).active_snapshot
    record_payment(db, affiliate, amount_piastres=200_000,
                   allocations={snapshot.id: 200_000})
    reopen_month(db, affiliate, AUGUST, reason="an order was missing")
    _order(db, affiliate, "extra", 1_000_000)
    approve_month(db, affiliate, AUGUST)

    balance = balance_for(db, affiliate, AUGUST)

    assert balance["version"] == 2
    # Nothing has been allocated to version 2 - the fact the old test was
    # protecting, kept and named for what it is.
    assert balance["paid_this_version_piastres"] == 0
    # And E£2,000 has left the bank for this month, so it is not still owed.
    assert balance["paid_piastres"] == 200_000
    assert balance["paid_earlier_versions_piastres"] == 200_000
    assert balance["balance_piastres"] == (
        balance["obligation_piastres"] - 200_000
    )
    assert balance["state"] == SettlementState.PARTIALLY_PAID


def test_every_version_of_a_month_is_reported(db):
    """A single figure with a small "v2" beside it cannot answer the only
    question somebody has on seeing one: is this the whole amount, or what is
    left?
    """
    affiliate = _affiliate(db)
    _owed(db, affiliate)
    snapshot = get_month(db, affiliate, AUGUST).active_snapshot
    first = snapshot.approved_obligation_piastres
    record_payment(db, affiliate, amount_piastres=200_000,
                   allocations={snapshot.id: 200_000})
    reopen_month(db, affiliate, AUGUST, reason="an order was missing")
    _order(db, affiliate, "extra", 1_000_000)
    approve_month(db, affiliate, AUGUST)

    versions = balance_for(db, affiliate, AUGUST)["versions"]

    assert [v["version"] for v in versions] == [1, 2]
    assert versions[0]["obligation_piastres"] == first
    assert versions[0]["paid_piastres"] == 200_000
    assert versions[0]["is_current"] is False
    assert versions[1]["paid_piastres"] == 0
    assert versions[1]["is_current"] is True


def test_a_month_agreed_once_has_one_version(db):
    """The ordinary case stays ordinary - no history panel to explain away."""
    affiliate = _affiliate(db)
    _owed(db, affiliate)

    versions = balance_for(db, affiliate, AUGUST)["versions"]

    assert len(versions) == 1
    assert versions[0]["is_current"] is True


# ── What the database refuses ──────────────────────────────────────────────────


def test_allocating_more_than_was_sent_is_impossible(db):
    """§17, and a trigger rather than a review comment. "We allocated E£12,000
    of a E£10,000 transfer" has to be impossible.
    """
    affiliate = _affiliate(db)
    snapshot = _owed(db, affiliate)
    transaction = record_payment(db, affiliate, amount_piastres=100_000)

    allocate(db, transaction, snapshot, 60_000)

    with pytest.raises(DBAPIError, match="transfer"):
        allocate(db, transaction, snapshot, 50_000)
    db.rollback()


def test_the_service_refuses_it_before_the_database_does(db):
    """The constraint is what makes it true; the message is for a person."""
    affiliate = _affiliate(db)
    snapshot = _owed(db, affiliate)

    with pytest.raises(ValueError, match="more than the"):
        record_payment(
            db, affiliate, amount_piastres=100_000,
            allocations={snapshot.id: 150_000},
        )


def test_leaving_a_transfer_unallocated_is_allowed(db):
    """A transfer may arrive before anybody has decided which months it covers,
    and forcing a split at that moment would invent an answer.
    """
    affiliate = _affiliate(db)
    _owed(db, affiliate)

    transaction = record_payment(db, affiliate, amount_piastres=100_000)

    assert transaction.unallocated_piastres == 100_000
    assert balance_for(db, affiliate, AUGUST)["state"] == SettlementState.UNPAID


@pytest.mark.parametrize("amount", [0, -1])
def test_a_payment_of_nothing_is_refused(db, amount):
    affiliate = _affiliate(db)

    with pytest.raises(ValueError):
        record_payment(db, affiliate, amount_piastres=amount)


def test_the_database_refuses_a_negative_payment_too(db):
    affiliate = _affiliate(db)

    db.add(PaymentTransaction(affiliate_id=affiliate.id, amount_piastres=-1))
    with pytest.raises(IntegrityError):
        db.flush()


def test_a_payment_cannot_be_edited(db):
    """§17. A payment that can be edited is a payment nobody can reconcile
    against a bank statement.
    """
    affiliate = _affiliate(db)
    transaction = record_payment(db, affiliate, amount_piastres=100_000)
    db.commit()

    with pytest.raises(DBAPIError):
        db.execute(
            text("UPDATE payment_transaction SET amount_piastres = 1 WHERE id = :i"),
            {"i": transaction.id},
        )
    db.rollback()


def test_a_payment_cannot_be_deleted(db):
    affiliate = _affiliate(db)
    transaction = record_payment(db, affiliate, amount_piastres=100_000)
    db.commit()

    with pytest.raises(DBAPIError):
        db.execute(
            text("DELETE FROM payment_transaction WHERE id = :i"),
            {"i": transaction.id},
        )
    db.rollback()


def test_an_allocation_cannot_be_edited(db):
    affiliate = _affiliate(db)
    snapshot = _owed(db, affiliate)
    record_payment(db, affiliate, amount_piastres=100_000,
                   allocations={snapshot.id: 100_000})
    db.commit()

    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE payment_allocation SET allocated_piastres = 1"))
    db.rollback()


# ── The destination is frozen and masked ───────────────────────────────────────


def test_the_destination_is_recorded_masked(db):
    """§6.4.4. `mask_destination` is the only sanctioned representation outside
    the owner's own screen, and a payment record is not that screen.
    """
    affiliate = _affiliate(db)
    set_destination(
        db,
        affiliate,
        method="instapay",
        instapay_address_url="https://ipn.eg/nour-abdelrahman-2291",
    )

    transaction = record_payment(db, affiliate, amount_piastres=100_000)

    stored = transaction.destination_snapshot_json
    assert stored["method"] == "instapay"
    assert "nour-abdelrahman" not in str(stored)
    assert stored["instapay_address_url"].startswith("…")


def test_a_payment_survives_its_destination_being_superseded(db):
    """payout_destination is append-only precisely so a past payment resolves
    the destination in force at the time - and copying the masked values means
    this record still reads correctly however many times that row is later
    replaced.
    """
    affiliate = _affiliate(db)
    set_destination(db, affiliate, method="instapay",
                    instapay_address_url="https://ipn.eg/old-address-1111")
    transaction = record_payment(db, affiliate, amount_piastres=100_000)
    original = dict(transaction.destination_snapshot_json)

    set_destination(db, affiliate, method="instapay",
                    instapay_address_url="https://ipn.eg/new-address-2222")

    assert transaction.destination_snapshot_json == original


def test_a_payment_with_no_destination_on_file_is_still_recorded(db):
    """Cash, or a transfer arranged another way. Refusing it would mean the
    record could not show the truth.
    """
    affiliate = _affiliate(db)

    transaction = record_payment(db, affiliate, amount_piastres=100_000)

    assert transaction.destination_snapshot_json is None


# ── Adjustments reduce what is owed ────────────────────────────────────────────


def test_a_write_off_clears_the_rest(db):
    """§11.5. She was overpaid, or the remainder is not worth chasing, and HBA
    absorbs it.
    """
    affiliate = _affiliate(db)
    snapshot = _owed(db, affiliate)
    record_payment(db, affiliate, amount_piastres=190_000,
                   allocations={snapshot.id: 190_000})
    month = get_month(db, affiliate, AUGUST)

    db.add(
        PayrollAdjustment(
            type=AdjustmentType.WRITEOFF,
            source_payroll_month_id=month.id,
            amount_piastres=10_000,
            reason="transfer fee absorbed",
        )
    )
    db.flush()

    assert balance_for(db, affiliate, AUGUST)["state"] == SettlementState.SETTLED


def test_a_credit_increases_what_a_later_month_owes(db):
    """A credit moves an overpayment forward: it reduces the month it came from
    and is expected to raise the one it lands on.
    """
    affiliate = _affiliate(db)
    _owed(db, affiliate, AUGUST)
    _owed(db, affiliate, SEPTEMBER, base=1_000_000)
    august = get_month(db, affiliate, AUGUST)
    september = get_month(db, affiliate, SEPTEMBER)

    db.add(
        PayrollAdjustment(
            type=AdjustmentType.CREDIT,
            source_payroll_month_id=august.id,
            destination_payroll_month_id=september.id,
            amount_piastres=20_000,
            reason="August was reopened to a lower figure",
        )
    )
    db.flush()

    assert balance_for(db, affiliate, AUGUST)["balance_piastres"] == 180_000
    assert balance_for(db, affiliate, SEPTEMBER)["balance_piastres"] == 120_000


def test_an_adjustment_needs_a_reason(db):
    """Money moving without a transfer, and the only thing that makes it
    auditable is why.
    """
    affiliate = _affiliate(db)
    _owed(db, affiliate)
    month = get_month(db, affiliate, AUGUST)

    db.add(
        PayrollAdjustment(
            type=AdjustmentType.WRITEOFF,
            source_payroll_month_id=month.id,
            amount_piastres=1_000,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_an_adjustment_cannot_be_edited(db):
    affiliate = _affiliate(db)
    _owed(db, affiliate)
    month = get_month(db, affiliate, AUGUST)
    db.add(
        PayrollAdjustment(
            type=AdjustmentType.WRITEOFF,
            source_payroll_month_id=month.id,
            amount_piastres=1_000,
            reason="rounding",
        )
    )
    db.commit()

    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE payroll_adjustment SET amount_piastres = 99"))
    db.rollback()


def test_a_credit_opens_the_month_it_lands_on(db):
    """The month a credit carries into does not exist yet, and that is normal.

    An overpayment is found in early October, when October has not been
    approved and so has no row. Refusing until somebody "opened that month
    first" named a step nothing in the platform could perform, leaving a
    write-off as the only way out - money absorbed that should have carried
    forward.
    """
    from app.services.payments import adjust

    affiliate = _affiliate(db)
    _owed(db, affiliate, AUGUST)

    assert get_month(db, affiliate, SEPTEMBER) is None, "September is untouched"

    adjust(
        db,
        affiliate,
        kind=AdjustmentType.CREDIT,
        source_month=AUGUST,
        amount_piastres=20_000,
        reason="August was reopened to a lower figure.",
        destination_month=SEPTEMBER,
    )
    db.flush()

    landed = get_month(db, affiliate, SEPTEMBER)
    assert landed is not None
    assert landed.active_snapshot is None, "opening it agrees nothing"


def test_a_credit_waits_on_a_draft_month_and_applies_when_it_is_approved(db):
    """The credit changes nothing until the month it lands on is agreed.

    Until then there is no figure to reduce, and reporting one would be
    inventing an obligation nobody has approved.
    """
    from app.services.payments import adjust

    affiliate = _affiliate(db)
    _owed(db, affiliate, AUGUST)
    adjust(
        db,
        affiliate,
        kind=AdjustmentType.CREDIT,
        source_month=AUGUST,
        amount_piastres=20_000,
        reason="August was reopened to a lower figure.",
        destination_month=SEPTEMBER,
    )
    db.flush()

    waiting = balance_for(db, affiliate, SEPTEMBER)
    assert waiting["state"] == SettlementState.NOT_APPROVED
    assert waiting["balance_piastres"] == 0

    _owed(db, affiliate, SEPTEMBER, base=1_000_000)
    db.flush()

    # E£1,000 agreed, plus E£200 carried in, and nothing paid yet.
    settled = balance_for(db, affiliate, SEPTEMBER)
    assert settled["credited_piastres"] == 20_000
    assert settled["balance_piastres"] == 120_000


def test_a_month_opened_only_to_receive_a_credit_is_not_reported_as_forgotten(db):
    """§11.5's alarm is for months approved and then reopened.

    A month never approved has no superseded snapshot and no payment stranded
    against one, so raising it would be noise on the one warning that has to be
    believed.
    """
    from app.services.payments import adjust
    from app.services.payroll import months_left_reopened

    affiliate = _affiliate(db)
    _owed(db, affiliate, AUGUST)
    adjust(
        db,
        affiliate,
        kind=AdjustmentType.CREDIT,
        source_month=AUGUST,
        amount_piastres=20_000,
        reason="August was reopened to a lower figure.",
        destination_month=SEPTEMBER,
    )
    db.flush()

    assert months_left_reopened(db, SEPTEMBER) == []
