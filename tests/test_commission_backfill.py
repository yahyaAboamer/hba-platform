"""Attaching the orders a code already had when it was registered.

Phase 4 Task 6, and the two tests Phase 3 deferred by name.

§9.2 permits this explicitly: *a previously unattributed order may be attached
when its code is registered for the first time. This assigns an orphan; it does
not move an order.*

It matters because models arrive with codes **already live and already
selling** (ADR 0022). Without it, everything a code earned before somebody typed
it into the platform belongs to nobody, for ever, and nothing says so.
"""

from datetime import datetime, timezone

import pytest

from app.core.passwords import hash_password
from app.models.affiliates import AccountKind
from app.models.attributed_orders import AttributedOrder
from app.models.identity import UserAccount
from app.models.integration import BackgroundJob
from app.models.orders import OrderIndex
from app.services.affiliates import create_affiliate
from app.services.codes import register_code
from app.services.commission.backfill import (
    MAX_ORDERS_PER_RUN,
    backfill_code,
    orders_awaiting_attachment,
)
from app.services.jobs import JobKind
from app.services.shopify.fulfilment import DELIVERED

PAID = 115_700
SHIPPING = 9_500
EXPECTED_BASE = 106_200


def _affiliate(
    db, name="Nour", code=None, start="2026-01", end=None, kind=AccountKind.MODEL
):
    """An affiliate, optionally already owning a code.

    Ownership is what `resolve()` reads. Without it the backfill finds orders
    and attaches none of them, which is the correct behaviour and a useless
    test.
    """
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
    if code:
        register_code(db, affiliate, code, start, end)
        db.flush()
    return affiliate


def _order(db, order_id, code="NOUR10", month="2026-03"):
    row = OrderIndex(
        shopify_order_id=order_id,
        order_number=f"#{order_id}",
        placed_at=datetime(2026, 3, 15, 12, tzinfo=timezone.utc),
        business_month=month,
        discount_codes=[code] if code else [],
        subtotal_piastres=EXPECTED_BASE,
        total_piastres=PAID,
        shipping_piastres=SHIPPING,
        tax_piastres=0,
        currency="EGP",
        delivery_state=DELIVERED,
        delivered_at=datetime(2026, 3, 20, 10, tzinfo=timezone.utc),
    )
    db.add(row)
    db.flush()
    return row


# ── The two Phase 3 deferred by name ───────────────────────────────────────────


def test_backfill_attaches_previously_unattributed_orders(db):
    """Deferred from Phase 3 Task 8, because attaching means writing
    `attributed_order` and that table did not exist yet.
    """
    affiliate = _affiliate(db, code="NOUR10")
    _order(db, "3001")
    _order(db, "3002")

    attached, more = backfill_code(db, "NOUR10", "2026-01")

    assert attached == 2
    assert more is False
    assert db.get(AttributedOrder, "3001").affiliate_id == affiliate.id
    assert db.get(AttributedOrder, "3002").affiliate_id == affiliate.id


def test_backfill_values_the_orders_it_attaches(db):
    """Attaching is not bookkeeping. Each order goes through the same base and
    state rules as a live one, so a backfilled month is worth the same as one
    that arrived by webhook.
    """
    _affiliate(db, code="NOUR10")
    _order(db, "3003")

    backfill_code(db, "NOUR10", "2026-01")

    row = db.get(AttributedOrder, "3003")
    assert row.commission_base_piastres == EXPECTED_BASE
    assert row.counts_toward_payout is True


# ── Attaching, never moving ────────────────────────────────────────────────────


def test_an_order_that_already_has_an_owner_is_left_alone(db):
    """§9.2: this assigns an orphan, it does not move an order. A mistyped
    registration must not quietly take a sale from the model who was paid for
    it.
    """
    nour = _affiliate(db, "Nour", code="NOUR10")
    order = _order(db, "3004")
    backfill_code(db, "NOUR10", "2026-01")

    sara = _affiliate(db, "Sara", code="SARA10")
    order.discount_codes = ["NOUR10", "SARA10"]
    db.flush()

    backfill_code(db, "SARA10", "2026-01")

    assert db.get(AttributedOrder, "3004").affiliate_id == nour.id


