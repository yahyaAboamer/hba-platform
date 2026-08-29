"""What a model was asked to produce, what they produced, and who confirmed it.

Phase 5 Tasks 1-3. §15, and for a `base_guarantee` model this is the input that
decides their pay.

The distinction the whole design turns on (§11.3):

    no target recorded      blocks the month - nobody knows what they did
    recorded, missed        pays their commission, month approves
    recorded, achieved      unlocks the guarantee - **once verified**

"Not achieved" and "not yet recorded" are different answers with different
consequences, which is why `is_achieved` returns three things and not two.
"""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.passwords import hash_password
from app.models.affiliates import AccountKind
from app.models.audit import AuditEvent
from app.models.identity import UserAccount
from app.models.targets import MonthlyTarget
from app.services.affiliates import create_affiliate
from app.services.compensation import set_terms
from app.services.targets import (
    get_target,
    record_actuals,
    set_requirements,
    targets_for,
    unverify,
    verify,
)

MONTH = "2026-04"


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


def _target(db, affiliate, videos=8, stories=5, month=MONTH):
    return set_requirements(
        db, affiliate, month, videos=videos, stories=stories
    )


def _audits(db, action):
    """Audit events for one action.

    The flush matters: `record_audit` deliberately only *stages* the event for
    the caller to commit with the change it describes, and this session runs
    with `autoflush=False`. Without it a test reads everything except the last
    thing that happened - which is exactly the event it usually cares about.
    """
    db.flush()
    return list(
        db.scalars(select(AuditEvent).where(AuditEvent.action == action))
    )


# ── Three states, not two ──────────────────────────────────────────────────────


def test_a_target_with_nothing_recorded_is_neither_achieved_nor_missed(db):
    """The `None` is the point. "Not achieved" pays their commission and approves
    the month; "not yet recorded" blocks it. A boolean cannot express both, and
    collapsing them would silently approve a month nobody had looked at.
    """
    target = _target(db, _affiliate(db))

    assert target.is_recorded is False
    assert target.is_achieved is None


def test_meeting_every_requirement_is_achieved(db):
    target = _target(db, _affiliate(db), videos=8, stories=5)
    record_actuals(db, target, videos=8, stories=5)

    assert target.is_achieved is True


def test_exceeding_the_requirement_is_achieved(db):
    target = _target(db, _affiliate(db), videos=8, stories=5)
    record_actuals(db, target, videos=12, stories=9)

    assert target.is_achieved is True


def test_eight_videos_and_four_of_five_stories_is_not_achieved(db):
    """Confirmed with HBA on 26 August 2026. Every requirement, not most of
    them - §9.5 has no fractional guarantee. They are paid their commission,
    promptly, and the guarantee does not apply.
    """
    target = _target(db, _affiliate(db), videos=8, stories=5)
    record_actuals(db, target, videos=8, stories=4)

    assert target.is_achieved is False


def test_nothing_asked_for_is_achieved_by_nothing_produced(db):
    """A requirement of zero is a real answer meaning nothing was asked of them
    this month - distinct from nobody having asked, which is what a missing row
    means.
    """
    target = _target(db, _affiliate(db), videos=0, stories=0)
    record_actuals(db, target, videos=0, stories=0)

    assert target.is_achieved is True


# ── One row per model per month ────────────────────────────────────────────────


def test_a_second_target_for_the_same_month_is_refused(db):
    """§17. Two rows would be two answers to "did they achieve August?", and
    whichever the query read first would decide a payment.
    """
    affiliate = _affiliate(db)
    _target(db, affiliate)

    db.add(
        MonthlyTarget(
            affiliate_id=affiliate.id,
            month=MONTH,
            required_videos=1,
            required_stories=1,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_setting_requirements_twice_updates_the_same_row(db):
    affiliate = _affiliate(db)
    _target(db, affiliate, videos=8, stories=5)
    _target(db, affiliate, videos=10, stories=6)

    target = get_target(db, affiliate, MONTH)
    assert (target.required_videos, target.required_stories) == (10, 6)


def test_changing_what_was_asked_does_not_un_know_what_they_did(db):
    affiliate = _affiliate(db)
    target = _target(db, affiliate, videos=8, stories=5)
    record_actuals(db, target, videos=9, stories=6)

    _target(db, affiliate, videos=12, stories=9)

    target = get_target(db, affiliate, MONTH)
    assert (target.actual_videos, target.actual_stories) == (9, 6)
    assert target.is_achieved is False, "the bar moved, and the model is now under it"


def test_each_month_stands_alone(db):
    affiliate = _affiliate(db)
    _target(db, affiliate, videos=8, stories=5, month="2026-04")
    _target(db, affiliate, videos=2, stories=1, month="2026-05")

    assert get_target(db, affiliate, "2026-04").required_videos == 8
    assert get_target(db, affiliate, "2026-05").required_videos == 2


# ── Recording ──────────────────────────────────────────────────────────────────


def test_both_numbers_are_recorded_together(db):
    """A half-recorded month is not a state anybody has a rule for: "eight
    videos and an unknown number of stories" cannot answer whether they
    achieved.
    """
    affiliate = _affiliate(db)
    _target(db, affiliate)
    db.commit()

    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "UPDATE monthly_target SET actual_videos = 8 "
                "WHERE affiliate_id = :a"
            ),
            {"a": affiliate.id},
        )
        db.flush()
    db.rollback()


