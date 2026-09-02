"""Getting back into an account whose password is lost.

Before this there was no way back at all: no reset route, and re-inviting
refused because `create_invitation` turns away an address that already holds
an account. A model who forgot their password could only be helped by editing
the database by hand.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.businesstime import utcnow
from app.core.passwords import hash_password, verify_password
from app.models.identity import PasswordReset, UserAccount
from app.services.password_resets import (
    complete_reset,
    preview_reset,
    request_reset,
)

PASSWORD = "quiet-harbour-lantern"
NEW_PASSWORD = "marble-anchor-drift-91"


def _account(db, email="nour@example.com", status="active"):
    account = UserAccount(
        email=email,
        password_hash=hash_password(PASSWORD),
        status=status,
        display_name="Nour Mahmoud",
    )
    db.add(account)
    db.flush()
    return account


# ── Asking ──────────────────────────────────────────────────────────────────


def test_a_real_address_gets_a_token(db):
    account = _account(db)
    started = request_reset(db, "nour@example.com")
    assert started is not None
    assert started[1].id == account.id


def test_an_unknown_address_gets_nothing_to_send(db):
    """`None` means there is nobody to email. The endpoint above answers 202
    either way - see the module docstring on why."""
    assert request_reset(db, "stranger@example.com") is None


def test_the_address_is_matched_regardless_of_case(db):
    _account(db, "Nour@Example.COM")
    assert request_reset(db, "nour@example.com") is not None


def test_a_suspended_account_cannot_reset_its_way_back_in(db):
    """Suspension is a decision somebody made. Letting the suspended person
    reset a password would undo it silently.
    """
    _account(db, status="suspended")
    assert request_reset(db, "nour@example.com") is None


def test_asking_again_kills_the_earlier_link(db):
    """Somebody who presses the button twice - because the first mail was
    slow - would otherwise hold two working links, and the older one is the
    one likelier to be sitting somewhere else.
    """
    _account(db)
    first, _ = request_reset(db, "nour@example.com")
    db.flush()
    second, _ = request_reset(db, "nour@example.com")
    db.flush()

    with pytest.raises(ValueError):
        preview_reset(db, first)
    assert preview_reset(db, second).email == "nour@example.com"


def test_only_the_hash_of_the_token_is_stored(db):
    """The raw token is a credential until it is used."""
    _account(db)
    token, _ = request_reset(db, "nour@example.com")
    db.flush()

    rows = db.scalars(select(PasswordReset)).all()
    assert rows
    assert all(token not in row.token_hash for row in rows)


# ── Opening the link ────────────────────────────────────────────────────────


def test_a_live_link_names_the_account(db):
    _account(db)
    token, _ = request_reset(db, "nour@example.com")
    db.flush()

    assert preview_reset(db, token).email == "nour@example.com"


def test_previewing_does_not_spend_it(db):
    _account(db)
    token, _ = request_reset(db, "nour@example.com")
    db.flush()

    preview_reset(db, token)
    assert complete_reset(db, token, NEW_PASSWORD) is not None


def test_an_expired_link_is_refused(db):
    _account(db)
    token, _ = request_reset(db, "nour@example.com")
    db.flush()
    row = db.scalars(select(PasswordReset)).one()
    row.expires_at = utcnow() - timedelta(minutes=1)
    db.flush()

    with pytest.raises(ValueError):
        preview_reset(db, token)


def test_a_made_up_token_is_refused(db):
    with pytest.raises(ValueError):
        preview_reset(db, "not-a-real-token")


# ── Setting the new password ────────────────────────────────────────────────


def test_the_new_password_replaces_the_old_one(db):
    account = _account(db)
    token, _ = request_reset(db, "nour@example.com")
    db.flush()

    complete_reset(db, token, NEW_PASSWORD)
    db.flush()

    assert verify_password(NEW_PASSWORD, account.password_hash)
    assert not verify_password(PASSWORD, account.password_hash)


def test_the_link_works_only_once(db):
    _account(db)
    token, _ = request_reset(db, "nour@example.com")
    db.flush()
    complete_reset(db, token, NEW_PASSWORD)
    db.flush()

    with pytest.raises(ValueError):
        complete_reset(db, token, "another-quiet-harbour")


def test_a_refused_password_does_not_burn_the_link(db):
    """The same courtesy `accept_invitation` gives: a rejected password is a
    mistake somebody can correct, not a reason to send them a new email.
    """
    _account(db)
    token, _ = request_reset(db, "nour@example.com")
    db.flush()

    with pytest.raises(ValueError):
        complete_reset(db, token, "password123456")

    assert preview_reset(db, token).email == "nour@example.com"


def test_the_new_password_cannot_be_their_own_address(db):
    _account(db)
    token, _ = request_reset(db, "nour@example.com")
    db.flush()

    with pytest.raises(ValueError) as refused:
        complete_reset(db, token, "nour@example.com!!")
    assert "your own name or email" in str(refused.value)


def test_the_quality_rules_apply_here_too(db):
    """A reset is not a back door around the rules the accept screen enforces."""
    _account(db)
    token, _ = request_reset(db, "nour@example.com")
    db.flush()

    with pytest.raises(ValueError):
        complete_reset(db, token, "123456789012")