def test_the_job_does_not_fail_on_a_row_it_cannot_touch(db):
    """It must carry on rather than dying on a row it was never entitled to
    write - one such order would otherwise strand every order after it.
    """
    nour = _affiliate(db, "Nour", code="NOUR10")
    taken = _order(db, "3005")
    backfill_code(db, "NOUR10", "2026-01")

    sara = _affiliate(db, "Sara", code="SARA10")
    taken.discount_codes = ["NOUR10", "SARA10"]
    db.flush()
    _order(db, "3006", code="SARA10")

    attached, _ = backfill_code(db, "SARA10", "2026-01")

    assert attached == 1
    assert db.get(AttributedOrder, "3006").affiliate_id == sara.id


# ── Only the months she owns ───────────────────────────────────────────────────


def test_only_months_she_owns_are_attached(db):
    """A code that changed hands has periods either side. Each registration
    backfills its own, or a model is paid for another model's sales.
    """
    _affiliate(db, code="NOUR10", start="2026-04", end="2026-06")
    _order(db, "3007", month="2026-02")
    _order(db, "3008", month="2026-05")
    _order(db, "3009", month="2026-09")

    backfill_code(db, "NOUR10", "2026-04", "2026-06")

    assert db.get(AttributedOrder, "3007") is None, "reached before her period"
    assert db.get(AttributedOrder, "3008") is not None
    assert db.get(AttributedOrder, "3009") is None, "reached past her period"


def test_an_open_ended_period_has_no_upper_bound(db):
    _affiliate(db, code="NOUR10", start="2026-04")
    _order(db, "3010", month="2026-05")
    _order(db, "3011", month="2099-12")

    backfill_code(db, "NOUR10", "2026-04", None)

    assert db.get(AttributedOrder, "3010") is not None
    assert db.get(AttributedOrder, "3011") is not None


def test_an_order_using_a_different_code_is_not_touched(db):
    _affiliate(db, code="NOUR10")
    _order(db, "3012", code="SOMEONE_ELSE10")

    attached, _ = backfill_code(db, "NOUR10", "2026-01")

    assert attached == 0


# ── Running twice, and running long ────────────────────────────────────────────


def test_running_it_again_changes_nothing(db):
    """Registering, re-checking and correcting a code in quick succession all
    queue one, and a retried job runs it again.
    """
    _affiliate(db, code="NOUR10")
    _order(db, "3013")

    first, _ = backfill_code(db, "NOUR10", "2026-01")
    second, _ = backfill_code(db, "NOUR10", "2026-01")

    assert (first, second) == (1, 0)
    assert db.query(AttributedOrder).filter_by(shopify_order_id="3013").count() == 1


def test_a_long_backfill_reports_that_more_remains(db):
    """A code with two thousand orders would otherwise hold a worker lease for
    minutes and lose the lot when it expired (ADR 0021).
    """
    _affiliate(db, code="NOUR10")
    for index in range(4):
        _order(db, f"31{index:02d}")

    attached, more = backfill_code(db, "NOUR10", "2026-01", limit=2)

    assert attached == 2
    assert more is True


def test_the_bound_is_not_so_small_that_ordinary_codes_need_two_runs(db):
    """HBA's whole shop is about 30k orders a year. A code needing more than
    one run should be unusual, not routine.
    """
    assert MAX_ORDERS_PER_RUN >= 100


def test_orders_already_attached_are_not_re_queried(db):
    """The query excludes them, rather than attributing and discarding. On a
    second run over a finished code that is the difference between no work and
    all of it.
    """
    _affiliate(db, code="NOUR10")
    _order(db, "3014")
    backfill_code(db, "NOUR10", "2026-01")

    assert orders_awaiting_attachment(db, "NOUR10", "2026-01", None, limit=10) == []


# ── Registration queues it, and never waits for it ─────────────────────────────


def test_registering_a_code_queues_its_history(db):
    """§10.3: affiliate creation never blocks on the backfill."""
    affiliate = _affiliate(db)
    _order(db, "3015")

    register_code(db, affiliate, "NOUR10", "2026-01")
    db.flush()

    queued = db.query(BackgroundJob).filter_by(kind=JobKind.BACKFILL_CODE).all()
    assert len(queued) == 1
    assert queued[0].payload["code"] == "NOUR10"
    assert db.get(AttributedOrder, "3015") is None, "it must not run inline"