@pytest.mark.parametrize("videos,stories", [(-1, 0), (0, -1)])
def test_a_negative_count_is_refused(db, videos, stories):
    target = _target(db, _affiliate(db))

    with pytest.raises(ValueError):
        record_actuals(db, target, videos=videos, stories=stories)


def test_a_negative_requirement_is_refused(db):
    with pytest.raises(ValueError):
        _target(db, _affiliate(db), videos=-1)


def test_recording_says_who_and_when(db):
    affiliate = _affiliate(db)
    target = _target(db, affiliate)

    record_actuals(db, target, videos=8, stories=5, actor_id=affiliate.user_account_id)

    assert target.recorded_by == affiliate.user_account_id
    assert target.recorded_at is not None


# ── Verification ───────────────────────────────────────────────────────────────


def test_verifying_records_who_and_when(db):
    """"Verified, by whom, eight months ago" is a different answer from
    "verified", and only one of them can be audited.
    """
    affiliate = _affiliate(db)
    target = _target(db, affiliate)
    record_actuals(db, target, videos=8, stories=5)

    verify(db, target, actor_id=affiliate.user_account_id)

    assert target.is_verified is True
    assert target.verified_by == affiliate.user_account_id
    assert target.verified_at is not None


def test_verifying_nothing_is_refused(db):
    """Confirming numbers nobody has entered would unlock a base guarantee on
    an empty month.
    """
    target = _target(db, _affiliate(db))

    with pytest.raises(ValueError, match="nothing to verify"):
        verify(db, target)


def test_the_database_refuses_it_too(db):
    """The service message is for a person; the constraint is what makes it
    true.
    """
    affiliate = _affiliate(db)
    _target(db, affiliate)
    db.commit()

    with pytest.raises(IntegrityError):
        db.execute(
            text("UPDATE monthly_target SET verified_at = now() WHERE affiliate_id = :a"),
            {"a": affiliate.id},
        )
        db.flush()
    db.rollback()


def test_a_missed_target_can_be_verified(db):
    """Verification confirms the **numbers**, not the outcome. A verified miss
    is a confirmed miss: they are paid their commission, the month approves, and
    the guarantee simply does not apply. Conflating the two would block every
    model who had a quiet month.
    """
    affiliate = _affiliate(db)
    target = _target(db, affiliate, videos=8, stories=5)
    record_actuals(db, target, videos=3, stories=1)

    verify(db, target)

    assert target.is_verified is True
    assert target.is_achieved is False


def test_re_recording_clears_the_verification(db):
    """The confirmation was of the old numbers. Leaving it would let a
    correction inherit somebody else's approval and unlock a guarantee nobody
    agreed to.
    """
    affiliate = _affiliate(db)
    target = _target(db, affiliate)
    record_actuals(db, target, videos=3, stories=1)
    verify(db, target)

    record_actuals(db, target, videos=8, stories=5)

    assert target.is_verified is False
    assert target.is_achieved is True, "achieved, but now nobody has confirmed it"


def test_un_verifying_requires_a_written_reason(db):
    """It is the only way back from a mistaken verification, and a mistaken
    verification silently pays a guarantee.
    """
    affiliate = _affiliate(db)
    target = _target(db, affiliate)
    record_actuals(db, target, videos=8, stories=5)
    verify(db, target)

    with pytest.raises(ValueError, match="written reason"):
        unverify(db, target, reason="   ")

    unverify(db, target, reason="Sara counted last month's posts by mistake")
    assert target.is_verified is False


