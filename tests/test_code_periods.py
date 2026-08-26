"""Discount code ownership over time.

Spec section 9.2. A code belongs to an affiliate *for some months*, and the
answer to "who owned NOUR10 in April?" has to be a fact - because in Phase 4
that answer becomes money.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, IntegrityError

from app.core.businesstime import utcnow
from app.core.passwords import hash_password
from app.models.codes import DiscountCodePeriod
from app.models.identity import UserAccount
from app.services.affiliates import create_affiliate
from app.services.codes import (
    close_codes_for,
    codes_for,
    owner_of,
    register_code,
    registered_codes,
)


def _affiliate(db, name="Nour", email=None):
    account = UserAccount(
        email=email or f"{name.lower()}@example.com",
        password_hash=hash_password("a-long-enough-password"),
        status="active",
        display_name=name,
    )
    db.add(account)
    db.flush()
    return create_affiliate(db, user_account_id=account.id, name=name)


# ── Ownership for a month ──────────────────────────────────────────────────────


def test_a_code_is_owned_by_one_affiliate_for_a_month(db):
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-03")
    db.flush()

    assert owner_of(db, "NOUR10", "2026-03").id == nour.id


def test_ownership_does_not_start_before_the_period(db):
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-03")
    db.flush()

    assert owner_of(db, "NOUR10", "2026-02") is None


def test_ownership_ends_when_the_period_does(db):
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-03", "2026-06")
    db.flush()

    assert owner_of(db, "NOUR10", "2026-06").id == nour.id
    assert owner_of(db, "NOUR10", "2026-07") is None


def test_an_open_ended_period_owns_indefinitely(db):
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-03")
    db.flush()

    assert owner_of(db, "NOUR10", "2099-12").id == nour.id


def test_an_unknown_code_is_owned_by_nobody(db):
    assert owner_of(db, "NOBODY", "2026-03") is None


# ── The constraint that stops the wrong person being paid ──────────────────────


def test_the_same_code_cannot_be_owned_by_two_affiliates_at_once(db):
    """The situation that pays the wrong person.

    The business says it cannot happen given how codes are issued. This makes
    that true rather than hoped.
    """
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    register_code(db, nour, "NOUR10", "2026-03")
    db.flush()

    with pytest.raises(IntegrityError):
        register_code(db, sara, "NOUR10", "2026-05")
        db.flush()


def test_the_same_code_can_move_to_another_affiliate_later(db):
    """Ownership is a period, not a property. March-June for Nour and
    July-onward for Sara is legitimate and must be storable.
    """
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    register_code(db, nour, "NOUR10", "2026-03", "2026-06")
    register_code(db, sara, "NOUR10", "2026-07")
    db.flush()

    assert owner_of(db, "NOUR10", "2026-05").id == nour.id
    assert owner_of(db, "NOUR10", "2026-08").id == sara.id


def test_the_exclusion_is_on_the_code_not_the_pair(db):
    """Guards against the constraint being written as (affiliate_id, code).

    That version would happily let two affiliates own one code in the same
    months, which is exactly what must never happen.
    """
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    register_code(db, nour, "SHARED", "2026-01", "2026-12")
    db.flush()

    with pytest.raises(IntegrityError):
        register_code(db, sara, "SHARED", "2026-06", "2026-06")
        db.flush()


def test_one_affiliate_may_hold_several_codes_in_a_month(db):
    """The rule is one model code per *order*, not one code per model."""
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-03")
    register_code(db, nour, "NOUR20", "2026-03")
    db.flush()

    assert sorted(codes_for(db, nour, "2026-03")) == ["NOUR10", "NOUR20"]


def test_an_affiliate_cannot_hold_the_same_code_twice_over(db):
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-03")
    db.flush()

    with pytest.raises(IntegrityError):
        register_code(db, nour, "NOUR10", "2026-05")
        db.flush()


# ── Case ───────────────────────────────────────────────────────────────────────


def test_a_code_is_stored_upper_case(db):
    """normalise_order upper-cases what Shopify sends. A lookup that misses on
    case attributes nothing, silently - which is the failure §10.4 exists to
    prevent.
    """
    nour = _affiliate(db)
    period = register_code(db, nour, "  nour10  ", "2026-03")
    db.flush()

    assert period.code == "NOUR10"


def test_lookup_is_case_insensitive(db):
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-03")
    db.flush()

    assert owner_of(db, "nour10", "2026-03").id == nour.id
    assert owner_of(db, "NoUr10", "2026-03").id == nour.id


def test_case_does_not_defeat_the_overlap_constraint(db):
    """Storing upper-case is what makes this work: 'nour10' and 'NOUR10' must
    collide, or two affiliates could own the same code by typing it
    differently.
    """
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    register_code(db, nour, "NOUR10", "2026-03")
    db.flush()

    with pytest.raises(IntegrityError):
        register_code(db, sara, "nour10", "2026-05")
        db.flush()


def test_an_empty_code_is_refused(db):
    nour = _affiliate(db)
    with pytest.raises(ValueError, match="code"):
        register_code(db, nour, "   ", "2026-03")


# ── Verification ───────────────────────────────────────────────────────────────


def test_a_code_starts_unverified(db):
    """Registration and verification are separate acts. §10.4 gates approval on
    verification, not on registration.
    """
    nour = _affiliate(db)
    period = register_code(db, nour, "NOUR10", "2026-03")
    db.flush()

    assert period.shopify_verified_at is None
    assert period.is_verified is False


def test_a_code_can_be_registered_already_verified(db):
    nour = _affiliate(db)
    period = register_code(db, nour, "NOUR10", "2026-03", verified_at=utcnow())
    db.flush()

    assert period.is_verified is True


def test_verification_records_when_not_merely_whether(db):
    """"Verified, but eight months ago" is a different answer from "verified",
    and a boolean cannot express it.
    """
    nour = _affiliate(db)
    moment = utcnow()
    period = register_code(db, nour, "NOUR10", "2026-03", verified_at=moment)
    db.flush()

    assert period.shopify_verified_at == moment


# ── Periods ────────────────────────────────────────────────────────────────────


def test_a_backwards_period_is_refused_readably(db):
    nour = _affiliate(db)
    with pytest.raises(ValueError, match="2026-06 to 2026-03"):
        register_code(db, nour, "NOUR10", "2026-06", "2026-03")


def test_a_malformed_month_is_refused(db):
    nour = _affiliate(db)
    with pytest.raises(ValueError, match="YYYY-MM"):
        register_code(db, nour, "NOUR10", "March")


def test_registering_a_code_is_recorded(db):
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-03")
    db.flush()

    actions = [
        row[0] for row in db.execute(text("SELECT action FROM audit_event"))
    ]
    assert "code.registered" in actions


# ── Closing on archive ─────────────────────────────────────────────────────────


def test_closing_ends_ownership_at_the_given_month(db):
    """Archiving says "from now on, not theirs". It cannot say "was never
    theirs" - that would rewrite attribution in months already paid.
    """
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-03")
    db.flush()

    close_codes_for(db, nour, "2026-08")
    db.flush()

    assert owner_of(db, "NOUR10", "2026-08").id == nour.id
    assert owner_of(db, "NOUR10", "2026-09") is None


def test_closing_never_shortens_history(db):
    """The months before the close date keep their owner, permanently."""
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-03")
    db.flush()

    close_codes_for(db, nour, "2026-08")
    db.flush()

    for month in ("2026-03", "2026-05", "2026-07"):
        assert owner_of(db, "NOUR10", month).id == nour.id


def test_closing_leaves_an_already_closed_period_alone(db):
    """A period that already ended earlier must not be extended by closing."""
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-03", "2026-05")
    db.flush()

    close_codes_for(db, nour, "2026-08")
    db.flush()

    assert owner_of(db, "NOUR10", "2026-06") is None


def test_a_closed_code_can_be_reissued_to_somebody_else(db):
    """Which is the point of closing rather than deleting."""
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    register_code(db, nour, "NOUR10", "2026-03")
    db.flush()

    close_codes_for(db, nour, "2026-08")
    db.flush()
    register_code(db, sara, "NOUR10", "2026-09")
    db.flush()

    assert owner_of(db, "NOUR10", "2026-07").id == nour.id
    assert owner_of(db, "NOUR10", "2026-09").id == sara.id


# ── Bulk lookup, for attribution ───────────────────────────────────────────────


def test_registered_codes_maps_code_to_affiliate_for_a_month(db):
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    register_code(db, nour, "NOUR10", "2026-03")
    register_code(db, sara, "SARA10", "2026-03")
    db.flush()

    assert registered_codes(db, "2026-03") == {
        "NOUR10": nour.id,
        "SARA10": sara.id,
    }


def test_registered_codes_respects_the_month(db):
    """Attribution asks about the order's month, not today's ownership."""
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    register_code(db, nour, "NOUR10", "2026-03", "2026-06")
    register_code(db, sara, "NOUR10", "2026-07")
    db.flush()

    assert registered_codes(db, "2026-04") == {"NOUR10": nour.id}
    assert registered_codes(db, "2026-08") == {"NOUR10": sara.id}


def test_registered_codes_is_empty_when_nothing_is_registered(db):
    assert registered_codes(db, "2026-03") == {}


def test_codes_for_an_affiliate_respects_the_month(db):
    nour = _affiliate(db)
    register_code(db, nour, "OLD", "2026-01", "2026-02")
    register_code(db, nour, "NEW", "2026-03")
    db.flush()

    assert codes_for(db, nour, "2026-01") == ["OLD"]
    assert codes_for(db, nour, "2026-03") == ["NEW"]


# ── The table's own guards ─────────────────────────────────────────────────────


def test_a_period_cannot_exist_without_an_affiliate(db):
    db.add(DiscountCodePeriod(affiliate_id=999999, code="X", start_month="2026-03"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_the_range_is_generated_not_supplied(db):
    nour = _affiliate(db)
    db.flush()
    with pytest.raises(DatabaseError):
        db.execute(
            text(
                "INSERT INTO discount_code_period "
                "(affiliate_id, code, start_month, effective_range) "
                "VALUES (:a, 'X', '2026-03', '[2000-01-01,2001-01-01)')"
            ),
            {"a": nour.id},
        )


def test_deleting_an_affiliate_takes_their_code_periods(db):
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-03")
    db.flush()

    db.delete(nour)
    db.flush()

    assert db.query(DiscountCodePeriod).count() == 0


def test_codes_with_status_says_whether_shopify_confirmed_each_one(db):
    """Registered and confirmed are different facts, and a screen needs both.

    An unconfirmed code still attributes orders. What is unknown is whether it
    exists on Shopify at all - so if it was mistyped, no order will ever carry
    it, and nothing looks wrong (docs/limits.md).
    """
    from app.services.codes import codes_with_status

    nour = _affiliate(db)
    register_code(db, nour, "SEEN", "2026-01", verified_at=utcnow())
    register_code(db, nour, "UNSEEN", "2026-01")
    db.flush()

    found = codes_with_status(db, nour, "2026-03")

    assert [(row["code"], row["verified"]) for row in found] == [
        ("SEEN", True),
        ("UNSEEN", False),
    ]


def test_codes_for_and_codes_with_status_agree(db):
    """One definition of "owned in this month", used two ways.

    Two copies of that filter would eventually disagree, and the way anybody
    would find out is a model paid for somebody else's orders.
    """
    from app.services.codes import codes_with_status

    nour = _affiliate(db)
    register_code(db, nour, "KEPT", "2026-01")
    register_code(db, nour, "ENDED", "2026-01", end_month="2026-02")
    db.flush()

    for month in ("2026-01", "2026-02", "2026-03"):
        assert codes_for(db, nour, month) == [
            row["code"] for row in codes_with_status(db, nour, month)
        ]