def test_asking_twice_queues_one_backfill(db):
    """Registering, re-checking and correcting a code in quick succession
    should do the work once. Deduplicated on code and period, so a genuinely
    different period still gets its own.
    """
    from app.services.commission.backfill import queue_backfill

    affiliate = _affiliate(db, code="NOUR10")
    db.query(BackgroundJob).delete()
    db.flush()

    queue_backfill(db, affiliate, "NOUR10", "2026-01", None)
    queue_backfill(db, affiliate, "NOUR10", "2026-01", None)
    queue_backfill(db, affiliate, "NOUR10", "2026-07", None)
    db.flush()

    queued = db.query(BackgroundJob).filter_by(kind=JobKind.BACKFILL_CODE).all()
    assert len(queued) == 2
    assert sorted(job.payload["start_month"] for job in queued) == ["2026-01", "2026-07"]


def test_a_handover_backfills_the_new_code(db):
    """`retire_and_replace` creates a period without going through
    `register_code`. A path that creates ownership and forgets to backfill
    leaves those orders belonging to nobody.
    """
    from app.services.codes import retire_and_replace

    affiliate = _affiliate(db)
    old = register_code(db, affiliate, "OLD10", "2026-01")
    db.query(BackgroundJob).delete()
    db.flush()

    retire_and_replace(
        db, affiliate, old_period=old, new_code="NEW10", new_start_month="2026-07"
    )
    db.flush()

    queued = db.query(BackgroundJob).filter_by(kind=JobKind.BACKFILL_CODE).all()
    assert [job.payload["code"] for job in queued] == ["NEW10"]


def test_correcting_a_mistyped_code_backfills_the_real_one(db):
    """The corrected code is a different code with its own history. A typo
    fixed on Monday must not leave the real code's orders orphaned.
    """
    from app.services.codes import replace_code

    affiliate = _affiliate(db)
    period = register_code(db, affiliate, "NOUR1O", "2026-01")
    db.query(BackgroundJob).delete()
    db.flush()

    replace_code(db, period, "NOUR10", start_month="2026-01")
    db.flush()

    queued = db.query(BackgroundJob).filter_by(kind=JobKind.BACKFILL_CODE).all()
    assert [job.payload["code"] for job in queued] == ["NOUR10"]


# ── The job handler ────────────────────────────────────────────────────────────


def test_the_handler_does_the_work(db):
    from app.services.commission.backfill import _handle_backfill

    _affiliate(db, code="NOUR10")
    _order(db, "3020")

    _handle_backfill(db, {"code": "NOUR10", "start_month": "2026-01", "end_month": None})

    assert db.get(AttributedOrder, "3020") is not None


def test_a_handler_missing_its_payload_fails_permanently(db):
    """Retrying will not supply a code. Four more identical failures over eight
    minutes buy nothing and bury the line that explains the problem.
    """
    from app.services.commission.backfill import _handle_backfill
    from app.services.jobs import PermanentFailure

    with pytest.raises(PermanentFailure):
        _handle_backfill(db, {"start_month": "2026-01"})

    with pytest.raises(PermanentFailure):
        _handle_backfill(db, {"code": "NOUR10"})


def test_a_long_backfill_queues_its_own_continuation(db):
    """Queued inside the transaction that recorded this batch, so a crash
    re-runs the batch rather than losing the rest.
    """
    from app.services.commission.backfill import MAX_ORDERS_PER_RUN, _handle_backfill

    _affiliate(db, code="NOUR10")
    for index in range(3):
        _order(db, f"32{index:02d}")
    db.query(BackgroundJob).delete()
    db.flush()

    import app.services.commission.backfill as backfill_module

    original = backfill_module.MAX_ORDERS_PER_RUN
    backfill_module.MAX_ORDERS_PER_RUN = 2
    try:
        _handle_backfill(
            db, {"code": "NOUR10", "start_month": "2026-01", "end_month": None}
        )
    finally:
        backfill_module.MAX_ORDERS_PER_RUN = original
    db.flush()

    assert db.query(BackgroundJob).filter_by(kind=JobKind.BACKFILL_CODE).count() == 1
