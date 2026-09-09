"""When she actually started, and what her month list is made of.

Rule H01. The platform used to answer *when did she start* with *when did money
first appear*, which is a different question that usually gives the same answer.
These are the cases where it does not, and they are the reason the column
exists.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.passwords import hash_password
from app.models.affiliates import AffiliateProfile
from app.models.attributed_orders import AttributedOrder, CommissionState
from app.models.identity import UserAccount
from app.services.affiliates import (
    create_affiliate,
    set_collaboration_start,
    update_measurements,
)
from app.services.portal import months_for


@pytest.fixture(autouse=True)
def _working_month(monkeypatch):
    """Pin the clock. A month list that changes with the calendar is a test
    that passes until October."""
    monkeypatch.setattr("app.services.payroll.working_month", lambda: "2026-06")
    monkeypatch.setattr("app.services.portal.working_month", lambda: "2026-06")


def _affiliate(db, name="Nour", email="nour@example.com") -> AffiliateProfile:
    account = UserAccount(
        email=email,
        password_hash=hash_password("quiet-harbour-lantern"),
        status="active",
        display_name=name,
    )
    db.add(account)
    db.flush()
    affiliate = create_affiliate(db, user_account_id=account.id, name=name)
    db.flush()
    return affiliate


def _order(db, affiliate, month, order_id="1001"):
    """An order already attributed, written straight in.

    `attributed_order` points at `order_index`, so the index row comes first.
    The paths that produce these have their own tests; this file is about which
    months a model is offered, so it starts from the row.
    """
    db.execute(
        text(
            "INSERT INTO order_index (shopify_order_id, order_number, placed_at,"
            " business_month, discount_codes, subtotal_piastres, total_piastres,"
            " shipping_piastres, tax_piastres, currency,"
            " original_subtotal_piastres, original_total_piastres)"
            " VALUES (:i, :n, now(), :m, ARRAY['NOUR10'], 10000, 10000, 0, 0,"
            " 'EGP', 10000, 10000)"
        ),
        {"i": order_id, "n": f"#{order_id}", "m": month},
    )
    db.add(
        AttributedOrder(
            affiliate_id=affiliate.id,
            shopify_order_id=order_id,
            business_month=month,
            commission_base_piastres=10_000,
            commission_state=CommissionState.EARNED,
        )
    )
    db.flush()


# ── What the column is for ─────────────────────────────────────────────────


def test_a_recorded_start_opens_the_months_she_sold_nothing_in(db):
    """H01's headline case, and the reason a derivation is not good enough.

    She started in February and her first order landed in April. February and
    March are real months she was here for; the derivation drops them, and a
    model reading her own dashboard cannot tell "you sold nothing" from "you
    did not exist".
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "2026-04")

    assert months_for(db, affiliate) == ["2026-04", "2026-05", "2026-06"][::-1]

    set_collaboration_start(db, affiliate, "2026-02")
    db.flush()

    assert months_for(db, affiliate) == [
        "2026-06",
        "2026-05",
        "2026-04",
        "2026-03",
        "2026-02",
    ]


def test_a_recorded_start_wins_even_when_an_order_is_older(db):
    """An order attributed before she started is a matching error.

    It is not a reason to open that month to her. The diagnostics for a
    mis-attributed order live on the maintainer's side; her picker should show
    the months she was actually here for.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "2026-01")

    set_collaboration_start(db, affiliate, "2026-05")
    db.flush()

    assert months_for(db, affiliate) == ["2026-06", "2026-05"]


def test_no_recorded_start_keeps_the_old_derivation(db):
    """Nothing is backfilled, so absence must not change what anybody sees.

    This is the compatibility guarantee for every model already on the
    platform: until somebody records a start, her months are exactly what they
    were before the column existed.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "2026-03")

    assert affiliate.collaboration_start_month is None
    assert months_for(db, affiliate) == ["2026-06", "2026-05", "2026-04", "2026-03"]


def test_clearing_a_start_returns_her_to_the_derivation(db):
    """Clearing is a real answer, not a failure to answer."""
    affiliate = _affiliate(db)
    _order(db, affiliate, "2026-03")
    set_collaboration_start(db, affiliate, "2026-01")
    db.flush()
    assert months_for(db, affiliate)[-1] == "2026-01"

    set_collaboration_start(db, affiliate, None)
    db.flush()

    assert affiliate.collaboration_start_month is None
    assert months_for(db, affiliate)[-1] == "2026-03"


