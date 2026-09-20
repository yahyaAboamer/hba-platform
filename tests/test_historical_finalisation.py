"""Finishing the months that happened before the platform. A09.

ADR 0036 already made a pre-go-live month an ordinary month - calculated,
approved, frozen, and never payable. What was missing was a way to do that for
everybody at once, and the audit's A09 named it: *the approved bulk historical
review entry is absent*.

The approved export's own result line is the specification:

    Months from January 2026 recalculated from Shopify using each model's
    historical terms. No receipts were created; months without an imported
    transfer stay marked as having none.

Each clause is a constraint, and each one has a test here.

**The dividing line these tests exist to hold** is between what the software
may finish on its own and what is waiting on a person. A month whose terms
nobody has written, or a guaranteed month whose outcome nobody has recorded,
cannot be finalised by any amount of code - the information does not exist.
Inventing a rate or assuming an outcome would be fabricating evidence for a
figure that decides money, which H02 forbids and F06 restates. So those months
are reported, by name, and skipped.
"""

from datetime import datetime, timezone

import pytest

from app.core.passwords import hash_password
from app.models.affiliates import AccountKind
from app.models.attributed_orders import AttributedOrder
from app.models.compensation import CompensationType
from app.models.identity import UserAccount
from app.models.orders import OrderIndex
from app.models.payments import PaymentTransaction, PayrollAdjustment
from app.services.affiliates import create_affiliate, set_collaboration_start
from app.services.codes import register_code
from app.services.compensation import set_terms
from app.services.historical import finalise_historical, historical_review
from app.services.payroll import get_month
from app.services.targets import record_outcome

#: Everything before this was settled outside the platform (ADR 0036).
GO_LIVE = "2026-05"
WORKING = "2026-06"


