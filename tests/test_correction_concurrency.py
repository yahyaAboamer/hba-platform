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
OCTOBER = "2026-10"


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


def _in_parallel(work, count=2, names=None):
    """Run `work(index)` in `count` threads, each holding its own session.

    Started together on a barrier so they are genuinely in flight at the same
    time. Returns each thread's result or the exception it raised, in order.

    `names` labels the threads, which is how the deterministic tests below tell
    one participant from the other from inside the service code.
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

    threads = [
        threading.Thread(
            target=run,
            args=(index,),
            name=(names[index] if names else f"worker-{index}"),
        )
        for index in range(count)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        # Generous, because the gate is doing its job: three writers against
        # one model queue behind each other and each runs a whole month's
        # calculation. A tighter bound here measures the machine, not the code.
        thread.join(timeout=180)
    assert not any(thread.is_alive() for thread in threads), "a session never finished"
    return results


def _hold_one_thread_at_the_gate(monkeypatch, *, thread_name, until):
    """Make one named thread arrive at the money gate *after* `until` is set.

    F3. The race approval used to lose is not about who starts first — it is
    about a session that read the world, waited, and then wrote what it read.
    This puts one thread in exactly that position on purpose: it reaches the
    gate, the other session commits in full, and only then does it continue.

    Everything approval decides on is read **after** the gate (that is the
    fix), so the thread held here must come out of the wait seeing the other
    session's work. A version that read first and locked second would freeze
    evidence that was already false, and the assertions below say so.

    An event, not a sleep: nothing here is timing-dependent, and the other
    session has genuinely committed before this one moves.
    """
    from app.services import money_gate

    real = money_gate.hold_money_gate

    def wait_then_hold(db, affiliate):
        if threading.current_thread().name == thread_name:
            assert until.wait(timeout=30), "the other session never finished"
        return real(db, affiliate)

    monkeypatch.setattr(money_gate, "hold_money_gate", wait_then_hold)


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

    # F4. **Both**, not "at least one and no contradictions."
    #
    # The first version of this collected the successes, checked that one
    # existed and checked they agreed with each other. One success and one
    # exception satisfies every word of that, which is the outcome the test was
    # written to rule out: a retry answered with a 409 it cannot interpret,
    # about a decision its own first attempt had already made.
    assert all(isinstance(row, int) for row in outcomes), outcomes
    assert len(set(outcomes)) == 1, f"one decision produced two rows: {outcomes}"
    assert _adjustments(AdjustmentType.CREDIT) == [(AdjustmentType.CREDIT, 200_000)]


def test_a_key_reused_for_a_different_decision_is_refused(committed):
    """F4. The other half of an idempotency key: it has to identify something.

    Handing back whatever row carries the key, whatever that row says, turns a
    client's key-reuse bug into a silent wrong answer — a carry into September
    reported for a request that asked for an absorb, or for a different month
    entirely.
    """
    from app.models.affiliates import AffiliateProfile
    from app.services.payments import OperationKeyReused

    key = f"reused-{uuid.uuid4()}"
    session = SessionLocal()
    try:
        affiliate = session.get(AffiliateProfile, committed)
        first = resolve(
            session,
            affiliate,
            AUGUST,
            choice=AdjustmentType.CREDIT,
            reason="carried",
            destination_month=SEPTEMBER,
            operation_key=key,
        )
        session.commit()
        first_id = first.id
    finally:
        session.close()

    session = SessionLocal()
    try:
        affiliate = session.get(AffiliateProfile, committed)
        # Same key, different decision. Not the same request arriving twice.
        with pytest.raises(OperationKeyReused):
            resolve(
                session,
                affiliate,
                AUGUST,
                choice=AdjustmentType.WRITEOFF,
                reason="absorbed instead",
                operation_key=key,
            )
        session.rollback()
        # And the same key with the same decision is still a retry.
        affiliate = session.get(AffiliateProfile, committed)
        again = resolve(
            session,
            affiliate,
            AUGUST,
            choice=AdjustmentType.CREDIT,
            reason="carried",
            destination_month=SEPTEMBER,
            operation_key=key,
        )
        assert again.id == first_id
    finally:
        session.rollback()
        session.close()

    assert _adjustments(AdjustmentType.CREDIT) == [(AdjustmentType.CREDIT, 200_000)]


def test_a_colliding_key_leaves_the_session_able_to_answer(committed):
    """F4. The savepoint has to contain the collision, insert included.

    Two sessions both find the key free and both insert. The loser's statement
    fails on the unique constraint, and what happens next is the whole point:
    the recovery query has to be able to run. If the insert escaped the
    savepoint the whole transaction would be aborted, and a retry that should
    have been answered with the winner's row would raise instead.

    Driven through `adjust` directly with the replay check stubbed out, because
    the only way to reach the collision is for both sessions to get past a
    check that is designed to stop them.
    """
    from app.models.affiliates import AffiliateProfile
    from app.services import payments

    key = f"collide-{uuid.uuid4()}"
    passed_the_check = threading.Barrier(2, timeout=30)
    real = payments._replay_of

    def blind_first_time(db, operation_key, **rest):
        found = real(db, operation_key, **rest)
        if found is None:
            # Both sessions leave here together, so both insert.
            passed_the_check.wait()
        return found

    def work(index, worker):
        profile = worker.get(AffiliateProfile, committed)
        row = payments.adjust(
            worker,
            profile,
            kind=AdjustmentType.CREDIT,
            source_month=AUGUST,
            destination_month=SEPTEMBER,
            amount_piastres=200_000,
            reason="carried",
            open_difference_piastres=200_000,
            operation_key=key,
        )
        # The session survived the collision and can still be used.
        assert worker.scalar(
            __import__("sqlalchemy")
            .select(PayrollAdjustment.id)
            .where(PayrollAdjustment.id == row.id)
        )
        return row.id

    payments._replay_of = blind_first_time
    try:
        outcomes = _in_parallel(work)
    finally:
        payments._replay_of = real

    assert all(isinstance(row, int) for row in outcomes), outcomes
    assert len(set(outcomes)) == 1, f"one key produced two rows: {outcomes}"
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


# -- F3. Approval and allocation, which used to run past each other -----------


@pytest.fixture()
def carried_into_october(fresh_database):
    """August overpaid by E£2,000, and an October worth E£2,000 to take it.

    October is deliberately left in draft: a carry is accepted against a month
    before it is agreed (F07, F12), which is the window approval and the
    corrections service both write into.
    """
    session = SessionLocal()
    try:
        affiliate = _model(session, "Hana")
        _order(session, affiliate, "aug-1", 2_000_000)
        august = approve_month(session, affiliate, AUGUST)
        record_payment(
            session,
            affiliate,
            amount_piastres=200_000,
            allocations={august.id: 200_000},
        )
        _order(session, affiliate, "oct-1", 2_000_000, month=OCTOBER)
        _fail(session, "aug-1")
        session.commit()
        return affiliate.id
    finally:
        session.close()


def _october(affiliate_id):
    """What October ended up at: its snapshot's evidence and its ledger."""
    from app.models.affiliates import AffiliateProfile
    from app.services.payments import credited_into
    from app.services.payroll import get_month

    session = SessionLocal()
    try:
        affiliate = session.get(AffiliateProfile, affiliate_id)
        month = get_month(session, affiliate, OCTOBER)
        snapshot = month.active_snapshot if month is not None else None
        return {
            "approved": snapshot.approved_obligation_piastres if snapshot else None,
            "frozen_applied": (
                snapshot.payload_json["deductions_applied_piastres"]
                if snapshot
                else None
            ),
            "frozen_released": (
                snapshot.payload_json["deductions_released_piastres"]
                if snapshot
                else None
            ),
            "credited": credited_into(session, month) if month else 0,
            "balance": balance_for(session, affiliate, OCTOBER)["balance_piastres"],
            "outstanding": correction_for(
                session, affiliate, AUGUST
            ).outstanding_piastres,
        }
    finally:
        session.close()


