"""A model applying, over HTTP.

The service tests cover what an application creates and refuses. This file
covers the thing only a real request can prove: **who is allowed to call it.**

The invite-accept-apply sequence is driven end to end rather than written
straight into the database, because the ordering is the part that has to work -
an account exists before a profile does, and the gate on this route depends on
exactly that.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import engine
from app.main import app
from app.models.payouts import PayoutMethod

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "quiet-harbour-lantern",
}
PASSWORD = "quiet-harbour-lantern"

APPLICATION = {
    "name": "Nour Mahmoud",
    "phone": "010 1234 5678",
    "code": "NOUR10",
    "payout_method": PayoutMethod.INSTAPAY,
    "instapay_address_url": "https://ipn.eg/S/nour.mahmoud/instapay/8Xk2Qp",
    "instapay_phone": "01001234567",
}


@pytest.fixture()
def admin(fresh_database):
    """Signed in as the maintainer, who does the inviting."""
    with TestClient(app) as client:
        response = client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield client


def _invite(admin, email: str) -> str:
    response = admin.post(
        "/api/auth/invitations", json={"email": email, "role": "affiliate"}
    )
    assert response.status_code == 201, response.text
    return response.json()["token"]


def _accept(token: str, name: str) -> TestClient:
    """Accept an invitation in its own client, so the model's session does not
    replace the maintainer's.
    """
    client = TestClient(app)
    response = client.post(
        "/api/auth/invitations/accept",
        json={"token": token, "display_name": name, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf"]
    return client


# ── The sequence §13 describes ───────────────────────────────────────────────


def test_invited_accepted_and_applied(admin):
    """Steps 1 and 2, driven end to end."""
    token = _invite(admin, "nour@example.com")
    model = _accept(token, "Nour")

    before = model.get("/api/applications/mine").json()
    assert before["applied"] is False
    assert before["status"] is None

    created = model.post("/api/applications", json=APPLICATION)
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "pending"

    after = model.get("/api/applications/mine").json()
    assert after["applied"] is True
    assert after["status"] == "pending"


def test_the_form_learns_its_required_fields_from_the_server(admin):
    """Served rather than duplicated in the client, so the form and the service
    cannot disagree about what a bank transfer needs.
    """
    token = _invite(admin, "nour@example.com")
    model = _accept(token, "Nour")

    required = model.get("/api/applications/mine").json()["required_fields"]

    assert set(required["instapay"]) == {"instapay_address_url", "instapay_phone"}
    assert set(required["bank"]) == {
        "bank_name",
        "bank_account_holder",
        "bank_account_number",
    }


def test_a_newly_applied_model_appears_on_the_maintainers_list(admin):
    """The two sides meet: they apply, and it is waiting for somebody."""
    token = _invite(admin, "nour@example.com")
    model = _accept(token, "Nour")
    model.post("/api/applications", json=APPLICATION)

    rows = admin.get("/api/affiliates").json()["affiliates"]

    assert [row["name"] for row in rows] == ["Nour Mahmoud"]
    assert rows[0]["status"] == "pending"
    assert rows[0]["has_verified_code"] is False, "§10.4's gate is still shut"


# ── Who may call it ──────────────────────────────────────────────────────────


def test_anonymous_access_is_refused(fresh_database):
    with TestClient(app) as anonymous:
        assert anonymous.post("/api/applications", json=APPLICATION).status_code == 401
        assert anonymous.get("/api/applications/mine").status_code == 401


def test_a_maintainer_cannot_apply(admin):
    """An administrator has no affiliate record to create, and letting them
    make one would produce a profile whose owner is the person approving it.
    """
    response = admin.post("/api/applications", json=APPLICATION)

    assert response.status_code == 403


def test_applying_twice_over_http_is_refused(admin):
    token = _invite(admin, "nour@example.com")
    model = _accept(token, "Nour")
    assert model.post("/api/applications", json=APPLICATION).status_code == 201

    again = model.post("/api/applications", json=APPLICATION)

    assert again.status_code == 400
    assert "already applied" in again.json()["detail"]


def test_a_second_application_leaves_the_first_untouched(admin):
    """Refused, not partially applied - one profile, one code, one destination."""
    token = _invite(admin, "nour@example.com")
    model = _accept(token, "Nour")
    model.post("/api/applications", json=APPLICATION)
    model.post("/api/applications", json={**APPLICATION, "code": "OTHER10"})

    with engine.connect() as connection:
        profiles = connection.execute(
            text("SELECT count(*) FROM affiliate_profile")
        ).scalar_one()
        codes = connection.execute(
            text("SELECT count(*) FROM discount_code_period")
        ).scalar_one()

    assert (profiles, codes) == (1, 1)


# ── §6.5 over the wire ───────────────────────────────────────────────────────


def test_money_terms_sent_with_an_application_are_ignored(admin):
    """A model may never edit what they are owed (§6.5).

    The body model has no field for a rate, so sending one is dropped rather
    than applied - proven here rather than trusted, because "the form does not
    show it" is not a control.
    """
    from app.services.compensation import terms_for

    token = _invite(admin, "nour@example.com")
    model = _accept(token, "Nour")

    created = model.post(
        "/api/applications",
        json={
            **APPLICATION,
            "compensation_type": "commission",
            "commission_rate_bp": 9999,
            "base_amount_piastres": 99_999_999,
            "status": "active",
        },
    )
    assert created.status_code == 201, created.text

    body = admin.get("/api/affiliates").json()["affiliates"][0]
    assert body["status"] == "pending", "the applicant approved themselves"

    detail = admin.get(f"/api/affiliates/{body['id']}").json()
    assert detail["compensation"] is None, "the applicant set their own rate"


# ── Inviting somebody already on the programme ───────────────────────────────


def test_inviting_an_email_already_on_the_programme_is_refused(admin):
    token = _invite(admin, "nour@example.com")
    model = _accept(token, "Nour")
    model.post("/api/applications", json=APPLICATION)

    again = admin.post(
        "/api/auth/invitations", json={"email": "nour@example.com", "role": "affiliate"}
    )

    assert again.status_code == 409
    assert "already on the programme" in again.json()["detail"]
