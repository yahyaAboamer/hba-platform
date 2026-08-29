"""Authentication API.

Spec sections 6.2 and 6.3. These tests drive real HTTP requests, so they
exercise cookies, CSRF headers, status codes, and the permission gate exactly
as a browser would.

The fresh_database fixture rebuilds the schema. TRUNCATE is impossible here:
audit_event refuses it and truncating user_account cascades into it, which is
the append-only guard working as intended.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import engine
from app.main import app

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "a-long-enough-password",
}


@pytest.fixture()
def client(fresh_database):
    with TestClient(app) as test_client:
        yield test_client


def _bootstrap(client) -> dict:
    response = client.post("/api/auth/bootstrap", json=BOOTSTRAP)
    assert response.status_code == 201, response.text
    return response.json()


def _audit_actions() -> list[str]:
    with engine.connect() as connection:
        return [
            row[0]
            for row in connection.execute(
                text("SELECT action FROM audit_event ORDER BY id")
            )
        ]


# ── Bootstrap ──────────────────────────────────────────────────────────────────


def test_status_reports_setup_is_required_before_any_account(client):
    assert client.get("/api/auth/status").json() == {"setup_required": True}


def test_bootstrap_creates_the_first_admin(client):
    body = _bootstrap(client)
    assert body["actor"]["role"] == "admin"
    assert body["actor"]["email"] == "owner@example.com"
    assert body["csrf"]


def test_status_reports_setup_complete_afterwards(client):
    _bootstrap(client)
    assert client.get("/api/auth/status").json() == {"setup_required": False}


def test_bootstrap_only_works_once(client):
    _bootstrap(client)
    second = client.post(
        "/api/auth/bootstrap", json={**BOOTSTRAP, "email": "second@example.com"}
    )
    assert second.status_code == 409


def test_bootstrap_signs_the_new_admin_in(client):
    _bootstrap(client)
    assert "hba_session" in client.cookies
    assert client.get("/api/auth/me").status_code == 200


def test_bootstrap_rejects_a_short_password(client):
    response = client.post(
        "/api/auth/bootstrap", json={**BOOTSTRAP, "password": "short"}
    )
    assert response.status_code == 422


def test_bootstrap_rejects_an_invalid_email(client):
    response = client.post(
        "/api/auth/bootstrap", json={**BOOTSTRAP, "email": "not-an-email"}
    )
    assert response.status_code == 422


# ── Login and logout ───────────────────────────────────────────────────────────


def test_login_succeeds_and_sets_a_session_cookie(client):
    _bootstrap(client)
    client.cookies.clear()
    response = client.post(
        "/api/auth/login",
        json={"email": BOOTSTRAP["email"], "password": BOOTSTRAP["password"]},
    )
    assert response.status_code == 200
    assert "hba_session" in response.cookies


def test_login_is_case_insensitive_on_email(client):
    _bootstrap(client)
    client.cookies.clear()
    response = client.post(
        "/api/auth/login",
        json={"email": "OWNER@EXAMPLE.COM", "password": BOOTSTRAP["password"]},
    )
    assert response.status_code == 200


def test_login_rejects_a_wrong_password(client):
    _bootstrap(client)
    client.cookies.clear()
    response = client.post(
        "/api/auth/login",
        json={"email": BOOTSTRAP["email"], "password": "definitely-wrong-password"},
    )
    assert response.status_code == 401


def test_login_gives_the_same_answer_for_unknown_and_wrong(client):
    """Different messages would confirm which addresses have accounts."""
    _bootstrap(client)
    client.cookies.clear()
    wrong = client.post(
        "/api/auth/login",
        json={"email": BOOTSTRAP["email"], "password": "definitely-wrong-password"},
    )
    unknown = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "definitely-wrong-password"},
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_the_session_cookie_is_httponly(client):
    """JavaScript must not be able to read the session token."""
    _bootstrap(client)
    client.cookies.clear()
    response = client.post(
        "/api/auth/login",
        json={"email": BOOTSTRAP["email"], "password": BOOTSTRAP["password"]},
    )
    assert "httponly" in response.headers["set-cookie"].lower()


def test_logout_ends_the_session(client):
    body = _bootstrap(client)
    logout = client.post("/api/auth/logout", headers={"X-CSRF-Token": body["csrf"]})
    assert logout.status_code == 200
    assert client.get("/api/auth/me").status_code == 401


# ── Session and CSRF enforcement ───────────────────────────────────────────────


def test_me_requires_a_session(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_the_actor_and_permissions(client):
    _bootstrap(client)
    body = client.get("/api/auth/me").json()
    assert body["actor"]["email"] == BOOTSTRAP["email"]
    assert "payroll.approve" in body["permissions"]
    assert "payments.record" in body["permissions"]


def test_me_says_which_month_the_platform_is_working_in(client, monkeypatch):
    """Every screen needs this before it can render a figure, and this request
    is already made once at start-up.

    Before go-live the working month is the go-live month: opening on a month
    the platform holds nothing for reads as a broken tool.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "2099-06", raising=False)
    _bootstrap(client)

    body = client.get("/api/auth/me").json()

    assert body["platform"] == {
        "working_month": "2099-06",
        "go_live_month": "2099-06",
    }


