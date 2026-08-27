"""Staff invitations.

Spec section 6.2. There is no public staff signup. An administrator invites a
person and chooses their role; the invitee sets their own password, so nobody
ever sets or sees another person's credentials.
"""

from datetime import timedelta

import pytest

from app.core.businesstime import utcnow
from app.core.passwords import hash_password, verify_password
from app.core.permissions import VALID_ROLES
from app.models.identity import UserAccount
from app.services.invitations import accept_invitation, create_invitation

PASSWORD = "a-long-enough-password"


def _admin(db, email="admin@example.com"):
    user = UserAccount(
        email=email, password_hash=hash_password(PASSWORD), status="active"
    )
    db.add(user)
    db.flush()
    return user


# ── Creating ───────────────────────────────────────────────────────────────────


def test_invitation_produces_a_token_and_row(db):
    token, invitation = create_invitation(db, "new@example.com", "content_manager", None)
    db.flush()
    assert token
    assert invitation.accepted_at is None
    assert invitation.id is not None


def test_the_raw_token_is_never_stored(db):
    """An invitation link is a credential until it is used."""
    token, invitation = create_invitation(db, "new@example.com", "content_manager", None)
    db.flush()
    assert invitation.token_hash != token
    assert len(invitation.token_hash) == 64
    assert token not in invitation.token_hash


def test_email_is_normalised(db):
    _, invitation = create_invitation(db, "  MiXeD@Example.COM  ", "admin", None)
    db.flush()
    assert invitation.email == "mixed@example.com"


def test_invalid_role_is_refused(db):
    with pytest.raises(ValueError):
        create_invitation(db, "new@example.com", "wizard", None)


def test_every_code_defined_role_can_be_invited(db):
    for index, role in enumerate(sorted(VALID_ROLES)):
        token, _ = create_invitation(db, f"role{index}@example.com", role, None)
        assert token


def test_the_inviter_is_recorded(db):
    admin = _admin(db)
    _, invitation = create_invitation(db, "new@example.com", "admin", admin.id)
    db.flush()
    assert invitation.invited_by == admin.id


def test_invitations_expire(db):
    _, invitation = create_invitation(db, "new@example.com", "admin", None, valid_hours=1)
    db.flush()
    expected = utcnow() + timedelta(hours=1)
    assert abs((invitation.expires_at - expected).total_seconds()) < 60


def test_two_invitations_get_different_tokens(db):
    first, _ = create_invitation(db, "a@example.com", "admin", None)
    second, _ = create_invitation(db, "b@example.com", "admin", None)
    assert first != second


# ── Accepting ──────────────────────────────────────────────────────────────────


def test_accepting_creates_an_active_user_with_the_invited_role(db):
    token, _ = create_invitation(db, "sara@example.com", "content_manager", None)
    db.flush()
    user = accept_invitation(db, token, PASSWORD, "Sara")
    db.flush()
    assert isinstance(user, UserAccount)
    assert user.status == "active"
    assert user.email == "sara@example.com"
    assert user.display_name == "Sara"
    assert verify_password(PASSWORD, user.password_hash)
    assert [row.role for row in user.roles] == ["content_manager"]


def test_the_invitee_chooses_their_own_password(db):
    """Nobody ever sets or sees another person's credentials."""
    token, _ = create_invitation(db, "own@example.com", "admin", None)
    db.flush()
    user = accept_invitation(db, token, "the-password-i-chose", "Owner")
    db.flush()
    assert verify_password("the-password-i-chose", user.password_hash)


def test_an_invitation_can_only_be_accepted_once(db):
    token, _ = create_invitation(db, "once@example.com", "admin", None)
    db.flush()
    accept_invitation(db, token, PASSWORD, "Once")
    db.flush()
    with pytest.raises(ValueError):
        accept_invitation(db, token, "another-long-password", "Again")


def test_accepting_marks_the_invitation_used(db):
    token, invitation = create_invitation(db, "used@example.com", "admin", None)
    db.flush()
    accept_invitation(db, token, PASSWORD, "Used")
    db.flush()
    assert invitation.accepted_at is not None


def test_expired_invitation_is_refused(db):
    token, invitation = create_invitation(db, "old@example.com", "admin", None)
    invitation.expires_at = utcnow() - timedelta(minutes=1)
    db.flush()
    with pytest.raises(ValueError):
        accept_invitation(db, token, PASSWORD, "Old")


def test_unknown_token_is_refused(db):
    with pytest.raises(ValueError):
        accept_invitation(db, "not-a-real-token", PASSWORD, "Nobody")


def test_empty_token_is_refused(db):
    with pytest.raises(ValueError):
        accept_invitation(db, "", PASSWORD, "Nobody")


def test_short_password_is_refused(db):
    token, _ = create_invitation(db, "short@example.com", "admin", None)
    db.flush()
    with pytest.raises(ValueError):
        accept_invitation(db, token, "short", "Short")


def test_a_refused_acceptance_does_not_consume_the_invitation(db):
    """A rejected weak password must not burn the link.

    The password is validated before the invitation is marked used, so the
    invitee can simply try again with a stronger one.
    """
    token, invitation = create_invitation(db, "retry@example.com", "admin", None)
    db.flush()

    with pytest.raises(ValueError):
        accept_invitation(db, token, "short", "Retry")
    assert invitation.accepted_at is None

    # The same link still works.
    user = accept_invitation(db, token, PASSWORD, "Retry")
    db.flush()
    assert user.status == "active"
    assert invitation.accepted_at is not None


def test_inviting_an_email_that_already_has_an_account_is_refused(db):
    """Caught when the invitation is created, so the person inviting finds out
    while they can still act on it rather than after sending a dead link."""
    _admin(db, "taken@example.com")
    with pytest.raises(ValueError, match="already exists"):
        create_invitation(db, "taken@example.com", "admin", None)


def test_accepting_for_an_email_that_already_exists_is_refused(db):
    """The same collision, arriving the other way round.

    The account is created **after** the invitation was sent, so the check at
    creation time could not have seen it. Both guards are needed: this one
    covers the window between sending a link and somebody using it, which is
    up to 72 hours wide.
    """
    token, _ = create_invitation(db, "taken@example.com", "admin", None)
    db.flush()
    _admin(db, "taken@example.com")
    db.flush()

    with pytest.raises(ValueError):
        accept_invitation(db, token, PASSWORD, "Taken")


def test_display_name_is_optional(db):
    token, _ = create_invitation(db, "noname@example.com", "admin", None)
    db.flush()
    user = accept_invitation(db, token, PASSWORD, "")
    db.flush()
    assert user.display_name is None
