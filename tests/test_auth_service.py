"""Sessions and authentication.

Spec section 6.2. Only hashes are stored: the raw session token lives in an
HttpOnly cookie and the CSRF token in a header, so a database leak cannot be
replayed as a login.
"""

from datetime import timedelta

from app.core.businesstime import utcnow
from app.core.passwords import hash_password
from app.models.identity import UserAccount
from app.services.auth import authenticate, issue_session, resolve_session, revoke_session

PASSWORD = "quiet-harbour-lantern"


def _user(db, email="u@example.com", password=PASSWORD, status="active"):
    user = UserAccount(
        email=email, password_hash=hash_password(password), status=status
    )
    db.add(user)
    db.flush()
    return user


# ── Issuing and resolving ──────────────────────────────────────────────────────


def test_issued_session_resolves(db):
    user = _user(db)
    token, csrf, _ = issue_session(db, user.id)
    db.flush()
    assert resolve_session(db, token, csrf).id == user.id


def test_raw_token_is_never_stored(db):
    """A database leak must not be replayable as a login."""
    user = _user(db, "raw@example.com")
    token, csrf, row = issue_session(db, user.id)
    db.flush()
    assert row.token_hash != token
    assert row.csrf_hash != csrf
    assert len(row.token_hash) == 64  # sha256 hex
    assert token not in row.token_hash


def test_each_session_gets_distinct_secrets(db):
    user = _user(db, "distinct@example.com")
    first_token, first_csrf, _ = issue_session(db, user.id)
    second_token, second_csrf, _ = issue_session(db, user.id)
    db.flush()
    assert first_token != second_token
    assert first_csrf != second_csrf


def test_client_details_are_recorded(db):
    user = _user(db, "client@example.com")
    _, _, row = issue_session(db, user.id, "10.0.0.1", "Mozilla/5.0")
    db.flush()
    assert row.ip_address == "10.0.0.1"
    assert row.user_agent == "Mozilla/5.0"


def test_an_overlong_user_agent_is_truncated_not_rejected(db):
    """A hostile or unusual header must not break sign-in."""
    user = _user(db, "longua@example.com")
    _, _, row = issue_session(db, user.id, None, "x" * 5000)
    db.flush()
    assert len(row.user_agent) <= 400


def test_unknown_token_resolves_to_nothing(db):
    assert resolve_session(db, "not-a-real-token", None) is None


def test_empty_token_resolves_to_nothing(db):
    assert resolve_session(db, "", None) is None
    assert resolve_session(db, None, None) is None


# ── CSRF ───────────────────────────────────────────────────────────────────────


def test_wrong_csrf_is_rejected(db):
    user = _user(db, "csrf@example.com")
    token, _, _ = issue_session(db, user.id)
    db.flush()
    assert resolve_session(db, token, "wrong-csrf") is None


def test_csrf_is_not_required_for_reads(db):
    """Callers pass None for safe methods and the header value for unsafe ones."""
    user = _user(db, "read@example.com")
    token, _, _ = issue_session(db, user.id)
    db.flush()
    assert resolve_session(db, token, None).id == user.id


def test_empty_csrf_on_an_unsafe_request_is_rejected(db):
    """An empty string is a supplied-but-wrong token, not an absent one."""
    user = _user(db, "emptycsrf@example.com")
    token, _, _ = issue_session(db, user.id)
    db.flush()
    assert resolve_session(db, token, "") is None


def test_csrf_from_another_session_is_rejected(db):
    user = _user(db, "mixed@example.com")
    first_token, _, _ = issue_session(db, user.id)
    _, second_csrf, _ = issue_session(db, user.id)
    db.flush()
    assert resolve_session(db, first_token, second_csrf) is None


# ── Expiry and revocation ──────────────────────────────────────────────────────