def test_a_start_before_the_platform_is_floored_not_honoured(db):
    """Her real history may go back further; the platform's orders do not.

    `set_collaboration_start` refuses to record one, but a value already in the
    column - from a migration, a fixture, a future import - must not open
    months that can only ever be empty.
    """
    affiliate = _affiliate(db)
    affiliate.collaboration_start_month = "2025-04"
    db.flush()

    assert months_for(db, affiliate)[-1] == "2026-01"


# ── What it refuses ────────────────────────────────────────────────────────


def test_a_start_before_the_horizon_is_refused_with_a_reason(db):
    affiliate = _affiliate(db)

    with pytest.raises(ValueError, match="settled before the platform"):
        set_collaboration_start(db, affiliate, "2025-11")


def test_a_start_in_the_future_is_refused(db):
    affiliate = _affiliate(db)

    with pytest.raises(ValueError, match="cannot be in the future"):
        set_collaboration_start(db, affiliate, "2026-09")


def test_a_malformed_month_is_refused_before_the_database_sees_it(db):
    affiliate = _affiliate(db)

    with pytest.raises(ValueError, match="looks like 2026-03"):
        set_collaboration_start(db, affiliate, "2026-13")


def test_the_database_refuses_a_malformed_month_too(db):
    """The service is not the only thing that writes rows.

    A fixture, a migration or a console session bypasses every check above.
    This one it does not.
    """
    affiliate = _affiliate(db)

    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "UPDATE affiliate_profile SET collaboration_start_month = '2026-13'"
                " WHERE id = :id"
            ),
            {"id": affiliate.id},
        )
        db.flush()


def test_setting_the_month_it_already_has_records_nothing(db):
    """An audit trail full of "changed March to March" is an audit trail
    nobody reads."""
    affiliate = _affiliate(db)
    set_collaboration_start(db, affiliate, "2026-02")
    db.flush()
    before = db.scalar(text("SELECT count(*) FROM audit_event"))

    set_collaboration_start(db, affiliate, "2026-02")
    db.flush()

    assert db.scalar(text("SELECT count(*) FROM audit_event")) == before


def test_recording_a_start_is_audited(db):
    affiliate = _affiliate(db)
    set_collaboration_start(db, affiliate, "2026-02", actor_email="boda@hba.test")
    db.flush()

    actions = [
        row[0] for row in db.execute(text("SELECT action FROM audit_event ORDER BY id"))
    ]
    assert "affiliate.collaboration_start_set" in actions


# ── Measurements ───────────────────────────────────────────────────────────


def test_measurements_are_optional_and_stay_none(db):
    """Missing is a normal state (A05). Not zero - a zero is a measurement."""
    affiliate = _affiliate(db)

    assert affiliate.height_cm is None
    assert affiliate.weight_kg is None


def test_a_measurement_outside_the_bounds_is_refused_in_words(db):
    """The bounds catch a mistyped phone number in a height field.

    The message says what a height is, rather than naming a constraint.
    """
    affiliate = _affiliate(db)

    with pytest.raises(ValueError, match="between 100 and 250"):
        update_measurements(db, affiliate, height_cm=1012345678)


def test_one_measurement_can_be_given_without_the_other(db):
    affiliate = _affiliate(db)

    update_measurements(db, affiliate, height_cm=170)
    db.flush()

    assert affiliate.height_cm == 170
    assert affiliate.weight_kg is None


def test_the_audit_records_that_she_changed_them_not_what_they_are(db):
    """They are hers, and the trail is read by staff who may not change them.

    "She updated her measurements" is the whole of what an audit needs.
    """
    affiliate = _affiliate(db)
    update_measurements(db, affiliate, height_cm=170, weight_kg=55)
    db.flush()

    rows = list(
        db.execute(
            text(
                "SELECT action, before_json::text, after_json::text"
                " FROM audit_event ORDER BY id"
            )
        )
    )
    entry = [row for row in rows if row[0] == "affiliate.measurements_updated"]
    assert entry, "the change was not recorded at all"
    assert "170" not in (entry[0][2] or "")
    assert "55" not in (entry[0][2] or "")