# ── The audit trail ────────────────────────────────────────────────────────────


def test_every_change_is_audited(db):
    """A target that decides a payment needs the same trail as the payment."""
    affiliate = _affiliate(db)
    target = _target(db, affiliate)
    record_actuals(db, target, videos=8, stories=5)
    verify(db, target)
    unverify(db, target, reason="counted the wrong month")

    assert len(_audits(db, "target.requirements_set")) == 1
    assert len(_audits(db, "target.actuals_recorded")) == 1
    assert len(_audits(db, "target.verified")) == 1
    assert len(_audits(db, "target.unverified")) == 1


def test_un_verifying_records_the_reason(db):
    affiliate = _affiliate(db)
    target = _target(db, affiliate)
    record_actuals(db, target, videos=8, stories=5)
    verify(db, target)
    unverify(db, target, reason="Sara counted last month's posts")

    assert "last month" in _audits(db, "target.unverified")[0].reason


def test_a_correction_records_what_it_replaced(db):
    """What it changed from matters as much as what it changed to."""
    affiliate = _affiliate(db)
    target = _target(db, affiliate)
    record_actuals(db, target, videos=3, stories=1)
    record_actuals(db, target, videos=8, stories=5)

    latest = _audits(db, "target.actuals_recorded")[-1]
    assert latest.before_json["actual_videos"] == 3
    assert latest.after_json["actual_videos"] == 8


def test_a_cleared_verification_is_visible_in_the_audit(db):
    affiliate = _affiliate(db)
    target = _target(db, affiliate)
    record_actuals(db, target, videos=3, stories=1)
    verify(db, target)
    record_actuals(db, target, videos=8, stories=5)

    latest = _audits(db, "target.actuals_recorded")[-1]
    assert latest.after_json["verification_cleared"] is True


# ── Reading a whole month ──────────────────────────────────────────────────────


def test_a_month_comes_back_keyed_by_affiliate(db):
    """One query for the whole grid. Twenty lookups would work and would also
    be twenty round trips on a screen somebody opens every month.
    """
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    _target(db, nour, videos=8, stories=5)
    _target(db, sara, videos=2, stories=2)

    found = targets_for(db, MONTH)

    assert set(found) == {nour.id, sara.id}
    assert found[nour.id].required_videos == 8


def test_another_months_targets_are_not_returned(db):
    affiliate = _affiliate(db)
    _target(db, affiliate, month="2026-05")

    assert targets_for(db, MONTH) == {}


def test_an_affiliate_with_no_target_is_simply_absent(db):
    """The grid fills the gap in Task 5. Here, absent means absent - which is
    the case that blocks their month later.
    """
    _affiliate(db)

    assert targets_for(db, MONTH) == {}


def test_a_target_dies_with_its_affiliate(db):
    affiliate = _affiliate(db)
    _target(db, affiliate)
    db.commit()

    db.execute(
        text("DELETE FROM affiliate_profile WHERE id = :i"), {"i": affiliate.id}
    )
    db.commit()

    assert targets_for(db, MONTH) == {}


def test_a_month_that_is_not_a_month_is_refused(db):
    affiliate = _affiliate(db)

    with pytest.raises(ValueError):
        set_requirements(db, affiliate, "2026-13", videos=1, stories=1)


def test_the_grid_says_whose_pay_a_target_decides(db):
    """§15. A target decides money only for a base guarantee.

    A screen that cannot tell the difference marks every empty row as urgent,
    and §11.3 blocks payroll on exactly one of these kinds. Warning about the
    other three is a false alarm on every model, every month.
    """
    from app.api.targets import _determines_pay
    from app.models.compensation import CompensationType

    guaranteed = _affiliate(db, "Sara")
    set_terms(
        db,
        guaranteed,
        start_month="2026-01",
        compensation_type=CompensationType.BASE_GUARANTEE,
        commission_rate_bp=1000,
        base_amount_piastres=800_000,
    )
    on_commission = _affiliate(db, "Nour")
    set_terms(
        db,
        on_commission,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    db.flush()

    assert _determines_pay(db, guaranteed, MONTH) is True
    assert _determines_pay(db, on_commission, MONTH) is False


def test_a_model_with_no_terms_has_no_target_deciding_anything(db):
    """No arrangement means nothing is calculable from their target either."""
    from app.api.targets import _determines_pay

    nobody = _affiliate(db, "Habiba")
    db.flush()

    assert _determines_pay(db, nobody, MONTH) is False