def test_a_carry_landing_during_an_approval_is_part_of_what_is_agreed(
    carried_into_october, monkeypatch
):
    """F3. The deterministic one: approval waits, the carry lands, approval runs.

    The approving session reaches the gate and is held there until the other
    has committed a E£2,000 carry onto the very month it is about to agree.
    Everything approval decides on is read after that gate, so the snapshot it
    writes has to account for the carry.

    What must not happen is the shape the old order produced: a snapshot whose
    frozen deduction evidence says nothing landed on this month, beside a
    ledger in which E£2,000 did. Two records of one month, disagreeing, with
    the statement rendered from the one that is wrong.
    """
    from app.models.affiliates import AffiliateProfile

    carried = threading.Event()
    _hold_one_thread_at_the_gate(monkeypatch, thread_name="approver", until=carried)

    def work(index, session):
        affiliate = session.get(AffiliateProfile, carried_into_october)
        if threading.current_thread().name == "approver":
            return approve_month(session, affiliate, OCTOBER).id
        try:
            return resolve(
                session,
                affiliate,
                AUGUST,
                choice=AdjustmentType.CREDIT,
                reason="carried into October",
                destination_month=OCTOBER,
                operation_key=f"carry-{uuid.uuid4()}",
            ).id
        finally:
            session.commit()
            carried.set()

    outcomes = _in_parallel(work, names=["approver", "carrier"])
    assert all(isinstance(row, int) for row in outcomes), outcomes

    after = _october(carried_into_october)
    assert after["approved"] == 200_000
    assert after["credited"] == 200_000
    assert after["frozen_applied"] == 200_000, (
        "the snapshot froze a deduction figure the ledger disagrees with"
    )
    assert after["frozen_released"] == 0
    assert after["balance"] == 0
    assert after["outstanding"] == 0


