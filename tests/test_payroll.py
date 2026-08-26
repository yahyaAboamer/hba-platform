"""Agreeing what a month is worth, and freezing it.

Phase 6 Tasks 1-3. §11.

Everything before this recalculates. Ask what April is worth twice and you may
get two answers, because an order was delivered in between. This is where the
number stops moving — and where two checks that have blocked nothing since
Phase 3 and Phase 5 start refusing.
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
from app.models.payroll import CalculationState, PayrollMonth, PayrollSnapshot
from app.services.affiliates import create_affiliate
from app.services.codes import register_code
from app.services.commission.calculate import NO_TERMS
from app.services.compensation import correct_terms, set_terms
from app.services.payroll import (
    ALREADY_APPROVED,
    HOUSE_ACCOUNT,
    ORDERS_ON_HOLD,
    approve_month,
    blockers_for,
    content_hash,
    get_month,
    open_month,
    snapshots_for,
)
from app.services.targets import record_actuals, set_requirements, verify

MONTH = "2026-04"


@pytest.fixture(autouse=True)
def _go_live(monkeypatch):
    """A configured go-live month, so the §11.2 guard does not block every test.

    It blocks by default, and that is deliberate: an unset go-live would
    silently make eight months of imported orders approvable. Every test here
    is about something else, so each one says out loud that the month is
    configured rather than relying on a default that must not exist.
    """
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
    return create_affiliate(
        db, user_account_id=account.id, name=name, account_kind=kind
    )


def _terms(db, affiliate, rate_bp=1000, **extra):
    return set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=rate_bp,
        **extra,
    )


def _order(db, affiliate, order_id, base, *, codes=("NOUR10",), month=MONTH,
           state=CommissionState.EARNED):
    db.add(
        OrderIndex(
            shopify_order_id=order_id,
            order_number=f"#{order_id}",
            placed_at=datetime(2026, 4, 15, 12, tzinfo=timezone.utc),
            business_month=month,
            discount_codes=list(codes),
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


def _ready(db, name="Nour", base=200_000):
    """An affiliate whose month has nothing standing in its way."""
    affiliate = _affiliate(db, name)
    _terms(db, affiliate)
    _order(db, affiliate, f"{name}-1", base)
    return affiliate


# ── The month row ──────────────────────────────────────────────────────────────


def test_a_month_is_created_by_asking_for_it(db):
    """ADR 0013. Twenty models times twelve months of empty rows is storage
    that answers no question.
    """
    affiliate = _affiliate(db)

    assert get_month(db, affiliate, MONTH) is None
    created = open_month(db, affiliate, MONTH)
    assert created.calculation_state == CalculationState.DRAFT
    assert get_month(db, affiliate, MONTH) is not None


def test_asking_twice_returns_the_same_month(db):
    affiliate = _affiliate(db)

    assert open_month(db, affiliate, MONTH).id == open_month(db, affiliate, MONTH).id


def test_a_second_month_row_is_refused(db):
    """§17. Two rows would be two answers to "what is she owed for August?"."""
    affiliate = _affiliate(db)
    open_month(db, affiliate, MONTH)

    db.add(PayrollMonth(affiliate_id=affiliate.id, month=MONTH))
    with pytest.raises(IntegrityError):
        db.flush()


# ── Approval ───────────────────────────────────────────────────────────────────


def test_approving_freezes_what_was_calculated(db):
    affiliate = _ready(db)

    snapshot = approve_month(db, affiliate, MONTH)

    assert snapshot.version == 1
    assert snapshot.approved_obligation_piastres == 20_000
    assert get_month(db, affiliate, MONTH).calculation_state == (
        CalculationState.APPROVED
    )


def test_the_month_points_at_the_version_in_force(db):
    affiliate = _ready(db)

    snapshot = approve_month(db, affiliate, MONTH)

    assert get_month(db, affiliate, MONTH).active_snapshot_id == snapshot.id


def test_a_payout_is_always_whole_pounds(db):
    """§9.6, ADR 0004, and the database enforces it - a snapshot carrying
    fractional pounds is a figure nobody can pay.
    """
    affiliate = _affiliate(db)
    _terms(db, affiliate, rate_bp=1000)
    _order(db, affiliate, "1", 106_237)

    snapshot = approve_month(db, affiliate, MONTH)

    assert snapshot.approved_obligation_piastres % 100 == 0
    assert snapshot.exact_unrounded_piastres == "10623.7", "the exact figure survives"


def test_approving_twice_is_refused(db):
    """Two obligations for one month is one too many."""
    affiliate = _ready(db)
    approve_month(db, affiliate, MONTH)

    blockers, _ = blockers_for(db, affiliate, MONTH)
    assert ALREADY_APPROVED in blockers
    with pytest.raises(ValueError):
        approve_month(db, affiliate, MONTH)


# ── Blockers refuse ────────────────────────────────────────────────────────────


def test_a_month_with_no_terms_is_refused(db):
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 200_000)

    blockers, _ = blockers_for(db, affiliate, MONTH)
    assert NO_TERMS in blockers
    with pytest.raises(ValueError, match="cannot be approved"):
        approve_month(db, affiliate, MONTH)


def test_a_house_account_is_never_approvable(db):
    """§8, §17. Approving one would create an obligation to HBA itself."""
    house = _affiliate(db, "House", kind=AccountKind.HOUSE)
    _terms(db, house)
    _order(db, house, "1", 500_000)

    blockers, _ = blockers_for(db, house, MONTH)
    assert HOUSE_ACCOUNT in blockers


def test_an_order_two_models_both_claim_blocks_the_month(db):
    """§9.2. A held order has **no** attributed row - that is what being held
    means - so counting attributed orders would report zero and approve a month
    with a known gap in it.
    """
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    _terms(db, nour)
    register_code(db, nour, "NOUR10", "2026-01")
    register_code(db, sara, "SARA10", "2026-01")
    db.add(
        OrderIndex(
            shopify_order_id="held-1",
            order_number="#held-1",
            placed_at=datetime(2026, 4, 15, 12, tzinfo=timezone.utc),
            business_month=MONTH,
            discount_codes=["NOUR10", "SARA10"],
            subtotal_piastres=100_000,
            total_piastres=100_000,
            shipping_piastres=0,
            tax_piastres=0,
            currency="EGP",
        )
    )
    db.flush()

    blockers, _ = blockers_for(db, nour, MONTH)

    assert ORDERS_ON_HOLD in blockers
    with pytest.raises(ValueError):
        approve_month(db, nour, MONTH)


def test_a_missed_target_does_not_block(db):
    """§11.3. The block is on missing information, never on poor performance."""
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.BASE_GUARANTEE,
        commission_rate_bp=1000,
        base_amount_piastres=800_000,
    )
    target = set_requirements(db, affiliate, MONTH, videos=8, stories=5)
    record_actuals(db, target, videos=1, stories=1)
    _order(db, affiliate, "1", 200_000)

    snapshot = approve_month(db, affiliate, MONTH)

    assert snapshot.approved_obligation_piastres == 20_000, "commission, not the base"


def test_a_verified_target_approves_at_the_guarantee(db):
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.BASE_GUARANTEE,
        commission_rate_bp=1000,
        base_amount_piastres=800_000,
    )
    target = set_requirements(db, affiliate, MONTH, videos=8, stories=5)
    record_actuals(db, target, videos=8, stories=5)
    verify(db, target)
    _order(db, affiliate, "1", 200_000)

    snapshot = approve_month(db, affiliate, MONTH)

    assert snapshot.approved_obligation_piastres == 800_000


# ── The snapshot does not recompute ────────────────────────────────────────────


def test_the_snapshot_survives_the_data_changing(db):
    """The largest risk in the phase. A snapshot storing references would
    quietly become a different figure the day a rate was corrected - and a
    snapshot that recomputes is not a snapshot.
    """
    affiliate = _ready(db)
    snapshot = approve_month(db, affiliate, MONTH)
    original = snapshot.approved_obligation_piastres
    original_hash = snapshot.content_hash
    db.commit()

    # Change everything the figure was built from.
    db.execute(
        text("UPDATE attributed_order SET commission_base_piastres = 999_999"),
    )
    db.execute(text("UPDATE compensation_period SET commission_rate_bp = 5000"))
    db.commit()
    db.refresh(snapshot)

    assert snapshot.approved_obligation_piastres == original
    assert snapshot.content_hash == original_hash
    assert snapshot.payload_json["earned_base_piastres"] == 200_000


def test_a_snapshot_cannot_be_edited(db):
    """§17, ADR 0008. A snapshot that can be edited is not a snapshot."""
    affiliate = _ready(db)
    snapshot = approve_month(db, affiliate, MONTH)
    db.commit()

    with pytest.raises(DBAPIError):
        db.execute(
            text(
                "UPDATE payroll_snapshot SET approved_obligation_piastres = 100 "
                "WHERE id = :i"
            ),
            {"i": snapshot.id},
        )
    db.rollback()


def test_a_snapshot_cannot_be_deleted(db):
    affiliate = _ready(db)
    snapshot = approve_month(db, affiliate, MONTH)
    db.commit()

    with pytest.raises(DBAPIError):
        db.execute(
            text("DELETE FROM payroll_snapshot WHERE id = :i"), {"i": snapshot.id}
        )
    db.rollback()


def test_the_hash_changes_only_when_the_figures_do(db):
    nour = _ready(db, "Nour", base=200_000)
    sara = _ready(db, "Sara", base=200_000)
    same = _ready(db, "Same", base=300_000)

    a = approve_month(db, nour, MONTH)
    b = approve_month(db, sara, MONTH)
    c = approve_month(db, same, MONTH)

    assert a.content_hash != c.content_hash, "different figures, different hash"
    assert content_hash({"x": 1, "y": 2}) == content_hash({"y": 2, "x": 1})
    assert b.approved_obligation_piastres == a.approved_obligation_piastres


def test_every_version_is_kept(db):
    affiliate = _ready(db)
    approve_month(db, affiliate, MONTH)

    assert len(snapshots_for(db, get_month(db, affiliate, MONTH))) == 1


def test_a_version_cannot_be_reused(db):
    affiliate = _ready(db)
    snapshot = approve_month(db, affiliate, MONTH)

    db.add(
        PayrollSnapshot(
            payroll_month_id=snapshot.payroll_month_id,
            version=1,
            payload_json={},
            content_hash="x" * 64,
            approved_obligation_piastres=0,
            exact_unrounded_piastres="0",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


# ── Which payroll paid which order ─────────────────────────────────────────────


def test_approving_records_which_payroll_paid_each_order(db):
    """§11.4, and the answer to a question a model will otherwise ask every
    month. Without it her own arithmetic cannot arrive at her own payment.
    """
    affiliate = _ready(db)

    snapshot = approve_month(db, affiliate, MONTH)

    order = db.get(AttributedOrder, "Nour-1")
    assert order.settled_in_snapshot_id == snapshot.id
    assert order.settled_at is not None


def test_an_order_that_did_not_pay_is_not_marked_settled(db):
    """A pending order was not paid by this payroll, and saying it was would
    make the label lie.
    """
    affiliate = _affiliate(db)
    _terms(db, affiliate)
    _order(db, affiliate, "1", 200_000)
    _order(db, affiliate, "2", 50_000, state=CommissionState.PENDING)

    approve_month(db, affiliate, MONTH)

    assert db.get(AttributedOrder, "1").settled_in_snapshot_id is not None
    assert db.get(AttributedOrder, "2").settled_in_snapshot_id is None


# ── The two seams start refusing ───────────────────────────────────────────────


def test_pay_terms_cannot_be_corrected_after_approval(db):
    """A seam since Phase 3, and blocking from here. Correcting a rate after
    payroll changes what a month was worth **after the money moved**, and the
    snapshot would silently disagree with the data it came from.
    """
    affiliate = _affiliate(db)
    terms = _terms(db, affiliate)
    _order(db, affiliate, "1", 200_000)
    approve_month(db, affiliate, MONTH)

    with pytest.raises(ValueError, match="approved month"):
        correct_terms(db, terms, commission_rate_bp=5000)


def test_terms_for_a_later_month_are_still_correctable(db):
    """An approved April does not freeze a rate that starts in September."""
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        end_month="2026-08",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    _order(db, affiliate, "1", 200_000)
    approve_month(db, affiliate, MONTH)

    later = set_terms(
        db,
        affiliate,
        start_month="2026-09",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1200,
    )
    correct_terms(db, later, commission_rate_bp=1300)

    assert later.commission_rate_bp == 1300


def test_ending_terms_after_an_approved_month_is_allowed(db):
    """Ending is not correcting. Closing a period in August does not change
    what April was worth - April was on those terms and still says so.
    """
    from app.services.compensation import close_terms

    affiliate = _affiliate(db)
    terms = _terms(db, affiliate)
    _order(db, affiliate, "1", 200_000)
    approve_month(db, affiliate, MONTH)

    close_terms(db, terms, "2026-08")

    assert terms.end_month == "2026-08"


def test_ending_terms_before_an_approved_month_is_refused(db):
    """That would leave an approved month with no terms at all, and it would be
    incalculable if it were ever reopened.
    """
    from app.services.compensation import close_terms

    affiliate = _affiliate(db)
    terms = _terms(db, affiliate)
    _order(db, affiliate, "1", 200_000)
    approve_month(db, affiliate, MONTH)

    with pytest.raises(ValueError, match="no terms at all"):
        close_terms(db, terms, "2026-02")


def test_a_target_cannot_be_changed_after_approval(db):
    """A seam since Phase 5. A target decides whether a guarantee applied, so
    editing one after payroll changes what the month was worth.
    """
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.BASE_GUARANTEE,
        commission_rate_bp=1000,
        base_amount_piastres=800_000,
    )
    target = set_requirements(db, affiliate, MONTH, videos=8, stories=5)
    record_actuals(db, target, videos=8, stories=5)
    verify(db, target)
    _order(db, affiliate, "1", 200_000)
    approve_month(db, affiliate, MONTH)

    with pytest.raises(ValueError, match="approved"):
        record_actuals(db, target, videos=9, stories=6)


def test_a_target_for_an_unapproved_month_is_still_editable(db):
    affiliate = _affiliate(db)
    _terms(db, affiliate)
    _order(db, affiliate, "1", 200_000)
    approve_month(db, affiliate, MONTH)

    other = set_requirements(db, affiliate, "2026-05", videos=8, stories=5)
    record_actuals(db, other, videos=8, stories=5)

    assert other.actual_videos == 8


# ── Which month a screen opens on ──────────────────────────────────────────────


def test_working_month_is_this_month_once_the_platform_is_live(monkeypatch):
    from app.config import settings
    from app.core.businesstime import business_month, utcnow
    from app.services.payroll import working_month

    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)

    assert working_month() == business_month(utcnow())


def test_working_month_is_the_go_live_month_before_the_platform_starts(monkeypatch):
    """The week before go-live, "this month" holds nothing at all.

    Opening on it shows every figure at zero, which reads as a broken tool
    rather than as a month the platform was never responsible for.
    """
    from app.config import settings
    from app.services.payroll import working_month

    monkeypatch.setattr(settings, "go_live_month", "2099-06", raising=False)

    assert working_month() == "2099-06"


def test_working_month_falls_back_to_this_month_with_no_go_live(monkeypatch):
    from app.config import settings
    from app.core.businesstime import business_month, utcnow
    from app.services.payroll import working_month

    monkeypatch.setattr(settings, "go_live_month", "", raising=False)

    assert working_month() == business_month(utcnow())


def test_an_approved_row_reports_what_was_agreed_and_what_it_would_be_now(db):
    """Two figures, and they are allowed to differ.

    An order settling after approval changes the calculation and never the
    obligation (§11.4). A screen showing the recalculated figure under the word
    "approved" would present a working number as a debt.
    """
    from app.api.payroll import _row

    nour = _affiliate(db)
    _terms(db, nour)
    _order(db, nour, "a-1", 1_000_000)
    db.flush()

    approve_month(db, nour, MONTH, actor_id=None, actor_email=None)
    db.flush()

    agreed = _row(db, nour, MONTH)["approved_obligation_piastres"]

    # An order settles after the fact, exactly as Egyptian COD delivery does.
    _order(db, nour, "late-1", 500_000)
    db.flush()

    row = _row(db, nour, MONTH)

    assert row["approved_obligation_piastres"] == agreed, "the agreed figure moved"
    assert row["obligation_piastres"] > agreed, "the calculation should have moved"