def test_me_reports_no_go_live_month_when_none_is_set(client, monkeypatch):
    """Null rather than an empty string, so the client has one falsy shape to
    check rather than two.
    """
    from app.config import settings
    from app.core.businesstime import business_month, utcnow

    monkeypatch.setattr(settings, "go_live_month", "", raising=False)
    _bootstrap(client)

    body = client.get("/api/auth/me").json()

    assert body["platform"]["go_live_month"] is None
    assert body["platform"]["working_month"] == business_month(utcnow())


def test_an_unsafe_request_without_csrf_is_rejected(client):
    """A cross-site form post must not be able to act on a live cookie.

    Tested against inviting somebody, which is a write that matters. It used to
    be tested against logout, which is now deliberately exempt - and a control
    demonstrated only on the one route that does not enforce it is a control
    nobody has actually checked.
    """
    _bootstrap(client)
    client.headers.pop("X-CSRF-Token", None)

    refused = client.post(
        "/api/auth/invitations", json={"email": "nour@example.com", "role": "affiliate"}
    )

    assert refused.status_code == 401


def test_an_unsafe_request_with_a_wrong_csrf_is_rejected(client):
    _bootstrap(client)

    refused = client.post(
        "/api/auth/invitations",
        json={"email": "nour@example.com", "role": "affiliate"},
        headers={"X-CSRF-Token": "not-the-right-token"},
    )

    assert refused.status_code == 401


def test_logout_is_exempt_from_csrf_on_purpose(client):
    """Pinned, so the exemption stays a decision rather than becoming a drift.

    What the check buys on a logout is preventing somebody being signed out of
    their own session: it reads nothing, changes nothing, moves no money. What
    enforcing it cost was somebody who **could not sign out**, twice, once
    leaving a live administrator session on a machine after the person had
    asked to leave it.

    If this test ever fails because the exemption was removed, the thing to
    re-read is that trade, not this assertion.
    """
    created = _bootstrap(client)
    assert created["csrf"]
    client.headers.pop("X-CSRF-Token", None)

    out = client.post("/api/auth/logout")

    assert out.status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_logout_still_needs_a_real_session(client):
    """Exempt from the token, not from having a session at all.

    Idempotent by design - signing out of something already gone is the
    outcome asked for, not an error - so this checks it cannot be used to
    learn anything, rather than that it refuses.
    """
    _bootstrap(client)
    client.cookies.set("hba_session", "a-completely-made-up-token")
    client.headers.pop("X-CSRF-Token", None)

    out = client.post("/api/auth/logout")

    assert out.status_code == 200
    assert out.json() == {"success": True}


def test_a_forged_session_cookie_is_rejected(client):
    client.cookies.set("hba_session", "a-completely-made-up-token")
    assert client.get("/api/auth/me").status_code == 401


# ── Invitations ────────────────────────────────────────────────────────────────


def test_an_admin_can_invite_staff(client):
    body = _bootstrap(client)
    response = client.post(
        "/api/auth/invitations",
        json={"email": "sara@example.com", "role": "content_manager"},
        headers={"X-CSRF-Token": body["csrf"]},
    )
    assert response.status_code == 201
    assert response.json()["invitation"]["role"] == "content_manager"
    assert response.json()["token"]


def test_inviting_requires_authentication(client):
    _bootstrap(client)
    client.cookies.clear()
    response = client.post(
        "/api/auth/invitations",
        json={"email": "sara@example.com", "role": "content_manager"},
        headers={"X-CSRF-Token": "anything"},
    )
    assert response.status_code == 401


def test_an_unknown_role_is_refused(client):
    body = _bootstrap(client)
    response = client.post(
        "/api/auth/invitations",
        json={"email": "sara@example.com", "role": "wizard"},
        headers={"X-CSRF-Token": body["csrf"]},
    )
    assert response.status_code == 422