def test_an_approval_and_a_carry_racing_leave_one_consistent_month(
    carried_into_october,
):
    """F3. The same two writers, with nobody held anywhere.

    Whichever order they land in, one set of facts has to come out: the month
    absorbs no more than it is worth, its frozen evidence agrees with its
    ledger, and every piastre of the correction is either applied or still
    open. Nothing may be applied twice and nothing may go missing.
    """
    from app.models.affiliates import AffiliateProfile

    def work(index, session):
        affiliate = session.get(AffiliateProfile, carried_into_october)
        if index == 0:
            return approve_month(session, affiliate, OCTOBER).id
        return resolve(
            session,
            affiliate,
            AUGUST,
            choice=AdjustmentType.CREDIT,
            reason="carried into October",
            destination_month=OCTOBER,
            operation_key=f"carry-{uuid.uuid4()}",
        ).id

    _in_parallel(work)

    after = _october(carried_into_october)
    if after["approved"] is None:
        pytest.fail("October was never agreed")
    assert after["credited"] <= after["approved"], "more was deducted than was agreed"
    # `frozen_applied` is already net of anything released, so subtracting the
    # released figure from it again would only make this easier to satisfy -
    # which is the F4 mistake in a different costume.
    assert after["frozen_applied"] <= after["approved"]
    assert after["frozen_applied"] >= 0
    assert after["balance"] >= 0
    # Applied plus still-open is the whole difference, once.
    assert after["credited"] + after["outstanding"] == 200_000


