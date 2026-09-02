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
from app.services.compensation import (
    close_terms,
    set_terms,
    terms_for,
)


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


def _approved_month(db, affiliate, month):
    """A month already agreed and paid, which nothing may retroactively change."""
    from app.models.payroll import CalculationState, PayrollMonth

    row = PayrollMonth(affiliate_id=affiliate.id, month=month)
    row.calculation_state = CalculationState.APPROVED
    db.add(row)
    db.flush()
    return row


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


def test_the_database_still_refuses_two_open_ended_periods(db):
    """The backstop, tested where it still applies.

    `set_terms` no longer reaches this constraint - it ends the arrangement in
    force first, which is what a rate change means. The constraint is what
    stops anything *else* from writing overlapping terms, so it is exercised
    here by inserting straight into the table.
    """
    nour = _affiliate(db)
    _commission(db, nour, "2026-03")
    db.flush()

    db.add(
        CompensationPeriod(
            affiliate_id=nour.id,
            start_month="2026-09",
            end_month=None,
            compensation_type=CompensationType.COMMISSION,
            commission_rate_bp=1000,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


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


# ── Rewriting a mistyped arrangement ───────────────────────────────────────
#
# There is no separate "correct" call any more. Naming the month an
# arrangement already starts in rewrites it; a later month opens a new one.
# The rules these tests protect did not change - only the door they are
# reached through.


def _rewrite(db, affiliate, terms, **fields):
    """Rewrite an arrangement by naming its own start month."""
    body = {
        "compensation_type": terms.compensation_type,
        "commission_rate_bp": terms.commission_rate_bp,
        "fixed_amount_piastres": terms.fixed_amount_piastres,
        "base_amount_piastres": terms.base_amount_piastres,
        "expected_customer_discount_bp": terms.expected_customer_discount_bp,
    }
    body.update(fields)
    return set_terms(db, affiliate, start_month=terms.start_month, **body)


def test_a_mistyped_rate_can_be_rewritten(db):
    affiliate = _affiliate(db)
    terms = _commission(db, affiliate, rate_bp=100)
    db.flush()

    assert _rewrite(db, affiliate, terms, commission_rate_bp=1000).commission_rate_bp == 1000


def test_a_mistyped_salary_can_be_rewritten(db):
    affiliate = _affiliate(db)
    terms = set_terms(
        db,
        affiliate,
        start_month="2026-03",
        compensation_type=CompensationType.FIXED_PLUS_COMMISSION,
        commission_rate_bp=1000,
        fixed_amount_piastres=5_000_000,
    )
    db.flush()

    rewritten = _rewrite(db, affiliate, terms, fixed_amount_piastres=500_000)
    assert rewritten.fixed_amount_piastres == 500_000


def test_a_mistyped_base_amount_can_be_rewritten(db):
    affiliate = _affiliate(db)
    terms = set_terms(
        db,
        affiliate,
        start_month="2026-03",
        compensation_type=CompensationType.BASE_GUARANTEE,
        commission_rate_bp=1000,
        base_amount_piastres=8_000_000,
    )
    db.flush()

    rewritten = _rewrite(db, affiliate, terms, base_amount_piastres=800_000)
    assert rewritten.base_amount_piastres == 800_000


def test_the_customer_discount_can_be_rewritten(db):
    affiliate = _affiliate(db)
    terms = _commission(db, affiliate)
    db.flush()

    rewritten = _rewrite(db, affiliate, terms, expected_customer_discount_bp=1500)
    assert rewritten.expected_customer_discount_bp == 1500


def test_a_rewrite_records_what_it_changed_from(db):
    """The audit carries the old figure. Without it there is no way to answer
    "what was this before somebody fixed it".
    """
    from sqlalchemy import text as sql_text

    affiliate = _affiliate(db)
    terms = _commission(db, affiliate, rate_bp=100)
    db.flush()
    _rewrite(db, affiliate, terms, commission_rate_bp=1000)
    db.flush()

    row = db.execute(
        sql_text(
            "select before_json, after_json from audit_event "
            "where action = 'compensation.corrected' order by id desc limit 1"
        )
    ).fetchone()
    assert row is not None
    assert "100" in str(row.before_json)
    assert "1000" in str(row.after_json)


def test_a_rewrite_cannot_produce_an_invalid_arrangement(db):
    """Validation is shared with creating, so a rewrite cannot produce
    something creation would have refused.
    """
    affiliate = _affiliate(db)
    terms = _commission(db, affiliate)
    db.flush()

    with pytest.raises(ValueError):
        _rewrite(db, affiliate, terms, fixed_amount_piastres=500_000)


def test_a_rewrite_refuses_an_impossible_rate(db):
    affiliate = _affiliate(db)
    terms = _commission(db, affiliate)
    db.flush()

    with pytest.raises(ValueError):
        _rewrite(db, affiliate, terms, commission_rate_bp=10_001)


def test_a_rewrite_refuses_a_float(db):
    """Piastres are integers. A float is a rounding error waiting to be paid."""
    affiliate = _affiliate(db)
    terms = set_terms(
        db,
        affiliate,
        start_month="2026-03",
        compensation_type=CompensationType.FIXED_PLUS_COMMISSION,
        commission_rate_bp=1000,
        fixed_amount_piastres=500_000,
    )
    db.flush()

    with pytest.raises(TypeError):
        _rewrite(db, affiliate, terms, fixed_amount_piastres=5000.50)


def test_changing_type_to_one_needing_an_amount_requires_it(db):
    affiliate = _affiliate(db)
    terms = _commission(db, affiliate)
    db.flush()

    with pytest.raises(ValueError):
        _rewrite(
            db,
            affiliate,
            terms,
            compensation_type=CompensationType.BASE_GUARANTEE,
            base_amount_piastres=None,
        )


# ── Ending an arrangement so another can start ─────────────────────────────────


def test_an_open_ended_arrangement_can_be_closed(db):
    """Without this it blocks every later one: the database refuses two
    overlapping periods, and there was no way to end the first.
    """
    nour = _affiliate(db)
    terms = _commission(db, nour, "2026-01", rate_bp=800)
    db.flush()

    close_terms(db, terms, "2026-06")
    db.flush()

    assert terms_for(db, nour, "2026-07") is None


def test_closing_then_starting_new_terms_works(db):
    """Moving a model onto a different arrangement, which was impossible."""
    nour = _affiliate(db)
    terms = _commission(db, nour, "2026-01", rate_bp=800)
    db.flush()

    close_terms(db, terms, "2026-06")
    db.flush()
    _commission(db, nour, "2026-07", rate_bp=1200)
    db.flush()

    assert terms_for(db, nour, "2026-04").commission_rate_bp == 800
    assert terms_for(db, nour, "2026-09").commission_rate_bp == 1200


def test_closing_does_not_rewrite_the_months_already_covered(db):
    """The months they were on the old terms keep saying so - which is what
    makes a past month still calculable at the rate that applied then.
    """
    nour = _affiliate(db)
    terms = _commission(db, nour, "2026-01", rate_bp=800)
    db.flush()

    close_terms(db, terms, "2026-06")
    db.flush()

    assert terms_for(db, nour, "2026-02").commission_rate_bp == 800


def test_closing_before_the_start_is_refused(db):
    nour = _affiliate(db)
    terms = _commission(db, nour, "2026-06")
    db.flush()

    with pytest.raises(ValueError):
        close_terms(db, terms, "2026-03")


def test_closing_is_recorded(db):
    nour = _affiliate(db)
    terms = _commission(db, nour, "2026-01")
    db.flush()

    close_terms(db, terms, "2026-06")
    db.flush()

    actions = [row[0] for row in db.execute(text("SELECT action FROM audit_event"))]
    assert "compensation.closed" in actions


# --- Changing a rate ---------------------------------------------------
#
# The screen has always said "Saving this ends that arrangement and starts a
# new one". Until now it did not: the second arrangement was refused for
# overlapping the first, and every rate change after the very first one failed
# with a 409 nobody could act on.


def test_a_later_arrangement_ends_the_one_in_force(db):
    affiliate = _affiliate(db)
    first = set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type="commission",
        commission_rate_bp=800,
    )
    assert first.end_month is None, "the first arrangement is open-ended"

    second = set_terms(
        db,
        affiliate,
        start_month="2026-09",
        compensation_type="commission",
        commission_rate_bp=1200,
    )

    assert first.end_month == "2026-08", "the old arrangement must end the month before"
    assert second.start_month == "2026-09"
    assert second.end_month is None, "the new arrangement is now the one in force"


def test_the_months_already_paid_keep_their_old_rate(db):
    """The point of ending rather than editing."""
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type="commission",
        commission_rate_bp=800,
    )
    set_terms(
        db,
        affiliate,
        start_month="2026-09",
        compensation_type="commission",
        commission_rate_bp=1200,
    )

    assert terms_for(db, affiliate, "2026-05").commission_rate_bp == 800
    assert terms_for(db, affiliate, "2026-08").commission_rate_bp == 800
    assert terms_for(db, affiliate, "2026-09").commission_rate_bp == 1200


