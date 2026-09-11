"""The transition, rehearsed. Phase 09A.

AC13, AC14, AC23 and AC64 in one place: the properties a release has to have
before anybody runs it against real money, asserted rather than asserted-about.

**This does not rehearse D01.** Which month the platform starts paying for, and
which historical statements are already real, is an owner decision that is
still open. What is rehearsed here is everything that must be true *whatever*
that answer turns out to be — so that when it arrives, the only new thing is
the boundary itself.
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
from app.services.compensation import set_terms
from app.services.payments import balance_for, record_payment
from app.services.payroll import approve_month, is_historical

BEFORE = "2026-03"
AFTER = "2026-09"


@pytest.fixture(autouse=True)
def _go_live(monkeypatch):
    """The boundary, pinned. D01 will decide the real one; every rule here
    holds wherever it lands.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "2026-08", raising=False)


@pytest.fixture(autouse=True)
def _working_month(monkeypatch):
    monkeypatch.setattr(
        "app.services.portal.working_month", lambda: AFTER, raising=True
    )


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
    affiliate.status = "active"
    register_code(db, affiliate, f"{name.upper()}10", "2026-01")
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    db.flush()
    return affiliate


def _order(db, affiliate, order_id, base, month):
    db.add(
        OrderIndex(
            shopify_order_id=order_id,
            order_number=f"#{order_id}",
            placed_at=datetime(2026, 3, 4, 12, tzinfo=timezone.utc),
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
            commission_state=CommissionState.EARNED,
        )
    )
    db.flush()
    return order_id


# -- AC13: the months that were paid before the platform existed ---------------


def test_a_month_before_the_boundary_is_worth_something_and_owes_nothing(db):
    """ADR 0036, and the distinction the whole transition rests on.

    Her March is calculated, approved and frozen like any other month, so her
    dashboard shows what March was worth. What it is **not** is payable: that
    money moved before this platform existed, and a balance is what is still
    outstanding.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000, BEFORE)

    snapshot = approve_month(db, affiliate, BEFORE)
    balance = balance_for(db, affiliate, BEFORE)

    assert is_historical(BEFORE)
    assert snapshot.approved_obligation_piastres == 200_000, "worth something"
    assert balance["balance_piastres"] == 0, "and owes nothing"
    assert balance["state"] == "settled_externally"


def test_no_transfer_can_be_recorded_against_a_month_settled_outside(db):
    """**The guarantee that stops the transition inventing money.**

    A migration that reconstructed history and then recorded transfers to match
    it would manufacture a payment that never happened and a receipt nobody
    sent. The refusal lives in the ledger rather than in a script, so no
    import, however well meant, can go around it.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000, BEFORE)
    snapshot = approve_month(db, affiliate, BEFORE)

    with pytest.raises(ValueError, match="settled outside|outside the platform"):
        record_payment(
            db,
            affiliate,
            amount_piastres=200_000,
            allocations={snapshot.id: 200_000},
        )


def test_a_month_after_the_boundary_is_ordinary(db):
    """The other side of the same line, so the rule is a boundary rather than
    a blanket. September is owed, and payable.
    """
    affiliate = _model(db)
    _order(db, affiliate, "2", 2_000_000, AFTER)

    approve_month(db, affiliate, AFTER)
    balance = balance_for(db, affiliate, AFTER)

    assert not is_historical(AFTER)
    assert balance["balance_piastres"] == 200_000


# -- AC14 / AC64: running it twice ---------------------------------------------


def test_reading_readiness_twice_says_the_same_thing_and_writes_nothing(db):
    """H06 and AC14. Readiness is a **question**, not a state.

    A rehearsal is run repeatedly by definition — that is what makes it a
    rehearsal — so the thing being rehearsed must not change under it. Nothing
    is stored, so asking twice cannot drift and a dry run cannot become a
    commitment by accident.
    """
    from app.services.setup import setup_readiness

    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000, BEFORE)

    first = setup_readiness(
        db, affiliate, working=AFTER, is_historical=is_historical
    )
    second = setup_readiness(
        db, affiliate, working=AFTER, is_historical=is_historical
    )

    assert first == second


def test_approving_the_same_historical_month_twice_is_refused(db):
    """AC64's *phased cutover handles irreversible new financial events*.

    A transition that runs twice — because it timed out, because somebody was
    not sure it had worked — must not agree a month twice. The second attempt
    is refused by the same blocker that refuses it on any other month.
    """
    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000, BEFORE)
    approve_month(db, affiliate, BEFORE)

    with pytest.raises(ValueError, match="cannot be approved"):
        approve_month(db, affiliate, BEFORE)


# -- AC23: ingestion that is interrupted or repeated ---------------------------
#
# **Duplicate ingestion is not re-tested here.** It is held by the real upsert
# path in `test_order_index.py::test_writing_the_same_order_twice_updates_rather_than_duplicates`
# and `test_shopify_sync.py::test_syncing_the_same_order_twice_leaves_one_row`.
# A version written against a test helper that inserts rows directly would
# prove the helper works and nothing about the platform - which is what the
# first draft of this file did.


def test_an_order_cannot_be_moved_between_months_by_a_later_sweep(db):
    """**The database refuses it**, not a service.

    An out-of-order webhook or a re-import with a different clock would
    otherwise move money between months — and a month that has been agreed and
    paid does not get to change what was in it.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    affiliate = _model(db)
    _order(db, affiliate, "1", 2_000_000, AFTER)

    with pytest.raises(DBAPIError):
        db.execute(
            text(
                "UPDATE attributed_order SET business_month = '2026-10' "
                "WHERE shopify_order_id = '1'"
            )
        )
    db.rollback()


# -- D01: the boundary, and how much history a model sees ----------------------


def test_a_model_from_before_2026_sees_history_back_to_january(db):
    """**D01, answered 11 September 2026.**

    > For models that were created before 2026, we show them the history till
    > January 2026.

    Not earlier: there are no orders indexed before January, so an offered
    month would be an empty screen with nothing to explain it.
    """
    from app.services.portal import months_for

    affiliate = _model(db)
    affiliate.collaboration_start_month = "2025-04"
    db.flush()

    months = months_for(db, affiliate)

    assert months[-1] == "2026-01", "floored at the platform's first month"
    assert months[0] == AFTER


def test_a_model_who_started_later_sees_only_her_own_months(db):
    """> Anyone that was created after 2026, we show him starting from his
    > starting month.

    June is her first. January is not hers, and a month that predates her is an
    empty screen with no way to tell whether that means nothing happened or
    something is broken.
    """
    from app.services.portal import months_for

    affiliate = _model(db)
    affiliate.collaboration_start_month = "2026-06"
    db.flush()

    months = months_for(db, affiliate)

    assert months[-1] == "2026-06"
    assert "2026-05" not in months


def test_the_boundary_is_a_setting_and_the_rules_follow_it(db, monkeypatch):
    """D01 chose September, and production is already configured that way.

    The rule is asserted against the setting rather than against the literal
    month, so moving the boundary moves the behaviour with it - and nothing
    here has to be rewritten if it ever moves again.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "2026-09", raising=False)

    assert is_historical("2026-08") is True
    assert is_historical("2026-09") is False