@pytest.fixture(autouse=True)
def _go_live(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", GO_LIVE, raising=False)


def _model(db, name="Nour", *, start="2026-03", terms=True, kind=CompensationType.COMMISSION, base=None):
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
    set_collaboration_start(db, affiliate, start)
    if terms:
        set_terms(
            db,
            affiliate,
            start_month=start,
            compensation_type=kind,
            commission_rate_bp=1000,
            base_amount_piastres=base,
        )
    db.flush()
    return affiliate


def _order(db, affiliate, order_id, base, *, month):
    db.add(
        OrderIndex(
            shopify_order_id=order_id,
            order_number=f"#{order_id}",
            placed_at=datetime(2026, 3, 20, 12, tzinfo=timezone.utc),
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
            commission_state="earned",
        )
    )
    db.flush()


# -- What it finishes ---------------------------------------------------------


def test_it_finalises_every_historical_month_that_can_be_calculated(db):
    """March and April are hers, arranged, and before go-live."""
    affiliate = _model(db)
    _order(db, affiliate, "mar", 1_000_000, month="2026-03")
    _order(db, affiliate, "apr", 2_000_000, month="2026-04")

    result = finalise_historical(db, working=WORKING)

    assert [row["month"] for row in result["approved"]] == ["2026-03", "2026-04"]
    assert result["totals"]["blocked"] == 0
    assert get_month(db, affiliate, "2026-03").is_approved
    assert get_month(db, affiliate, "2026-04").is_approved
    # The figure is the ordinary engine's, from her recorded terms.
    assert result["approved"][0]["obligation_piastres"] == 100_000


def test_a_live_month_is_never_touched(db):
    """The cut is go-live. May is the platform's own, and somebody agrees it
    by looking at it."""
    affiliate = _model(db)
    _order(db, affiliate, "mar", 1_000_000, month="2026-03")
    _order(db, affiliate, "may", 3_000_000, month=GO_LIVE)

    result = finalise_historical(db, working=WORKING)

    assert [row["month"] for row in result["approved"]] == ["2026-03", "2026-04"]
    assert get_month(db, affiliate, GO_LIVE) is None, "May was not opened at all"


# -- What it refuses to invent ------------------------------------------------


def test_a_month_with_no_terms_is_reported_and_skipped(db):
    """The information does not exist, so no amount of code produces it.

    There is no default rate here and no nearest-arrangement guess. H02: never
    fabricate evidence for a figure that decides money.
    """
    affiliate = _model(db, terms=False)
    _order(db, affiliate, "mar", 1_000_000, month="2026-03")

    result = finalise_historical(db, working=WORKING)

    assert result["approved"] == []
    assert [(row["name"], row["month"], row["missing"]) for row in result["blocked"]] == [
        ("Nour", "2026-03", ["no_terms"]),
        ("Nour", "2026-04", ["no_terms"]),
    ]
    assert get_month(db, affiliate, "2026-03") is None


def test_a_guarantee_with_no_recorded_outcome_is_reported_and_skipped(db):
    """F06. Unknown qualifying information blocks the decision; it does not
    read as a failure, and it is certainly not assumed to be a pass."""
    affiliate = _model(db, kind=CompensationType.BASE_GUARANTEE, base=300_000)
    _order(db, affiliate, "mar", 1_000_000, month="2026-03")

    result = finalise_historical(db, working=WORKING)

    assert result["approved"] == []
    assert {row["missing"][0] for row in result["blocked"]} == {"no_target_outcome"}


def test_once_the_outcome_is_recorded_the_same_month_finalises(db):
    """The other half of the sentence above: the software was never the thing
    missing, and the moment a person supplies the fact it finishes."""
    affiliate = _model(db, kind=CompensationType.BASE_GUARANTEE, base=300_000)
    _order(db, affiliate, "mar", 1_000_000, month="2026-03")
    assert finalise_historical(db, working=WORKING)["approved"] == []

    for month in ("2026-03", "2026-04"):
        record_outcome(db, affiliate, month, outcome="met")

    result = finalise_historical(db, working=WORKING)

    assert [row["month"] for row in result["approved"]] == ["2026-03", "2026-04"]
    # max(commission, base): E£1,000 of commission against a E£3,000 floor.
    assert result["approved"][0]["obligation_piastres"] == 300_000


# -- What it never creates ----------------------------------------------------


def test_no_payment_receipt_or_adjustment_is_created(db):
    """The approved result line promises this in as many words: *no receipts
    were created; months without an imported transfer stay marked as having
    none*.
    """
    from sqlalchemy import func, select

    affiliate = _model(db)
    _order(db, affiliate, "mar", 1_000_000, month="2026-03")

    finalise_historical(db, working=WORKING)

    assert db.scalar(select(func.count()).select_from(PaymentTransaction)) == 0
    assert db.scalar(select(func.count()).select_from(PayrollAdjustment)) == 0
    # And ADR 0036's guarantee holds on the other side: nothing is owed.
    from app.services.payments import balance_for

    assert balance_for(db, affiliate, "2026-03")["balance_piastres"] == 0


def test_it_sends_no_month_closed_notice(db):
    """ADR 0036. Twenty-one models times eight months is a hundred and seventy
    mails announcing that a month closed - months that closed and were paid
    before the platform existed. `approve_month` suppresses them, and running
    this in bulk is exactly the case it was suppressed for.
    """
    from sqlalchemy import func, select

    from app.models.notifications import NotificationOutbox

    affiliate = _model(db)
    _order(db, affiliate, "mar", 1_000_000, month="2026-03")

    finalise_historical(db, working=WORKING)

    assert db.scalar(select(func.count()).select_from(NotificationOutbox)) == 0


# -- Running it twice ---------------------------------------------------------


def test_running_it_again_changes_nothing(db):
    """Idempotent, which is what makes an interrupted run safe to finish.

    A timeout, a closed browser, a deploy mid-run: the repair is to press it
    again, not to work out where it stopped.
    """
    affiliate = _model(db)
    _order(db, affiliate, "mar", 1_000_000, month="2026-03")

    first = finalise_historical(db, working=WORKING)
    versions = {
        month: get_month(db, affiliate, month).active_snapshot_id
        for month in ("2026-03", "2026-04")
    }

    second = finalise_historical(db, working=WORKING)

    assert first["totals"]["approved"] == 2
    assert second["totals"]["approved"] == 0, "nothing left to do"
    assert second["totals"]["already_finalised"] == 2
    assert {
        month: get_month(db, affiliate, month).active_snapshot_id
        for month in ("2026-03", "2026-04")
    } == versions, "05B: an agreed month is never unmade, or restated"


def test_a_half_finished_run_is_finished_by_running_it_again(db):
    """The interruption case, built rather than described.

    One model is arranged and one is not. The first run finalises what it can
    and reports the rest; somebody then records the missing terms; the second
    run picks up exactly those months and leaves the first model's alone.
    """
    ready = _model(db, name="Nour")
    later = _model(db, name="Sara", terms=False)
    _order(db, ready, "n-mar", 1_000_000, month="2026-03")
    _order(db, later, "s-mar", 1_000_000, month="2026-03")

    first = finalise_historical(db, working=WORKING)
    assert {row["name"] for row in first["approved"]} == {"Nour"}
    assert {row["name"] for row in first["blocked"]} == {"Sara"}

    set_terms(
        db,
        later,
        start_month="2026-03",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    db.flush()

    second = finalise_historical(db, working=WORKING)

    assert {row["name"] for row in second["approved"]} == {"Sara"}
    assert second["totals"]["blocked"] == 0
    assert second["totals"]["already_finalised"] == 2, "Nour's, untouched"


# -- The dry run --------------------------------------------------------------


def test_the_review_writes_nothing(db):
    """A09 is as much about what is still missing as about what can be
    finished, so finding out must not be an act."""
    affiliate = _model(db)
    _order(db, affiliate, "mar", 1_000_000, month="2026-03")

    plan = historical_review(db, working=WORKING)

    assert [row["month"] for row in plan["ready"]] == ["2026-03", "2026-04"]
    assert plan["from_month"] == "2026-03"
    assert get_month(db, affiliate, "2026-03") is None, "nothing was opened"


def test_the_review_separates_what_is_ready_from_what_needs_a_person(db):
    """The whole point of the separation, on one roster."""
    _model(db, name="Nour")
    _model(db, name="Sara", terms=False)

    plan = historical_review(db, working=WORKING)

    assert plan["totals"]["ready"] == 2, "Nour's March and April"
    assert plan["totals"]["blocked"] == 2, "Sara's, waiting on her terms"
    assert plan["totals"]["models"] == 2