def test_backfilling_earlier_history_does_not_end_the_current_arrangement(db):
    """Terms that stop before the open one starts do not overlap it."""
    affiliate = _affiliate(db)
    current = set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type="commission",
        commission_rate_bp=800,
    )
    set_terms(
        db,
        affiliate,
        start_month="2025-03",
        end_month="2025-12",
        compensation_type="commission",
        commission_rate_bp=600,
    )

    assert current.end_month is None, "backfilling history must not end today's terms"
    assert terms_for(db, affiliate, "2025-06").commission_rate_bp == 600
    assert terms_for(db, affiliate, "2026-06").commission_rate_bp == 800


def test_the_same_month_rewrites_the_arrangement_rather_than_refusing(db):
    """Naming the month one already starts in means "I meant this instead".

    It used to refuse and tell the maintainer to *correct* it instead - a
    second control, chosen from a radio, whose difference from this one was
    real but almost impossible to hold in mind at the moment of use. The
    walkthrough asked for one control; this is how one control keeps both
    meanings.
    """
    affiliate = _affiliate(db)
    first = set_terms(
        db,
        affiliate,
        start_month="2026-09",
        compensation_type="commission",
        commission_rate_bp=800,
    )
    db.flush()

    again = set_terms(
        db,
        affiliate,
        start_month="2026-09",
        compensation_type="commission",
        commission_rate_bp=1200,
    )
    db.flush()

    assert again.id == first.id, "rewritten in place, not a second period"
    assert again.commission_rate_bp == 1200


