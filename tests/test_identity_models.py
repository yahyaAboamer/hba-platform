"""Identity schema.

Spec section 6.1. These tests exercise the database constraints directly,
because the spec requires invariants to be enforced by the database and not
only by application code (section 4.8). Every assertion here would still hold
if someone wrote to the tables with raw SQL.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.businesstime import utcnow
from app.core.permissions import VALID_ROLES
from app.models.identity import AuthSession, Invitation, RoleAssignment, UserAccount


def _user(db, email="user@example.com", status="active"):
    user = UserAccount(email=email, password_hash="x", status=status)
    db.add(user)
    db.flush()
    return user


# ── user_account ───────────────────────────────────────────────────────────────


def test_user_account_can_be_created(db):
    user = _user(db, "owner@example.com")
    assert user.id is not None
    assert user.created_at is not None


def test_status_defaults_to_invited(db):
    user = UserAccount(email="new@example.com", password_hash="x")
    db.add(user)
    db.flush()
    db.refresh(user)
    assert user.status == "invited"


def test_email_is_unique_case_insensitively(db):
    """Two accounts differing only by case would be an account-takeover route."""
    _user(db, "owner@example.com")
    db.add(UserAccount(email="OWNER@EXAMPLE.COM", password_hash="y", status="active"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_invalid_status_is_rejected_by_the_database(db):
    db.add(UserAccount(email="bad@example.com", password_hash="x", status="wizard"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_password_hash_is_required(db):
    db.add(UserAccount(email="nohash@example.com", status="active"))
    with pytest.raises(IntegrityError):
        db.flush()


# ── role_assignment ────────────────────────────────────────────────────────────


def test_role_assignment_links_to_a_user(db):
    user = _user(db, "staff@example.com")
    db.add(RoleAssignment(user_account_id=user.id, role="content_manager"))
    db.flush()
    assert db.query(RoleAssignment).filter_by(user_account_id=user.id).count() == 1


def test_invalid_role_is_rejected_by_the_database(db):
    user = _user(db, "staff2@example.com")
    db.add(RoleAssignment(user_account_id=user.id, role="wizard"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_every_code_defined_role_is_accepted_by_the_database(db):
    """The database constraint is generated from the code, so the two cannot drift.

    If a role is added in app.core.permissions without a migration, this fails.
    """
    for index, role in enumerate(sorted(VALID_ROLES)):
        user = _user(db, f"role{index}@example.com")
        db.add(RoleAssignment(user_account_id=user.id, role=role))
        db.flush()


def test_role_assignment_requires_a_real_user(db):
    db.add(RoleAssignment(user_account_id=999_999, role="admin"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_deleting_a_user_removes_their_role_assignments(db):
    user = _user(db, "gone@example.com")
    db.add(RoleAssignment(user_account_id=user.id, role="admin"))
    db.flush()
    db.delete(user)
    db.flush()
    assert db.query(RoleAssignment).filter_by(user_account_id=user.id).count() == 0


def test_a_revoked_assignment_is_kept_not_deleted(db):
    """The audit trail must be able to answer what access someone had."""
    user = _user(db, "revoked@example.com")
    assignment = RoleAssignment(user_account_id=user.id, role="content_manager")
    db.add(assignment)
    db.flush()
    assignment.revoked_at = utcnow()
    db.flush()
    stored = db.query(RoleAssignment).filter_by(id=assignment.id).one()
    assert stored.revoked_at is not None
    assert stored.role == "content_manager"


# ── auth_session ───────────────────────────────────────────────────────────────


def test_session_stores_hashes_not_tokens(db):
    user = _user(db, "s@example.com")
    session_row = AuthSession(
        user_account_id=user.id,
        token_hash="a" * 64,
        csrf_hash="b" * 64,
        expires_at=utcnow(),
    )
    db.add(session_row)
    db.flush()
    # There is deliberately no column that could hold a raw token.
    assert not hasattr(session_row, "token")
    assert not hasattr(session_row, "csrf")


def test_no_identity_table_has_a_plaintext_token_column(db):
    """A raw token in the database could be replayed as a login."""
    columns = db.execute(
        text(
            "SELECT table_name || '.' || column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND table_name IN ('auth_session', 'invitation')"
        )
    ).scalars().all()
    for column in columns:
        name = column.split(".")[1]
        if "token" in name or "csrf" in name:
            assert name.endswith("_hash"), f"{column} looks like a raw secret"


def test_session_token_hash_is_unique(db):
    first = _user(db, "one@example.com")
    second = _user(db, "two@example.com")
    db.add(
        AuthSession(
            user_account_id=first.id,
            token_hash="c" * 64,
            csrf_hash="d" * 64,
            expires_at=utcnow(),
        )
    )
    db.flush()
    db.add(
        AuthSession(
            user_account_id=second.id,
            token_hash="c" * 64,
            csrf_hash="e" * 64,
            expires_at=utcnow(),
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_deleting_a_user_removes_their_sessions(db):
    user = _user(db, "sessions@example.com")
    db.add(
        AuthSession(
            user_account_id=user.id,
            token_hash="f" * 64,
            csrf_hash="g" * 64,
            expires_at=utcnow(),
        )
    )
    db.flush()
    db.delete(user)
    db.flush()
    assert db.query(AuthSession).filter_by(user_account_id=user.id).count() == 0


# ── invitation ─────────────────────────────────────────────────────────────────


def test_invitation_requires_a_valid_role(db):
    db.add(
        Invitation(
            email="new@example.com",
            role="not_a_role",
            token_hash="h" * 64,
            expires_at=utcnow(),
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_invitation_can_be_created_with_a_valid_role(db):
    invitation = Invitation(
        email="new@example.com",
        role="content_manager",
        token_hash="i" * 64,
        expires_at=utcnow(),
    )
    db.add(invitation)
    db.flush()
    assert invitation.id is not None
    assert invitation.accepted_at is None


def test_invitation_token_hash_is_unique(db):
    db.add(
        Invitation(
            email="a@example.com",
            role="admin",
            token_hash="j" * 64,
            expires_at=utcnow(),
        )
    )
    db.flush()
    db.add(
        Invitation(
            email="b@example.com",
            role="admin",
            token_hash="j" * 64,
            expires_at=utcnow(),
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


# ── The spine itself ───────────────────────────────────────────────────────────


def test_identity_is_not_rooted_in_an_affiliate_table(db):
    """Spec section 6.1, asserted structurally.

    Later modules hang their own profiles off user_account. If identity were
    rooted in an affiliate record, the supposedly generic spine would have been
    shaped around models and every later module would work around it.
    """
    tables = db.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
    ).scalars().all()
    assert "user_account" in tables
    assert "affiliate" not in tables
    assert "affiliate_profile" not in tables

    # Every identity table points at user_account, not the other way round.
    for table in ("role_assignment", "auth_session", "invitation"):
        columns = db.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t"
            ),
            {"t": table},
        ).scalars().all()
        assert "user_account_id" in columns or "invited_by" in columns
