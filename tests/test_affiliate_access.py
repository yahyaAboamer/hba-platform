"""The ownership gate.

§6.1 and ADR 0006: a model reaches their data by owning the record, never by
holding a permission. This file proves the gate refuses everything it should,
because it is the only thing standing between one model and another model's
money.

The four refusals are separate tests on purpose. A single "it refuses bad
cases" test passes when three of the four checks are deleted.
"""

import pytest
from sqlalchemy import text

from app.api.deps import current_affiliate
from app.core.passwords import hash_password
from app.models.affiliates import AffiliateStatus
from app.models.identity import UserAccount
from app.services.affiliates import create_affiliate
from fastapi import HTTPException


def _account(db, email: str, status: str = "active") -> UserAccount:
    account = UserAccount(
        email=email,
        password_hash=hash_password("quiet-harbour-lantern"),
        status=status,
        display_name=email.split("@")[0].title(),
    )
    db.add(account)
    db.flush()
    return account


def _model(db, email="nour@example.com", status=AffiliateStatus.ACTIVE):
    account = _account(db, email)
    affiliate = create_affiliate(
        db, user_account_id=account.id, name=email.split("@")[0].title()
    )
    affiliate.status = status
    db.flush()
    return account, affiliate


# ── What it allows ───────────────────────────────────────────────────────────


def test_a_model_reaches_their_own_record(db):
    account, affiliate = _model(db)

    assert current_affiliate(user=account, db=db).id == affiliate.id


def test_a_paused_model_still_reaches_their_record(db):
    """§8: `inactive` is *not earning, may return*.

    Locking them out would make "paused" and "archived" the same thing to the
    only person they affect - and they still needs to see what they were owed
    from before they were paused.
    """
    account, affiliate = _model(db, status=AffiliateStatus.INACTIVE)

    assert current_affiliate(user=account, db=db).id == affiliate.id


def test_a_pending_model_reaches_their_record(db):
    """They have applied and is waiting. They must be able to sign in and be told
    that, rather than be refused as though they were nobody.
    """
    account, affiliate = _model(db, status=AffiliateStatus.PENDING)

    assert current_affiliate(user=account, db=db).id == affiliate.id


# ── What it refuses ──────────────────────────────────────────────────────────


def test_a_staff_account_is_refused(db):
    """An administrator is not an affiliate and must not become one by calling
    a model route. This is the mixing the two-gate design exists to prevent.
    """
    account = _account(db, "owner@example.com")

    with pytest.raises(HTTPException) as refused:
        current_affiliate(user=account, db=db)
    assert refused.value.status_code == 403


def test_an_archived_model_is_refused(db):
    """History resolves; the person does not sign in."""
    account, _ = _model(db, status=AffiliateStatus.ARCHIVED)

    with pytest.raises(HTTPException) as refused:
        current_affiliate(user=account, db=db)
    assert refused.value.status_code == 403


def test_an_invited_account_that_never_applied_is_refused(db):
    """The account exists because an invitation was accepted; no profile does.
    Fails closed.
    """
    account = _account(db, "invited@example.com")

    with pytest.raises(HTTPException) as refused:
        current_affiliate(user=account, db=db)
    assert refused.value.status_code == 403


def test_every_refusal_is_403_and_never_404(db):
    """Whether an affiliate record exists for some account is not something an
    unauthorised caller should establish by watching status codes.
    """
    staff = _account(db, "staff@example.com")
    archived, _ = _model(db, "gone@example.com", status=AffiliateStatus.ARCHIVED)

    codes = set()
    for account in (staff, archived):
        with pytest.raises(HTTPException) as refused:
            current_affiliate(user=account, db=db)
        codes.add(refused.value.status_code)

    assert codes == {403}


def test_one_model_cannot_reach_another(db):
    """The whole point, stated as a test rather than left implied."""
    nour_account, nour = _model(db, "nour@example.com")
    _, sara = _model(db, "sara@example.com")

    resolved = current_affiliate(user=nour_account, db=db)

    assert resolved.id == nour.id
    assert resolved.id != sara.id
