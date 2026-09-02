"""A model applying for themselves.

§13 step 2, and §6.5's boundary: the application collects identity and
destination, and cannot express a single figure that decides what they are paid.
"""

import pytest
from sqlalchemy import select

from app.core.passwords import hash_password
from app.models.affiliates import AffiliateProfile, AffiliateStatus
from app.models.codes import DiscountCodePeriod
from app.models.identity import UserAccount
from app.models.payouts import PayoutDestination, PayoutMethod
from app.services.applications import submit_application

INSTAPAY = {
    "instapay_address_url": "https://ipn.eg/S/nour.mahmoud/instapay/8Xk2Qp",
    "instapay_phone": "01001234567",
}


def _account(db, email="nour@example.com") -> UserAccount:
    account = UserAccount(
        email=email,
        password_hash=hash_password("a-long-enough-password"),
        status="active",
        display_name="Nour",
    )
    db.add(account)
    db.flush()
    return account


def _apply(db, account, **overrides):
    body = {
        "name": "Nour Mahmoud",
        "phone": "010 1234 5678",
        "code": "nour10",
        "payout_method": PayoutMethod.INSTAPAY,
        "payout_fields": dict(INSTAPAY),
    }
    body.update(overrides)
    return submit_application(db, account, **body)


# ── What it creates ──────────────────────────────────────────────────────────


def test_applying_creates_a_pending_profile(db):
    """Pending, never active. Approval is a deliberate later act by somebody
    who has verified their code (§10.4).
    """
    account = _account(db)

    affiliate = _apply(db, account)
    db.flush()

    assert affiliate.status == AffiliateStatus.PENDING
    assert affiliate.user_account_id == account.id
    assert affiliate.name == "Nour Mahmoud"


def test_the_proposed_code_is_registered_but_not_verified(db):
    """§10.4's gate is `set_status`, and registering here does not open it.

    Verifying on application would let a model approve their own code by typing
    it, which is the exact failure the gate exists for.
    """
    account = _account(db)

    affiliate = _apply(db, account)
    db.flush()

    period = db.scalar(
        select(DiscountCodePeriod).where(
            DiscountCodePeriod.affiliate_id == affiliate.id
        )
    )
    assert period.code == "NOUR10", "stored in canonical form"
    assert period.shopify_verified_at is None


def test_the_payout_destination_is_stored(db):
    account = _account(db)

    affiliate = _apply(db, account)
    db.flush()

    destination = db.scalar(
        select(PayoutDestination).where(
            PayoutDestination.affiliate_id == affiliate.id
        )
    )
    assert destination.method == PayoutMethod.INSTAPAY
    assert destination.instapay_address_url == INSTAPAY["instapay_address_url"]
    assert destination.instapay_phone == INSTAPAY["instapay_phone"]


def test_an_application_is_audited(db):
    from sqlalchemy import text

    account = _account(db)
    _apply(db, account)
    db.flush()

    actions = [
        row[0]
        for row in db.execute(text("SELECT action FROM audit_event ORDER BY id"))
    ]
    assert "affiliate.applied" in actions


def test_the_payout_details_never_reach_the_audit_log_unmasked(db):
    """`record_audit` masks on the way in, and the table is append-only - so
    this is the only moment it could ever be got wrong.
    """
    import json

    from sqlalchemy import text

    account = _account(db)
    _apply(db, account)
    db.flush()

    rows = db.execute(
        text("SELECT before_json, after_json FROM audit_event")
    ).all()
    written = json.dumps([list(row) for row in rows], default=str)

    assert INSTAPAY["instapay_address_url"] not in written


# ── What it refuses ──────────────────────────────────────────────────────────


def test_applying_twice_is_refused(db):
    """A double-tapped submit would otherwise produce two pending profiles and
    two code registrations for one person, one of which quietly wins.
    """
    account = _account(db)
    _apply(db, account)
    db.flush()

    with pytest.raises(ValueError, match="already applied"):
        _apply(db, account)


def test_a_missing_instapay_number_is_refused(db):
    """ADR 0028: the address feeds the deep link, the number is what somebody
    types when the link does not open. Both, or they cannot reliably be paid.
    """
    account = _account(db)

    with pytest.raises(ValueError, match="instapay phone"):
        _apply(
            db,
            account,
            payout_fields={"instapay_address_url": INSTAPAY["instapay_address_url"]},
        )


