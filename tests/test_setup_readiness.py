"""Is a model's history set up, month by month?

Rule H06, and the failure `DESIGN_REVIEW.md` records as **V09**: readiness that
reads the *first* terms record answers yes for a woman with four arranged months
and eleven eligible ones.

Every test here is about a month that looks arranged and is not, or one that
looks unarranged and is finished.
"""

import pytest
from sqlalchemy import text

from app.core.passwords import hash_password
from app.models.affiliates import AffiliateProfile
from app.models.compensation import CompensationType
from app.models.identity import UserAccount
from app.services.affiliates import create_affiliate, set_collaboration_start
from app.services.compensation import set_terms
from app.services.setup import (
    NO_TARGET_OUTCOME,
    NO_TERMS,
    TARGET_NOT_VERIFIED,
    setup_readiness,
)

WORKING = "2026-06"
#: Everything before this was settled outside the platform (ADR 0036).
GO_LIVE = "2026-05"


def _historical(month: str) -> bool:
    return month < GO_LIVE


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


def _model(db, *, start=None, name="Nour", email="nour@example.com"):
    """An affiliate with a recorded collaboration start, or deliberately none.

    A09 turns on the difference: a model whose start nobody wrote down still
    has eligible months, derived from her orders.
    """
    affiliate = _affiliate(db, name=name, email=email)
    if start:
        set_collaboration_start(db, affiliate, start)
        db.flush()
    return affiliate


def _order(db, affiliate, order_id, *, month):
    """One attributed order, which is what a derived start month reads."""
    from datetime import datetime, timezone

    from app.models.attributed_orders import AttributedOrder
    from app.models.orders import OrderIndex

    db.add(
        OrderIndex(
            shopify_order_id=order_id,
            order_number=f"#{order_id}",
            placed_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            business_month=month,
            discount_codes=["NOUR10"],
            subtotal_piastres=100_000,
            total_piastres=100_000,
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
            commission_base_piastres=100_000,
            commission_state="earned",
        )
    )
    db.flush()


def _readiness(db, affiliate):
    return setup_readiness(
        db, affiliate, working=WORKING, is_historical=_historical
    )


def _months(result):
    return {row["month"]: row for row in result["months"]}


def _outcome(db, affiliate, month, outcome="met"):
    db.execute(
        text(
            "INSERT INTO monthly_target (affiliate_id, month, recorded_outcome,"
            " created_at, updated_at)"
            " VALUES (:a, :m, :o, now(), now())"
        ),
        {"a": affiliate.id, "m": month, "o": outcome},
    )
    db.flush()


def _verified_target(db, affiliate, month):
    """A live month's target, recorded and confirmed.

    The actuals are not decoration: `monthly_target_cannot_verify_the_unrecorded`
    refuses a verification with nothing behind it, which is the database saying
    the same thing F06 does - a guarantee is released by evidence, not by a
    timestamp.
    """
    db.execute(
        text(
            "INSERT INTO monthly_target (affiliate_id, month, required_videos,"
            " required_stories, actual_videos, actual_stories, verified_at,"
            " created_at, updated_at)"
            " VALUES (:a, :m, 8, 12, 9, 14, now(), now(), now())"
        ),
        {"a": affiliate.id, "m": month},
    )
    db.flush()


# ── V09: every month, not the first one ────────────────────────────────────


def test_arranging_one_month_does_not_make_the_rest_ready(db):
    """The failure this file exists for.

    She started in January and has terms for January alone. A readiness check
    that asks "does she have terms" says yes. Five months of her history are
    unarranged.
    """
    affiliate = _affiliate(db)
    set_collaboration_start(db, affiliate, "2026-01")
    set_terms(
        db,
        affiliate,
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
        start_month="2026-01",
        end_month="2026-01",
    )
    db.flush()

    result = _readiness(db, affiliate)

    assert result["eligible"] == 6
    assert result["ready"] == 1
    assert result["blocking"] == 5
    assert _months(result)["2026-01"]["ready"] is True
    assert _months(result)["2026-02"]["missing"] == [NO_TERMS]


def test_arranging_every_month_clears_it(db):
    affiliate = _affiliate(db)
    set_collaboration_start(db, affiliate, "2026-01")
    set_terms(
        db,
        affiliate,
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
        start_month="2026-01",
    )
    db.flush()

    result = _readiness(db, affiliate)

    assert result["blocking"] == 0
    assert all(row["ready"] for row in result["months"])


# ── Only guarantee depends on targets (F06) ────────────────────────────────


def test_a_commission_month_needs_no_outcome(db):
    """Asking one of these for a target outcome would block payroll on
    evidence that decides nothing."""
    affiliate = _affiliate(db)
    set_collaboration_start(db, affiliate, "2026-02")
    set_terms(
        db,
        affiliate,
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
        start_month="2026-02",
    )
    db.flush()

    assert _readiness(db, affiliate)["blocking"] == 0


def test_a_salary_month_needs_no_outcome_either(db):
    affiliate = _affiliate(db)
    set_collaboration_start(db, affiliate, "2026-02")
    set_terms(
        db,
        affiliate,
        compensation_type=CompensationType.FIXED_PLUS_COMMISSION,
        commission_rate_bp=1000,
        fixed_amount_piastres=500_000,
        start_month="2026-02",
    )
    db.flush()

    assert _readiness(db, affiliate)["blocking"] == 0


