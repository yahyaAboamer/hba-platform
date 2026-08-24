"""Pay terms over time.

Spec section 9.5. What an affiliate is owed *per month* - not how much, which
is Phase 4. Terms are effective-dated, so a rate change is a new period rather
than an edit, and historical months keep the terms that were in force.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, IntegrityError

from app.core.passwords import hash_password
from app.models.compensation import CompensationPeriod, CompensationType
from app.models.identity import UserAccount
from app.services.affiliates import create_affiliate
from app.services.compensation import set_terms, terms_for


def _affiliate(db, name="Nour"):
    account = UserAccount(
        email=f"{name.lower()}@example.com",
        password_hash=hash_password("a-long-enough-password"),
        status="active",
        display_name=name,
    )
    db.add(account)
    db.flush()
    return create_affiliate(db, user_account_id=account.id, name=name)


def _commission(db, affiliate, start_month="2026-03", end_month=None, rate_bp=1000):
    return set_terms(
        db,
        affiliate,
        start_month=start_month,
        end_month=end_month,
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=rate_bp,
    )


# ── Terms apply to months ──────────────────────────────────────────────────────


def test_terms_apply_from_their_start_month(db):
    nour = _affiliate(db)
    _commission(db, nour, "2026-03")
    db.flush()

    assert terms_for(db, nour, "2026-03").commission_rate_bp == 1000


def test_terms_do_not_apply_before_they_start(db):
    nour = _affiliate(db)
    _commission(db, nour, "2026-03")
    db.flush()

    assert terms_for(db, nour, "2026-02") is None


def test_terms_stop_applying_after_they_end(db):
    nour = _affiliate(db)
    _commission(db, nour, "2026-03", "2026-06")
    db.flush()

    assert terms_for(db, nour, "2026-06") is not None
    assert terms_for(db, nour, "2026-07") is None


def test_a_rate_change_is_a_new_period_not_an_edit(db):
    """Editing would rewrite history: an approved month would silently
    recalculate at the new rate the next time anyone looked.
    """
    nour = _affiliate(db)
    _commission(db, nour, "2026-01", "2026-06", rate_bp=800)
    _commission(db, nour, "2026-07", rate_bp=1000)
    db.flush()

    assert terms_for(db, nour, "2026-04").commission_rate_bp == 800
    assert terms_for(db, nour, "2026-09").commission_rate_bp == 1000


def test_an_affiliate_with_no_terms_has_none(db):
    nour = _affiliate(db)
    db.flush()
    assert terms_for(db, nour, "2026-03") is None


def test_one_affiliates_terms_do_not_apply_to_another(db):
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    _commission(db, nour, "2026-03")
    db.flush()

    assert terms_for(db, sara, "2026-03") is None


# ── No overlaps ────────────────────────────────────────────────────────────────


def test_overlapping_terms_are_refused_by_the_database(db):
    """Two rates in force for one month is not a question with an answer."""
    nour = _affiliate(db)
    _commission(db, nour, "2026-03", "2026-08")
    db.flush()

    with pytest.raises(IntegrityError):
        _commission(db, nour, "2026-06", "2026-10")
        db.flush()


def test_adjacent_terms_are_allowed(db):
    """A rate change at a month boundary is the ordinary case and must work."""
    nour = _affiliate(db)
    _commission(db, nour, "2026-01", "2026-06", rate_bp=800)
    _commission(db, nour, "2026-07", rate_bp=1000)
    db.flush()

    count = db.execute(
        text("SELECT count(*) FROM compensation_period WHERE affiliate_id = :a"),
        {"a": nour.id},
    ).scalar()
    assert count == 2


def test_two_open_ended_periods_are_refused(db):
    nour = _affiliate(db)
    _commission(db, nour, "2026-03")
    db.flush()

    with pytest.raises(IntegrityError):
        _commission(db, nour, "2026-09")
        db.flush()


def test_different_affiliates_may_hold_the_same_months(db):
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    _commission(db, nour, "2026-03")
    _commission(db, sara, "2026-03")
    db.flush()

    assert terms_for(db, nour, "2026-05") is not None
    assert terms_for(db, sara, "2026-05") is not None


# ── The three types ────────────────────────────────────────────────────────────


def test_a_commission_type_carries_only_a_rate(db):
    nour = _affiliate(db)
    terms = _commission(db, nour)
    db.flush()

    assert terms.compensation_type == CompensationType.COMMISSION
    assert terms.commission_rate_bp == 1000
    assert terms.fixed_amount_piastres is None
    assert terms.base_amount_piastres is None


def test_a_fixed_plus_commission_carries_a_salary(db):
    nour = _affiliate(db)
    terms = set_terms(
        db,
        nour,
        start_month="2026-03",
        compensation_type=CompensationType.FIXED_PLUS_COMMISSION,
        commission_rate_bp=1000,
        fixed_amount_piastres=500_000,
    )
    db.flush()

    assert terms.fixed_amount_piastres == 500_000
    assert terms.base_amount_piastres is None


def test_a_base_guarantee_carries_a_base(db):
    nour = _affiliate(db)
    terms = set_terms(
        db,
        nour,
        start_month="2026-03",
        compensation_type=CompensationType.BASE_GUARANTEE,
        commission_rate_bp=1000,
        base_amount_piastres=800_000,
    )
    db.flush()

    assert terms.base_amount_piastres == 800_000
    assert terms.fixed_amount_piastres is None


# ── Per-type field validity, enforced by the database ──────────────────────────


def test_a_commission_type_may_not_carry_a_fixed_amount(db):
    """A field nothing reads is worse than a missing one: the next person to
    look assumes it is being paid.
    """
    nour = _affiliate(db)
    db.flush()
    with pytest.raises(DatabaseError):
        db.execute(
            text(
                "INSERT INTO compensation_period (affiliate_id, start_month, "
                "compensation_type, commission_rate_bp, fixed_amount_piastres) "
                "VALUES (:a, '2026-03', 'commission', 1000, 500000)"
            ),
            {"a": nour.id},
        )


def test_a_fixed_plus_commission_must_carry_a_fixed_amount(db):
    nour = _affiliate(db)
    db.flush()
    with pytest.raises(DatabaseError):
        db.execute(
            text(
                "INSERT INTO compensation_period (affiliate_id, start_month, "
                "compensation_type, commission_rate_bp) "
                "VALUES (:a, '2026-03', 'fixed_plus_commission', 1000)"
            ),
            {"a": nour.id},
        )


def test_a_base_guarantee_may_not_carry_a_fixed_amount(db):
    nour = _affiliate(db)
    db.flush()
    with pytest.raises(DatabaseError):
        db.execute(
            text(
                "INSERT INTO compensation_period (affiliate_id, start_month, "
                "compensation_type, commission_rate_bp, base_amount_piastres, "
                "fixed_amount_piastres) "
                "VALUES (:a, '2026-03', 'base_guarantee', 1000, 800000, 500000)"
            ),
            {"a": nour.id},
        )


def test_a_base_guarantee_must_carry_a_base_amount(db):
    nour = _affiliate(db)
    db.flush()
    with pytest.raises(DatabaseError):
        db.execute(
            text(
                "INSERT INTO compensation_period (affiliate_id, start_month, "
                "compensation_type, commission_rate_bp) "
                "VALUES (:a, '2026-03', 'base_guarantee', 1000)"
            ),
            {"a": nour.id},
        )


def test_an_unknown_type_is_refused_by_the_database(db):
    nour = _affiliate(db)
    db.flush()
    with pytest.raises(DatabaseError):
        db.execute(
            text(
                "INSERT INTO compensation_period (affiliate_id, start_month, "
                "compensation_type, commission_rate_bp) "
                "VALUES (:a, '2026-03', 'generous', 1000)"
            ),
            {"a": nour.id},
        )


# ── The service refuses the same things, readably ──────────────────────────────


def test_the_service_refuses_a_fixed_amount_on_a_commission_type(db):
    nour = _affiliate(db)
    with pytest.raises(ValueError, match="fixed_amount"):
        set_terms(
            db,
            nour,
            start_month="2026-03",
            compensation_type=CompensationType.COMMISSION,
            commission_rate_bp=1000,
            fixed_amount_piastres=500_000,
        )


def test_the_service_requires_a_base_for_a_base_guarantee(db):
    nour = _affiliate(db)
    with pytest.raises(ValueError, match="base_amount"):
        set_terms(
            db,
            nour,
            start_month="2026-03",
            compensation_type=CompensationType.BASE_GUARANTEE,
            commission_rate_bp=1000,
        )


def test_the_service_refuses_an_unknown_type(db):
    nour = _affiliate(db)
    with pytest.raises(ValueError, match="Unknown compensation type"):
        set_terms(
            db,
            nour,
            start_month="2026-03",
            compensation_type="generous",
            commission_rate_bp=1000,
        )


# ── Money and rates ────────────────────────────────────────────────────────────


def test_a_rate_over_one_hundred_percent_is_refused(db):
    nour = _affiliate(db)
    with pytest.raises(ValueError):
        _commission(db, nour, rate_bp=10_001)


def test_a_rate_of_zero_is_refused(db):
    """A zero-rate period is almost certainly a mistake, and it would pay
    nothing while looking configured.
    """
    nour = _affiliate(db)
    with pytest.raises(ValueError):
        _commission(db, nour, rate_bp=0)


def test_a_rate_of_exactly_one_hundred_percent_is_allowed(db):
    nour = _affiliate(db)
    terms = _commission(db, nour, rate_bp=10_000)
    db.flush()
    assert terms.commission_rate_bp == 10_000


def test_money_refuses_a_float(db):
    """Piastres are integers. A float here is a rounding error waiting to be
    paid to somebody (ADR 0002).
    """
    nour = _affiliate(db)
    with pytest.raises(TypeError):
        set_terms(
            db,
            nour,
            start_month="2026-03",
            compensation_type=CompensationType.FIXED_PLUS_COMMISSION,
            commission_rate_bp=1000,
            fixed_amount_piastres=5000.50,
        )


def test_a_negative_amount_is_refused(db):
    nour = _affiliate(db)
    with pytest.raises(ValueError):
        set_terms(
            db,
            nour,
            start_month="2026-03",
            compensation_type=CompensationType.FIXED_PLUS_COMMISSION,
            commission_rate_bp=1000,
            fixed_amount_piastres=-1,
        )


# ── The customer discount is not the commission ────────────────────────────────


def test_the_customer_discount_is_stored_separately(db):
    """§10.4. A creator may give customers 10% off while earning 5%. Storing
    one and inferring the other is wrong exactly when it matters.
    """
    nour = _affiliate(db)
    terms = set_terms(
        db,
        nour,
        start_month="2026-03",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=500,
        expected_customer_discount_bp=1000,
    )
    db.flush()

    assert terms.commission_rate_bp == 500
    assert terms.expected_customer_discount_bp == 1000


def test_the_customer_discount_is_optional(db):
    nour = _affiliate(db)
    terms = _commission(db, nour)
    db.flush()
    assert terms.expected_customer_discount_bp is None


def test_the_customer_discount_is_never_derived_from_the_rate(db):
    """Guards against a well-meaning default that would make the two agree by
    construction and hide every real mismatch.
    """
    nour = _affiliate(db)
    terms = _commission(db, nour, rate_bp=750)
    db.flush()
    assert terms.expected_customer_discount_bp != terms.commission_rate_bp


# ── Periods and records ────────────────────────────────────────────────────────


def test_a_backwards_period_is_refused_readably(db):
    nour = _affiliate(db)
    with pytest.raises(ValueError, match="2026-06 to 2026-03"):
        _commission(db, nour, "2026-06", "2026-03")


def test_setting_terms_is_recorded(db):
    nour = _affiliate(db)
    _commission(db, nour)
    db.flush()

    actions = [row[0] for row in db.execute(text("SELECT action FROM audit_event"))]
    assert "compensation.set" in actions


def test_the_record_names_the_money(db):
    """Compensation changes are the ones most worth being able to reconstruct."""
    nour = _affiliate(db)
    _commission(db, nour, rate_bp=1234)
    db.flush()

    after = db.execute(
        text("SELECT after_json FROM audit_event WHERE action = 'compensation.set'")
    ).scalar()
    assert after["commission_rate_bp"] == 1234
    assert after["compensation_type"] == CompensationType.COMMISSION


def test_deleting_an_affiliate_takes_their_terms(db):
    nour = _affiliate(db)
    _commission(db, nour)
    db.flush()

    db.delete(nour)
    db.flush()

    assert db.query(CompensationPeriod).count() == 0