def test_accepting_an_invitation_creates_a_working_account(client):
    body = _bootstrap(client)
    invite = client.post(
        "/api/auth/invitations",
        json={"email": "sara@example.com", "role": "content_manager"},
        headers={"X-CSRF-Token": body["csrf"]},
    ).json()

    client.cookies.clear()
    accepted = client.post(
        "/api/auth/invitations/accept",
        json={
            "token": invite["token"],
            "display_name": "Sara",
            "password": "sara-long-enough-password",
        },
    )
    assert accepted.status_code == 201
    assert accepted.json()["actor"]["role"] == "content_manager"


def test_the_invited_role_gets_exactly_its_permissions(client):
    """The permission gate is enforced by role, end to end over HTTP."""
    body = _bootstrap(client)
    invite = client.post(
        "/api/auth/invitations",
        json={"email": "sara@example.com", "role": "content_manager"},
        headers={"X-CSRF-Token": body["csrf"]},
    ).json()

    client.cookies.clear()
    client.post(
        "/api/auth/invitations/accept",
        json={
            "token": invite["token"],
            "display_name": "Sara",
            "password": "sara-long-enough-password",
        },
    )
    permissions = client.get("/api/auth/me").json()["permissions"]
    assert "targets.record" in permissions
    assert "compensation.manage" in permissions
    # The boundary that holds: they cannot approve payroll or move money.
    assert "payroll.approve" not in permissions
    assert "payments.record" not in permissions
    assert "invitations.send" not in permissions


def test_a_role_without_invitation_rights_cannot_invite(client):
    """Server-side enforcement, not a hidden button."""
    body = _bootstrap(client)
    invite = client.post(
        "/api/auth/invitations",
        json={"email": "sara@example.com", "role": "content_manager"},
        headers={"X-CSRF-Token": body["csrf"]},
    ).json()

    client.cookies.clear()
    accepted = client.post(
        "/api/auth/invitations/accept",
        json={
            "token": invite["token"],
            "display_name": "Sara",
            "password": "sara-long-enough-password",
        },
    ).json()

    forbidden = client.post(
        "/api/auth/invitations",
        json={"email": "someone@example.com", "role": "admin"},
        headers={"X-CSRF-Token": accepted["csrf"]},
    )
    assert forbidden.status_code == 403
    assert "invitations.send" in forbidden.json()["detail"]


def test_an_invitation_cannot_be_accepted_twice(client):
    body = _bootstrap(client)
    invite = client.post(
        "/api/auth/invitations",
        json={"email": "sara@example.com", "role": "content_manager"},
        headers={"X-CSRF-Token": body["csrf"]},
    ).json()

    client.cookies.clear()
    payload = {
        "token": invite["token"],
        "display_name": "Sara",
        "password": "sara-long-enough-password",
    }
    assert client.post("/api/auth/invitations/accept", json=payload).status_code == 201
    client.cookies.clear()
    assert client.post("/api/auth/invitations/accept", json=payload).status_code == 422


# ── Audit ──────────────────────────────────────────────────────────────────────


def test_bootstrap_login_and_logout_are_all_audited(client):
    body = _bootstrap(client)
    client.post("/api/auth/logout", headers={"X-CSRF-Token": body["csrf"]})
    client.post(
        "/api/auth/login",
        json={"email": BOOTSTRAP["email"], "password": BOOTSTRAP["password"]},
    )
    actions = _audit_actions()
    assert actions == ["auth.bootstrap", "auth.logout", "auth.login"]


def test_inviting_is_audited(client):
    body = _bootstrap(client)
    client.post(
        "/api/auth/invitations",
        json={"email": "sara@example.com", "role": "content_manager"},
        headers={"X-CSRF-Token": body["csrf"]},
    )
    assert "invitation.create" in _audit_actions()


def test_a_failed_login_creates_no_session_and_no_audit_entry(client):
    _bootstrap(client)
    before = len(_audit_actions())
    client.cookies.clear()
    client.post(
        "/api/auth/login",
        json={"email": BOOTSTRAP["email"], "password": "definitely-wrong-password"},
    )
    assert len(_audit_actions()) == before


# ── Response hygiene ───────────────────────────────────────────────────────────


def test_api_responses_are_never_cached(client):
    _bootstrap(client)
    response = client.get("/api/auth/me")
    assert response.headers["cache-control"] == "no-store"


def test_security_headers_are_present(client):
    response = client.get("/api/health/live")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_no_response_ever_contains_a_password_hash(client):
    body = _bootstrap(client)
    assert "password" not in str(body).lower()
    me = client.get("/api/auth/me").text
    assert "password" not in me.lower()
    assert "pbkdf2" not in me.lower()


# -- Standing up a fresh deployment (Phase 10) -------------------------------