def test_a_historical_guarantee_month_needs_its_recorded_outcome(db):
    """ADR 0036: the counts were never kept, so the outcome is the evidence.

    F06 is explicit that unknown qualifying information **blocks** a decision
    rather than being read as a failure - so this is not ready, and it is not
    "missed" either.
    """
    affiliate = _affiliate(db)
    set_collaboration_start(db, affiliate, "2026-02")
    set_terms(
        db,
        affiliate,
        compensation_type=CompensationType.BASE_GUARANTEE,
        commission_rate_bp=1000,
        base_amount_piastres=400_000,
        start_month="2026-02",
        end_month="2026-02",
    )
    db.flush()

    row = _months(_readiness(db, affiliate))["2026-02"]

    assert row["ready"] is False
    assert row["missing"] == [NO_TARGET_OUTCOME]


def test_recording_the_outcome_clears_a_historical_guarantee_month(db):
    affiliate = _affiliate(db)
    set_collaboration_start(db, affiliate, "2026-02")
    set_terms(
        db,
        affiliate,
        compensation_type=CompensationType.BASE_GUARANTEE,
        commission_rate_bp=1000,
        base_amount_piastres=400_000,
        start_month="2026-02",
        end_month="2026-02",
    )
    db.flush()
    _outcome(db, affiliate, "2026-02", "missed")

    row = _months(_readiness(db, affiliate))["2026-02"]

    assert row["ready"] is True
    assert row["missing"] == []


def test_missed_counts_as_recorded(db):
    """A guarantee that did not apply is a decided month, not a stuck one."""
    affiliate = _affiliate(db)
    set_collaboration_start(db, affiliate, "2026-03")
    set_terms(
        db,
        affiliate,
        compensation_type=CompensationType.BASE_GUARANTEE,
        commission_rate_bp=1000,
        base_amount_piastres=400_000,
        start_month="2026-03",
        end_month="2026-03",
    )
    db.flush()
    _outcome(db, affiliate, "2026-03", "missed")

    assert _months(_readiness(db, affiliate))["2026-03"]["ready"] is True


def test_a_live_guarantee_month_wants_verification_not_an_outcome(db):
    """Live months keep the existing gate. Verification is what releases a
    guarantee today, and a second approval would duplicate one fact."""
    affiliate = _affiliate(db)
    set_collaboration_start(db, affiliate, "2026-05")
    set_terms(
        db,
        affiliate,
        compensation_type=CompensationType.BASE_GUARANTEE,
        commission_rate_bp=1000,
        base_amount_piastres=400_000,
        start_month="2026-05",
    )
    db.flush()

    row = _months(_readiness(db, affiliate))["2026-05"]

    assert row["settled_outside"] is False
    assert row["missing"] == [TARGET_NOT_VERIFIED]


def test_a_verified_live_guarantee_month_is_ready(db):
    affiliate = _affiliate(db)
    set_collaboration_start(db, affiliate, "2026-05")
    set_terms(
        db,
        affiliate,
        compensation_type=CompensationType.BASE_GUARANTEE,
        commission_rate_bp=1000,
        base_amount_piastres=400_000,
        start_month="2026-05",
        end_month="2026-05",
    )
    db.flush()
    _verified_target(db, affiliate, "2026-05")

    assert _months(_readiness(db, affiliate))["2026-05"]["ready"] is True


# ── Which months are hers to arrange (H01) ─────────────────────────────────


def test_months_before_she_started_are_not_eligible(db):
    """A model who joined in April has no January to arrange, and offering one
    invites somebody to fill in three months that never existed."""
    affiliate = _affiliate(db)
    set_collaboration_start(db, affiliate, "2026-04")
    db.flush()

    result = _readiness(db, affiliate)

    assert result["start_month"] == "2026-04"
    assert result["eligible"] == 3
    assert [row["month"] for row in result["months"]] == [
        "2026-04",
        "2026-05",
        "2026-06",
    ]


def test_the_payload_says_whether_the_start_was_recorded_or_guessed(db):
    """A screen should be able to tell "she started in June" from "we are
    guessing from her earliest order" (H01)."""
    affiliate = _affiliate(db)

    assert _readiness(db, affiliate)["start_is_recorded"] is False

    set_collaboration_start(db, affiliate, "2026-03")
    db.flush()

    assert _readiness(db, affiliate)["start_is_recorded"] is True


def test_a_model_with_no_start_and_no_orders_has_nothing_to_arrange(db):
    """Not an error, and not zero months of a history she does not have."""
    affiliate = _affiliate(db)

    result = _readiness(db, affiliate)

    assert result["months"] == []
    assert result["eligible"] == 0
    assert result["blocking"] == 0
    assert result["start_month"] is None


# ── An approved month is finished ──────────────────────────────────────────