def test_rewriting_clears_an_amount_the_new_type_does_not_use(db):
    """A salary left behind on a commission-only arrangement is money nothing
    reads, which the next person to look assumes is being paid.
    """
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-09",
        compensation_type="fixed_plus_commission",
        commission_rate_bp=800,
        fixed_amount_piastres=500_000,
    )
    db.flush()

    rewritten = set_terms(
        db,
        affiliate,
        start_month="2026-09",
        compensation_type="commission",
        commission_rate_bp=800,
    )
    db.flush()

    assert rewritten.fixed_amount_piastres is None


def test_rewriting_an_approved_month_is_still_refused(db):
    """The guard that makes one control safe. What a model was told they
    earned is not rewritten underneath them - reopen the month first.
    """
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-09",
        compensation_type="commission",
        commission_rate_bp=800,
    )
    db.flush()
    _approved_month(db, affiliate, "2026-09")

    with pytest.raises(ValueError) as refused:
        set_terms(
            db,
            affiliate,
            start_month="2026-09",
            compensation_type="commission",
            commission_rate_bp=1200,
        )
    assert "approved" in str(refused.value)


def test_starting_before_an_arrangement_in_force_is_still_refused(db):
    """Rewriting is only ever the *same* month. Starting one earlier would
    swallow months nobody looked at.
    """
    affiliate = _affiliate(db)
    set_terms(
        db,
        affiliate,
        start_month="2026-09",
        compensation_type="commission",
        commission_rate_bp=800,
    )
    db.flush()

    with pytest.raises(ValueError) as refused:
        set_terms(
            db,
            affiliate,
            start_month="2026-06",
            compensation_type="commission",
            commission_rate_bp=1200,
        )
    assert "already starts in 2026-09" in str(refused.value)


def test_a_rate_change_cannot_disturb_an_approved_month(db):
    """`assert_correctable` still guards the close, because it runs inside it."""
    affiliate = _affiliate(db)
    terms = set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type="commission",
        commission_rate_bp=800,
    )
    _approved_month(db, affiliate, "2026-09")

    # Starting in September would end the old terms in August and leave the
    # approved month resolving to a rate it was never calculated at.
    with pytest.raises(ValueError) as refused:
        set_terms(
            db,
            affiliate,
            start_month="2026-09",
            compensation_type="commission",
            commission_rate_bp=1200,
        )

    assert "2026-09" in str(refused.value)
    assert terms.end_month is None, "nothing may be left half-changed"