def test_a_bank_application_needs_every_bank_field(db):
    account = _account(db)

    with pytest.raises(ValueError, match="bank account number"):
        _apply(
            db,
            account,
            payout_method=PayoutMethod.BANK,
            payout_fields={"bank_name": "CIB", "bank_account_holder": "Nour"},
        )


def test_a_blank_name_is_refused(db):
    account = _account(db)

    with pytest.raises(ValueError, match="your name"):
        _apply(db, account, name="   ")


def test_an_empty_code_is_refused_before_anything_is_written(db):
    """Nothing half-created: the profile must not survive a rejected code."""
    account = _account(db)

    with pytest.raises(ValueError):
        _apply(db, account, code="")

    db.rollback()
    assert db.scalar(
        select(AffiliateProfile).where(
            AffiliateProfile.user_account_id == account.id
        )
    ) is None


def test_an_unknown_payout_method_is_refused(db):
    account = _account(db)

    with pytest.raises(ValueError, match="Unknown payout method"):
        _apply(db, account, payout_method="cash_in_hand")


# ── §6.5, as a boundary rather than an intention ─────────────────────────────


def test_the_application_cannot_express_what_they_are_paid(db):
    """A form that merely omits a field is not a control. This asserts the
    service has no parameter for one, so no client can send one.
    """
    import inspect

    signature = inspect.signature(submit_application)
    forbidden = {
        "compensation_type",
        "commission_rate_bp",
        "fixed_amount_piastres",
        "base_amount_piastres",
        "required_videos",
        "required_stories",
        "status",
    }

    assert not forbidden & set(signature.parameters)


def test_applying_never_sets_compensation_terms(db):
    """The profile exists and is worth nothing until a maintainer says so."""
    from app.services.compensation import terms_for

    account = _account(db)
    affiliate = _apply(db, account)
    db.flush()

    assert terms_for(db, affiliate, "2026-08") is None


# ── The name a model gives ──────────────────────────────────────────────────
#
# One name is not enough to tell three models apart on a payroll screen, and
# the roster is the maintainer's, not the model's. Asked for during the flow-1
# walkthrough after "Ahmed" and "Ahmed Mohamed" turned out to be the same
# person seen from two sides.


def test_a_single_name_is_refused(db):
    account = _account(db)
    with pytest.raises(ValueError) as refused:
        _apply(db, account, name="Nour")
    assert "family name" in str(refused.value)


def test_a_first_and_family_name_is_enough(db):
    account = _account(db)
    assert _apply(db, account, name="Nour Mahmoud").name == "Nour Mahmoud"


def test_more_than_two_parts_is_not_a_mistake(db):
    """The rule is *at least* two, deliberately. Capping it would reject
    "Mohamed Abdel Rahman", which is an ordinary name rather than an error -
    and refusing somebody's real name is a worse failure than the one this
    rule exists to prevent.
    """
    account = _account(db)
    assert (
        _apply(db, account, name="Mohamed Abdel Rahman").name
        == "Mohamed Abdel Rahman"
    )


def test_spacing_does_not_decide_whether_a_name_is_accepted(db):
    """Somebody typing on a phone produces double spaces and trailing ones.
    Counting raw gaps would accept "Nour " on one device and refuse it on
    another, which is the kind of rule that looks broken.
    """
    account = _account(db)
    assert _apply(db, account, name="  Nour   Mahmoud  ").name == "Nour Mahmoud"


def test_a_padded_single_name_is_still_a_single_name(db):
    account = _account(db)
    with pytest.raises(ValueError):
        _apply(db, account, name="   Nour   ")


def test_the_account_takes_the_name_the_model_gave(db):
    """One name, in both places. The account carried what was typed on the
    first screen and the profile what was typed on the second, so a model saw
    one name in their portal while the maintainer saw another in admin.
    """
    account = _account(db)
    account.display_name = "whatever was typed first"

    _apply(db, account, name="Nour Mahmoud")
    db.flush()

    assert account.display_name == "Nour Mahmoud"