def test_an_approved_month_is_ready_whatever_else_is_true_of_it(db):
    """Its terms are frozen in the snapshot. Nothing here can ask it to change,
    so reporting it as blocking would be asking for work that must not be done.
    """
    affiliate = _affiliate(db)
    set_collaboration_start(db, affiliate, "2026-06")
    db.flush()
    db.execute(
        text(
            "INSERT INTO payroll_month (affiliate_id, month, calculation_state,"
            " created_at, updated_at)"
            " VALUES (:a, :m, 'approved', now(), now())"
        ),
        {"a": affiliate.id, "m": "2026-06"},
    )
    db.flush()

    row = _months(_readiness(db, affiliate))["2026-06"]

    assert row["has_terms"] is False
    assert row["approved"] is True
    assert row["ready"] is True
    assert row["missing"] == []


# ── Nothing is stored ──────────────────────────────────────────────────────


def test_readiness_reflects_a_later_edit_immediately(db):
    """H06: a first terms record, or a clicked Reviewed button, does not prove
    readiness. Nothing here is written down, so nothing can go stale."""
    affiliate = _affiliate(db)
    set_collaboration_start(db, affiliate, "2026-05")
    set_terms(
        db,
        affiliate,
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
        start_month="2026-05",
    )
    db.flush()
    assert _readiness(db, affiliate)["blocking"] == 0

    # Her start moves back a month. The new month has no terms, and readiness
    # has to notice without anybody re-reviewing anything.
    set_collaboration_start(db, affiliate, "2026-04")
    db.flush()

    result = _readiness(db, affiliate)
    assert result["eligible"] == 3
    assert _months(result)["2026-04"]["missing"] == [NO_TERMS]


# ── A09: readiness across every eligible month, not two dates ─────────────────


def test_a_gap_in_the_middle_is_not_covered_from_the_start(db):
    """A09. The case the two-date comparison could not see.

    Terms from January to March and from June onwards. The earliest terms
    month is January, her start is January, and the old column said *Covered
    from the start* - while April and May could not be calculated at all.
    """
    from app.services.setup import roster_readiness

    affiliate = _model(db, start="2026-01")
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        end_month="2026-03",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    set_terms(
        db,
        affiliate,
        start_month="2026-06",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )

    summary = roster_readiness(
        db, [affiliate], working="2026-09", is_historical=_historical
    )[affiliate.id]

    assert summary["eligible"] == 9
    assert summary["blocking"] == 2, "April and May have no terms"
    assert summary["ready"] == 7
    assert summary["first_gap"] == "2026-04"


def test_a_guaranteed_month_without_an_outcome_blocks_it_too(db):
    """A09, F06. Missing terms is not the only thing that stops a figure."""
    from app.services.setup import roster_readiness

    affiliate = _model(db, start="2026-09")
    set_terms(
        db,
        affiliate,
        start_month="2026-09",
        compensation_type=CompensationType.BASE_GUARANTEE,
        commission_rate_bp=1000,
        base_amount_piastres=300_000,
    )

    summary = roster_readiness(
        db, [affiliate], working="2026-09", is_historical=_historical
    )[affiliate.id]

    assert summary["eligible"] == 1
    assert summary["blocking"] == 1, "the guarantee has no verified target"
    assert summary["first_gap"] == "2026-09"


def test_every_month_covered_is_reported_ready(db):
    """A09. And the happy case still reads as one."""
    from app.services.setup import roster_readiness

    affiliate = _model(db, start="2026-07")
    set_terms(
        db,
        affiliate,
        start_month="2026-07",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )

    summary = roster_readiness(
        db, [affiliate], working="2026-09", is_historical=_historical
    )[affiliate.id]

    assert summary == {
        "eligible": 3,
        "ready": 3,
        "blocking": 0,
        "first_gap": None,
        "start_is_recorded": True,
    }


def test_a_model_with_no_recorded_start_is_judged_on_her_orders(db):
    """A09. "Start month not recorded" was reported as a state of its own.

    It is a real fact and the payload still carries it — but it is not a
    readiness verdict. A model whose start nobody wrote down still has
    eligible months derived from her orders, and she can be perfectly ready
    across all of them.
    """
    from app.services.setup import roster_readiness

    affiliate = _model(db, start=None)
    _order(db, affiliate, "aug", month="2026-08")
    set_terms(
        db,
        affiliate,
        start_month="2026-08",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )

    summary = roster_readiness(
        db, [affiliate], working="2026-09", is_historical=_historical
    )[affiliate.id]

    assert summary["start_is_recorded"] is False
    assert summary["eligible"] == 2
    assert summary["blocking"] == 0, "derived months, and every one of them covered"


def test_the_roster_answers_for_everybody_in_one_pass(db):
    """A09. Set-wise, because this is the screen with all of them on it."""
    from app.services.setup import roster_readiness

    ready = _model(db, start="2026-09", name="Ready", email="ready@example.com")
    set_terms(
        db,
        ready,
        start_month="2026-09",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    blocked = _model(db, start="2026-09", name="Blocked", email="blocked@example.com")

    summary = roster_readiness(
        db, [ready, blocked], working="2026-09", is_historical=_historical
    )

    assert summary[ready.id]["blocking"] == 0
    assert summary[blocked.id]["blocking"] == 1