def test_a_fresh_platform_says_it_needs_setting_up(fresh_database):
    """Until this existed, the first step of every deployment had no interface.

    The API docs are switched off in production, so standing one up meant
    calling the bootstrap endpoint by hand - which is a poor first impression
    and has to be done again every time staging is reset.
    """
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/auth/needs-setup").json() == {"needs_setup": True}


def test_once_there_is_an_account_it_says_so(client):
    """Anonymous callers see the same answer - it is a fact about the
    deployment, not about the caller.
    """
    _bootstrap(client)

    with TestClient(app) as anonymous:
        assert anonymous.get("/api/auth/needs-setup").json() == {"needs_setup": False}


def test_the_check_needs_no_session(fresh_database):
    """The only person who can ask is somebody looking at a platform with
    nobody in it, so requiring a session would make it unanswerable.
    """
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/auth/needs-setup").status_code == 200


def test_it_reveals_nothing_the_bootstrap_endpoint_did_not(client):
    """Worth being explicit about the disclosure.

    `POST /bootstrap` already answers 201 or 409 to the same question, so this
    tells an anonymous caller nothing new - it shortens the unclaimed window
    rather than lengthening it, because the owner can find the form instead of
    hunting for a curl command.
    """
    _bootstrap(client)

    with TestClient(app) as anonymous:
        refused = anonymous.post(
            "/api/auth/bootstrap",
            json={
                "email": "someone@example.com",
                "display_name": "Someone",
                "password": "a-long-enough-password",
            },
        )

    assert refused.status_code == 409
    assert anonymous.get("/api/auth/needs-setup").json()["needs_setup"] is False


# -- The session outlives the token that lets you use it ---------------------


def test_a_returning_tab_can_still_write(fresh_database):
    """The bug that made *Invite a model* and *Sign out* both say
    "Authentication required" on a platform somebody was plainly signed in to.

    The session cookie is persistent - twelve hours, `max_age` set. The CSRF
    token was kept in `sessionStorage`, which the browser throws away when the
    tab closes. So reopening the tab left a live session and no token: every
    read worked, the interface showed a signed-in administrator, and **every
    write failed with a message about authentication.**

    Reproduced by keeping the cookie and discarding everything else, which is
    exactly what closing a tab does.
    """
    with TestClient(app) as first_visit:
        created = first_visit.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert created.status_code == 201
        cookie = first_visit.cookies.get("hba_session")
        csrf_cookie = first_visit.cookies.get("hba_csrf")

    # A new tab. The browser still has the cookies; nothing else survives.
    with TestClient(app) as returning:
        returning.cookies.set("hba_session", cookie)
        if csrf_cookie:
            returning.cookies.set("hba_csrf", csrf_cookie)

        # Reads work, which is why the interface looks fine.
        assert returning.get("/api/auth/me").status_code == 200

        # And so must writes. The token has to come from somewhere the browser
        # keeps for as long as it keeps the session.
        assert csrf_cookie, "the CSRF token must survive a closed tab"
        wrote = returning.post(
            "/api/auth/invitations",
            json={"email": "model@example.com", "role": "affiliate"},
            headers={"X-CSRF-Token": csrf_cookie},
        )
        assert wrote.status_code == 201, wrote.text


def test_the_csrf_cookie_is_readable_by_the_page(fresh_database):
    """Double submit: the page reads the token and echoes it in a header.

    Readable on purpose. An attacker on another origin cannot read our
    cookies, and `SameSite=lax` means the session cookie is not sent on a
    cross-site POST at all - so the header remains something only our own page
    can produce. Nothing is lost by the page being able to read it: script
    running on this origin could already read `sessionStorage` and make
    credentialed same-origin requests.
    """
    with TestClient(app) as client:
        response = client.post("/api/auth/bootstrap", json=BOOTSTRAP)

    header = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in header if c.startswith("hba_session="))
    csrf_cookie = next(c for c in header if c.startswith("hba_csrf="))

    assert "httponly" in session_cookie.lower(), "the session token is never readable"
    assert "httponly" not in csrf_cookie.lower(), "the page has to be able to read this"
    assert "samesite=lax" in csrf_cookie.lower()


def test_signing_out_clears_both(fresh_database):
    """Sign-out appeared to do nothing: the request needed a CSRF token, the
    token was gone, so it failed - and the screen never moved because the
    navigation was waiting on a call that threw.
    """
    with TestClient(app) as client:
        created = client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        client.headers["X-CSRF-Token"] = created.json()["csrf"]

        out = client.post("/api/auth/logout")
        assert out.status_code in (200, 204), out.text

    cleared = out.headers.get_list("set-cookie")
    assert any(c.startswith("hba_session=") for c in cleared)
    assert any(c.startswith("hba_csrf=") for c in cleared)
