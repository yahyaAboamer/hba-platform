"""Two people, one correction. R2.

The sequential retry test in `test_corrections.py` proves a *repeat* is
refused. It cannot prove anything about a **race**, because there is only one
session in it: the first call finishes before the second begins, so the
outstanding figure has already changed by the time the second one reads it.

The race is the case where it has not. Two sessions read the same correction,
both see the same outstanding amount, both pass every check, and both write —
and the money is recovered twice with the ledger recording only that two
people chose it.

So these tests use **real, separate PostgreSQL sessions**, driven from threads
that commit, against committed rows. `db` is not used: it wraps everything in
one transaction that is rolled back, which is exactly the isolation these have
to do without.

Each test leaves the database as it found it, by emptying it through the
committing fixture the API tests use.
"""

import threading
import uuid
from datetime import datetime, timezone

import pytest

from app.core.passwords import hash_password
from app.db import SessionLocal
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
from app.services.payments import balance_for, record_payment
from app.services.payroll import approve_month

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
    affiliate.collaboration_start_month = "2026-01"
    db.flush()
    return affiliate


def _fail(db, order_id):
    db.get(AttributedOrder, order_id).commission_state = CommissionState.VOID
    db.flush()


def _in_parallel(work, count=2):
    """Run `work(index)` in `count` threads, each holding its own session.

    Started together on a barrier so they are genuinely in flight at the same
    time. Returns each thread's result or the exception it raised, in order.
    """
    ready = threading.Barrier(count)
    results: list = [None] * count

    def run(index: int) -> None:
        ready.wait(timeout=30)
        session = SessionLocal()
        try:
            results[index] = work(index, session)
            session.commit()
        except Exception as caught:  # recorded, not raised, so both finish
            session.rollback()
            results[index] = caught
        finally:
            session.close()

    threads = [threading.Thread(target=run, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads), "a session never finished"
    return results


@pytest.fixture()
def committed(fresh_database):
    """A model with an overpaid August and a September to carry it into.

    Committed, because the whole point is that other sessions can see it.
    """
    session = SessionLocal()
    try:
        affiliate = _model(session, "Nour")
        _order(session, affiliate, "aug-1", 2_000_000)
        august = approve_month(session, affiliate, AUGUST)
        record_payment(
            session,
            affiliate,
            amount_piastres=200_000,
            allocations={august.id: 200_000},
        )
        _order(session, affiliate, "sep-1", 9_000_000, month=SEPTEMBER)
        approve_month(session, affiliate, SEPTEMBER)
        _fail(session, "aug-1")
        session.commit()
        return affiliate.id
    finally:
        session.close()


def _adjustments(kind=None):
    session = SessionLocal()
    try:
        rows = list(session.scalars(__import__("sqlalchemy").select(PayrollAdjustment)))
        if kind:
            rows = [row for row in rows if row.type == kind]
        return [(row.type, row.amount_piastres) for row in rows]
    finally:
        session.close()


def test_two_sessions_resolving_one_correction_recover_it_once(committed):
    """R2. The race the sequential retry test cannot reach.

    Both sessions read the same E£2,000 outstanding, and both are entitled to
    act on it as far as any check can tell. Exactly one recovery may exist
    afterwards, and September must be reduced once.
    """
    from app.models.affiliates import AffiliateProfile

    def work(index, session):
        affiliate = session.get(AffiliateProfile, committed)
        return resolve(
            session,
            affiliate,
            AUGUST,
            choice=AdjustmentType.CREDIT,
            reason=f"session {index}",
            destination_month=SEPTEMBER,
            # Different keys: two *different* people deciding, not one retry.
            operation_key=f"race-{index}-{uuid.uuid4()}",
        ).id

    outcomes = _in_parallel(work)
    assert any(isinstance(row, int) for row in outcomes), outcomes

    carried = _adjustments(AdjustmentType.CREDIT)
    assert carried == [(AdjustmentType.CREDIT, 200_000)], (
        "the same correction was recovered twice"
    )

    session = SessionLocal()
    try:
        from app.models.affiliates import AffiliateProfile as Profile

        affiliate = session.get(Profile, committed)
        assert correction_for(session, affiliate, AUGUST).outstanding_piastres == 0
        # September needed E£900 and E£200 of it is already in her hands.
        assert balance_for(session, affiliate, SEPTEMBER)["credited_piastres"] == 200_000
        assert balance_for(session, affiliate, SEPTEMBER)["balance_piastres"] == 700_000
    finally:
        session.close()


def test_a_retry_with_the_same_key_returns_the_first_recovery(committed):
    """R2. A lost response is not a conflict.

    Both sessions send the *same* operation key, which is what a browser does
    when it retries a request whose answer it never saw. One decision, one
    row, and both callers are told about the same one.
    """
    from app.models.affiliates import AffiliateProfile

    key = f"retry-{uuid.uuid4()}"

    def work(index, session):
        affiliate = session.get(AffiliateProfile, committed)
        return resolve(
            session,
            affiliate,
            AUGUST,
            choice=AdjustmentType.CREDIT,
            reason="carried",
            destination_month=SEPTEMBER,
            operation_key=key,
        ).id

    outcomes = _in_parallel(work)
    landed = [row for row in outcomes if isinstance(row, int)]
    assert landed, outcomes
    assert len(set(landed)) == 1, "one decision produced two rows"
    assert _adjustments(AdjustmentType.CREDIT) == [(AdjustmentType.CREDIT, 200_000)]


def test_two_corrections_cannot_both_spend_one_destination(fresh_database):
    """R2. The other race: one month, two claims on it.

    June and July are both overpaid by E£100 and both carried into September,
    which is worth E£150. The two together are more than it has, and the
    ledger must not end up recording E£200 applied to a E£150 month.
    """
    from app.models.affiliates import AffiliateProfile

    session = SessionLocal()
    try:
        affiliate = _model(session, "Sara")
        for month, order in (("2026-06", "jun"), ("2026-07", "jul")):
            _order(session, affiliate, order, 1_000_000, month=month)
            snapshot = approve_month(session, affiliate, month)
            record_payment(
                session,
                affiliate,
                amount_piastres=100_000,
                allocations={snapshot.id: 100_000},
            )
            _fail(session, order)
        _order(session, affiliate, "sep", 1_500_000, month=SEPTEMBER)
        approve_month(session, affiliate, SEPTEMBER)
        session.commit()
        affiliate_id = affiliate.id
    finally:
        session.close()

    sources = ["2026-06", "2026-07"]

    def work(index, session):
        affiliate = session.get(AffiliateProfile, affiliate_id)
        return resolve(
            session,
            affiliate,
            sources[index],
            choice=AdjustmentType.CREDIT,
            reason=f"carried from {sources[index]}",
            destination_month=SEPTEMBER,
            operation_key=f"share-{index}-{uuid.uuid4()}",
        ).amount_piastres

    _in_parallel(work)

    session = SessionLocal()
    try:
        affiliate = session.get(AffiliateProfile, affiliate_id)
        applied = sum(
            amount for kind, amount in _adjustments(AdjustmentType.CREDIT)
        )
        # Whatever order they arrived in, the month cannot give more than it
        # has: E£150, not the E£200 the two corrections asked for together.
        assert applied <= 150_000, f"{applied} piastres applied to a 150000 month"
        assert balance_for(session, affiliate, SEPTEMBER)["balance_piastres"] >= 0
        # And nothing was lost: what the month could not take is still open
        # against the month it came from.
        outstanding = sum(
            correction_for(session, affiliate, month).outstanding_piastres
            for month in sources
        )
        assert applied + outstanding == 200_000
    finally:
        session.close()