def test_two_carries_and_an_approval_cannot_overdraw_the_month(fresh_database):
    """F3. Three writers, one destination worth less than the two claims.

    June and July are each owed E£1,000 back; September is worth E£1,500 and is
    being agreed at the same moment. The two carries together are more than it
    has. However the three interleave, September may absorb at most what it is
    worth, and what it cannot take stays open against the month it came from.
    """
    from app.models.affiliates import AffiliateProfile
    from app.services.payments import credited_into
    from app.services.payroll import get_month

    session = SessionLocal()
    try:
        affiliate = _model(session, "Dina")
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
        session.commit()
        affiliate_id = affiliate.id
    finally:
        session.close()

    sources = ["2026-06", "2026-07"]

    def work(index, session):
        affiliate = session.get(AffiliateProfile, affiliate_id)
        if index == 2:
            return approve_month(session, affiliate, SEPTEMBER).id
        return resolve(
            session,
            affiliate,
            sources[index],
            choice=AdjustmentType.CREDIT,
            reason=f"carried from {sources[index]}",
            destination_month=SEPTEMBER,
            operation_key=f"three-{index}-{uuid.uuid4()}",
        ).id

    _in_parallel(work, count=3)

    session = SessionLocal()
    try:
        affiliate = session.get(AffiliateProfile, affiliate_id)
        month = get_month(session, affiliate, SEPTEMBER)
        applied = credited_into(session, month)
        assert applied <= 150_000, f"{applied} piastres applied to a 150000 month"
        assert balance_for(session, affiliate, SEPTEMBER)["balance_piastres"] >= 0
        outstanding = sum(
            correction_for(session, affiliate, source).outstanding_piastres
            for source in sources
        )
        assert applied + outstanding == 200_000, "a remainder was lost"
        if month.active_snapshot is not None:
            body = month.active_snapshot.payload_json
            agreed = month.active_snapshot.approved_obligation_piastres
            # **Not equality with the ledger**, and the reason is a real rule
            # rather than a concession to the race. A carry may be accepted
            # against a month that is already agreed — `capacity_of` offers an
            # approved month its remaining balance — so a credit recorded after
            # this snapshot was written is legitimate and is not in it. What
            # the snapshot froze is what was landing *when it was agreed*, and
            # that can never have been more than the month was worth.
            assert body["deductions_applied_piastres"] <= agreed, (
                "the snapshot agreed to more deduction than the month was worth"
            )
            assert body["deductions_applied_piastres"] >= 0
    finally:
        session.close()


def test_a_release_and_a_decision_on_the_same_source_settle_it_once(fresh_database):
    """F3. Approval handing money back while somebody decides about it.

    August carries its whole E£2,000 into an October that then loses the sale
    it was going to pay with. Agreeing October at nothing releases the E£2,000
    back to August — at the same moment as somebody absorbing August's
    correction on the screen in front of them.

    The release reopens the difference and the absorb closes it. Both are real
    decisions and both may stand; what must not happen is August ending up
    settled for more or less than the one E£2,000 it was ever short.
    """
    from app.models.affiliates import AffiliateProfile
    from app.services.corrections import _resolved_so_far
    from app.services.payments import credited_into
    from app.services.payroll import get_month

    session = SessionLocal()
    try:
        affiliate = _model(session, "Rana")
        _order(session, affiliate, "aug-1", 2_000_000)
        august = approve_month(session, affiliate, AUGUST)
        record_payment(
            session,
            affiliate,
            amount_piastres=200_000,
            allocations={august.id: 200_000},
        )
        _order(session, affiliate, "oct-1", 2_000_000, month=OCTOBER)
        _fail(session, "aug-1")
        resolve(
            session,
            affiliate,
            AUGUST,
            choice=AdjustmentType.CREDIT,
            reason="carried into October",
            destination_month=OCTOBER,
        )
        # And now October loses the sale it was going to pay the deduction with.
        _fail(session, "oct-1")
        session.commit()
        affiliate_id = affiliate.id
    finally:
        session.close()

    def work(index, session):
        affiliate = session.get(AffiliateProfile, affiliate_id)
        if index == 0:
            return approve_month(session, affiliate, OCTOBER).id
        return resolve(
            session,
            affiliate,
            AUGUST,
            choice=AdjustmentType.WRITEOFF,
            reason="HBA absorbs it",
            operation_key=f"absorb-{uuid.uuid4()}",
        ).id

    _in_parallel(work)

    session = SessionLocal()
    try:
        affiliate = session.get(AffiliateProfile, affiliate_id)
        month = get_month(session, affiliate, OCTOBER)
        # October took nothing, because it is worth nothing.
        assert credited_into(session, month) == 0
        assert balance_for(session, affiliate, OCTOBER)["balance_piastres"] == 0

        settled, _ = _resolved_so_far(session, affiliate, AUGUST)
        outstanding = correction_for(session, affiliate, AUGUST).outstanding_piastres
        assert settled + outstanding == 200_000, (
            f"August was short E£2,000 and is recorded as {settled} settled "
            f"with {outstanding} open"
        )
        assert outstanding >= 0
        # And August is still owed nothing extra: it was paid in full.
        assert balance_for(session, affiliate, AUGUST)["balance_piastres"] == 0
    finally:
        session.close()