def test_expired_session_is_rejected(db):
    user = _user(db, "expired@example.com")
    token, csrf, row = issue_session(db, user.id)
    row.expires_at = utcnow() - timedelta(minutes=1)
    db.flush()
    assert resolve_session(db, token, csrf) is None


def test_session_expiry_follows_the_configured_lifetime(db):
    from app.config import settings

    user = _user(db, "lifetime@example.com")
    _, _, row = issue_session(db, user.id)
    db.flush()
    expected = utcnow() + timedelta(hours=settings.session_hours)
    assert abs((row.expires_at - expected).total_seconds()) < 60


def test_revoked_session_is_rejected(db):
    user = _user(db, "revoked@example.com")
    token, csrf, _ = issue_session(db, user.id)
    db.flush()
    assert revoke_session(db, token) is True
    db.flush()
    assert resolve_session(db, token, csrf) is None


def test_revoking_twice_reports_no_further_change(db):
    user = _user(db, "twice@example.com")
    token, _, _ = issue_session(db, user.id)
    db.flush()
    assert revoke_session(db, token) is True
    assert revoke_session(db, token) is False


def test_revoking_an_unknown_token_is_harmless(db):
    assert revoke_session(db, "not-a-real-token") is False


def test_revoking_one_session_leaves_the_others_alone(db):
    """Signing out on one device must not sign you out everywhere."""
    user = _user(db, "devices@example.com")
    laptop_token, laptop_csrf, _ = issue_session(db, user.id)
    phone_token, phone_csrf, _ = issue_session(db, user.id)
    db.flush()
    revoke_session(db, laptop_token)
    db.flush()
    assert resolve_session(db, laptop_token, laptop_csrf) is None
    assert resolve_session(db, phone_token, phone_csrf).id == user.id


def test_suspended_user_cannot_resolve_an_existing_session(db):
    """Suspending an account must end access immediately, not at expiry."""
    user = _user(db, "susp@example.com")
    token, csrf, _ = issue_session(db, user.id)
    user.status = "suspended"
    db.flush()
    assert resolve_session(db, token, csrf) is None


def test_resolving_updates_last_seen(db):
    user = _user(db, "seen@example.com")
    token, csrf, row = issue_session(db, user.id)
    db.flush()
    row.last_seen_at = utcnow() - timedelta(hours=5)
    db.flush()
    before = row.last_seen_at
    resolve_session(db, token, csrf)
    db.flush()
    assert row.last_seen_at > before


# ── Authentication ─────────────────────────────────────────────────────────────


def test_authenticate_accepts_the_correct_password(db):
    _user(db, "auth@example.com")
    assert authenticate(db, "auth@example.com", PASSWORD) is not None


def test_authenticate_is_case_insensitive_on_email(db):
    _user(db, "Case@Example.com")
    assert authenticate(db, "case@example.com", PASSWORD) is not None
    assert authenticate(db, "CASE@EXAMPLE.COM", PASSWORD) is not None


def test_authenticate_rejects_a_wrong_password(db):
    _user(db, "wrong@example.com")
    assert authenticate(db, "wrong@example.com", "definitely-not-the-password") is None


def test_authenticate_rejects_an_unknown_email(db):
    assert authenticate(db, "nobody@example.com", PASSWORD) is None


def test_authenticate_rejects_a_suspended_user(db):
    _user(db, "suspauth@example.com", status="suspended")
    assert authenticate(db, "suspauth@example.com", PASSWORD) is None


def test_authenticate_rejects_an_invited_user_who_has_not_accepted(db):
    _user(db, "invited@example.com", status="invited")
    assert authenticate(db, "invited@example.com", PASSWORD) is None


def test_authenticate_records_the_login_time(db):
    user = _user(db, "logintime@example.com")
    assert user.last_login_at is None
    authenticate(db, "logintime@example.com", PASSWORD)
    db.flush()
    assert user.last_login_at is not None


def test_authenticate_handles_empty_input(db):
    assert authenticate(db, "", "") is None
    assert authenticate(db, None, None) is None
