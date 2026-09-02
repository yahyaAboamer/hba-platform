"""What a model may do to their own record, over HTTP.

§6.4 is the highest-risk thing in the affiliate portal: a compromised account
that can silently repoint an InstaPay address can redirect an entire payout.
Every requirement in that section has a test here, and the ones about *not*
being able to reach somebody else's record are the reason this file exists.
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
ADDRESS = "https://ipn.eg/S/nour.mahmoud/instapay/8Xk2Qp"
NEW_ADDRESS = "https://ipn.eg/S/nour.mahmoud/instapay/NEWaddr"

APPLICATION = {
    "name": "Nour Mahmoud",
    "phone": "010 1234 5678",
    "code": "NOUR10",
    "payout_method": PayoutMethod.INSTAPAY,
    "instapay_address_url": ADDRESS,
    "instapay_phone": "01001234567",
}


@pytest.fixture()
def admin(fresh_database):
    with TestClient(app) as client:
        response = client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield client


def _model(admin, email: str, name: str, code: str) -> TestClient:
    """An invited, accepted, applied model, in their own client."""
    invite = admin.post(
        "/api/auth/invitations", json={"email": email, "role": "affiliate"}
    )
    assert invite.status_code == 201, invite.text

    client = TestClient(app)
    accepted = client.post(
        "/api/auth/invitations/accept",
        json={
            "token": invite.json()["token"],
            "display_name": name,
            "password": PASSWORD,
        },
    )
    assert accepted.status_code == 201, accepted.text
    client.headers["X-CSRF-Token"] = accepted.json()["csrf"]

    applied = client.post(
        "/api/applications", json={**APPLICATION, "name": name, "code": code}
    )
    assert applied.status_code == 201, applied.text
    return client


# ── Their own record ───────────────────────────────────────────────────────────


def test_a_model_sees_their_own_record(admin):
    model = _model(admin, "nour@example.com", "Nour Hassan", "NOUR10")

    body = model.get("/api/me").json()

    assert body["name"] == "Nour Hassan"
    assert body["status"] == "pending"
    assert body["state"] == "waiting"


def test_a_payout_destination_is_masked_even_to_its_owner(admin):
    """They supplied it, so it tells them nothing they do not know - and a
    screen printing a full account number is one worth photographing over
    somebody's shoulder.
    """
    model = _model(admin, "nour@example.com", "Nour Hassan", "NOUR10")

    destination = model.get("/api/me").json()["payout_destination"]

    assert destination["instapay_address_url"] != ADDRESS
    assert destination["instapay_address_url"].startswith("…")


def test_a_maintainer_is_refused_from_the_model_routes(admin):
    """An administrator is not the subject of any affiliate record. This is the
    mixing the two-gate design exists to prevent.
    """
    assert admin.get("/api/me").status_code == 403


def test_anonymous_access_is_refused(fresh_database):
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/me").status_code == 401


# ── §6.4: changing where their money goes ─────────────────────────────────────


def test_changing_a_destination_needs_the_password(admin):
    """§6.4.1. A session is what an attacker has; the password is what they
    may not.
    """
    model = _model(admin, "nour@example.com", "Nour Hassan", "NOUR10")

    refused = model.put(
        "/api/me/payout-destination",
        json={
            "password": "not-the-password",
            "method": PayoutMethod.INSTAPAY,
            "instapay_address_url": NEW_ADDRESS,
            "instapay_phone": "01009999999",
        },
    )

    assert refused.status_code == 403


def test_a_wrong_password_changes_nothing(admin):
    model = _model(admin, "nour@example.com", "Nour Hassan", "NOUR10")
    model.put(
        "/api/me/payout-destination",
        json={
            "password": "not-the-password",
            "method": PayoutMethod.INSTAPAY,
            "instapay_address_url": NEW_ADDRESS,
            "instapay_phone": "01009999999",
        },
    )

    with engine.connect() as connection:
        live = connection.execute(
            text(
                "SELECT instapay_address_url FROM payout_destination "
                "WHERE superseded_at IS NULL"
            )
        ).scalar_one()

    assert live == ADDRESS


def test_the_right_password_moves_it(admin):
    model = _model(admin, "nour@example.com", "Nour Hassan", "NOUR10")

    changed = model.put(
        "/api/me/payout-destination",
        json={
            "password": PASSWORD,
            "method": PayoutMethod.INSTAPAY,
            "instapay_address_url": NEW_ADDRESS,
            "instapay_phone": "01009999999",
        },
    )

    assert changed.status_code == 200, changed.text
    with engine.connect() as connection:
        live = connection.execute(
            text(
                "SELECT instapay_address_url FROM payout_destination "
                "WHERE superseded_at IS NULL"
            )
        ).scalar_one()
    assert live == NEW_ADDRESS


def test_both_sides_come_back_masked(admin):
    """§6.4.2. They can confirm what they changed without the screen printing
    either value in full - and the response body is a second place a raw value
    could be logged.
    """
    model = _model(admin, "nour@example.com", "Nour Hassan", "NOUR10")

    body = model.put(
        "/api/me/payout-destination",
        json={
            "password": PASSWORD,
            "method": PayoutMethod.INSTAPAY,
            "instapay_address_url": NEW_ADDRESS,
            "instapay_phone": "01009999999",
        },
    ).json()

    assert ADDRESS not in str(body)
    assert NEW_ADDRESS not in str(body)
    assert body["before"]["instapay_address_url"].startswith("…")
    assert body["after"]["instapay_address_url"].startswith("…")


def test_the_old_destination_is_superseded_not_overwritten(admin):
    """A payment made in March must still resolve the destination in force
    then.
    """
    model = _model(admin, "nour@example.com", "Nour Hassan", "NOUR10")
    model.put(
        "/api/me/payout-destination",
        json={
            "password": PASSWORD,
            "method": PayoutMethod.INSTAPAY,
            "instapay_address_url": NEW_ADDRESS,
            "instapay_phone": "01009999999",
        },
    )

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT instapay_address_url, superseded_at IS NOT NULL "
                "FROM payout_destination ORDER BY id"
            )
        ).all()

    assert [tuple(row) for row in rows] == [(ADDRESS, True), (NEW_ADDRESS, False)]


def test_the_change_is_audited_with_the_values_masked(admin):
    """§6.4.4. The audit table is append-only, so the only safe moment to mask
    is before the insert.
    """
    model = _model(admin, "nour@example.com", "Nour Hassan", "NOUR10")
    model.put(
        "/api/me/payout-destination",
        json={
            "password": PASSWORD,
            "method": PayoutMethod.INSTAPAY,
            "instapay_address_url": NEW_ADDRESS,
            "instapay_phone": "01009999999",
        },
    )

    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT action, before_json, after_json FROM audit_event")
        ).all()

    written = str([tuple(row) for row in rows])
    assert "payout_destination.set" in written
    assert NEW_ADDRESS not in written


def test_a_phone_number_in_the_link_field_is_refused_here_too(admin):
    """The validator lives in `set_destination`, so every path that writes a
    destination is checked by the same rule - not only the application form.
    """
    model = _model(admin, "nour@example.com", "Nour Hassan", "NOUR10")

    refused = model.put(
        "/api/me/payout-destination",
        json={
            "password": PASSWORD,
            "method": PayoutMethod.INSTAPAY,
            "instapay_address_url": "01001234567",
            "instapay_phone": "01001234567",
        },
    )

    assert refused.status_code == 400
    assert "phone number" in refused.json()["detail"]


def test_a_missing_field_is_refused_before_the_password_is_spent(admin):
    model = _model(admin, "nour@example.com", "Nour Hassan", "NOUR10")

    refused = model.put(
        "/api/me/payout-destination",
        json={
            "password": PASSWORD,
            "method": PayoutMethod.BANK,
            "bank_name": "CIB",
        },
    )

    assert refused.status_code == 400
    assert "bank account number" in refused.json()["detail"]


# ── One model cannot reach another ──────────────────────────────────────────


def test_the_routes_take_no_affiliate_id_at_all(admin):
    """Reaching another model's record is not refused - it is unexpressible.

    Every route acts on the caller's own profile, so there is no parameter to
    tamper with. Asserted by driving two real models rather than by reading
    the signatures.
    """
    nour = _model(admin, "nour@example.com", "Nour Hassan", "NOUR10")
    sara = _model(admin, "sara@example.com", "Sara Fouad", "SARA10")

    assert nour.get("/api/me").json()["name"] == "Nour Hassan"
    assert sara.get("/api/me").json()["name"] == "Sara Fouad"


def test_one_models_change_never_touches_another(admin):
    nour = _model(admin, "nour@example.com", "Nour Hassan", "NOUR10")
    _model(admin, "sara@example.com", "Sara Fouad", "SARA10")

    nour.put(
        "/api/me/payout-destination",
        json={
            "password": PASSWORD,
            "method": PayoutMethod.WALLET,
            "wallet_phone": "01055555555",
        },
    )

    with engine.connect() as connection:
        live = connection.execute(
            text(
                "SELECT a.name, d.method FROM payout_destination d "
                "JOIN affiliate_profile a ON a.id = d.affiliate_id "
                "WHERE d.superseded_at IS NULL ORDER BY a.name"
            )
        ).all()

    assert [tuple(row) for row in live] == [
        ("Nour Hassan", PayoutMethod.WALLET),
        ("Sara Fouad", PayoutMethod.INSTAPAY),
    ]


# ── §6.4.5, from their side and the maintainer's ──────────────────────────────


def test_they_can_see_that_their_destination_moved_lately(admin):
    """A model who did not make that change is the first person who would
    notice, and the only one who can say so.
    """
    model = _model(admin, "nour@example.com", "Nour Hassan", "NOUR10")
    model.put(
        "/api/me/payout-destination",
        json={
            "password": PASSWORD,
            "method": PayoutMethod.INSTAPAY,
            "instapay_address_url": NEW_ADDRESS,
            "instapay_phone": "01009999999",
        },
    )

    body = model.get("/api/me/payout-destination/changed-recently").json()

    assert body["changed_at"] is not None


def test_the_payment_screen_is_told_a_destination_moved_lately(admin):
    """§6.4.5. `changed_recently` has existed since Phase 3 and reached no
    screen until now - it had nothing to warn about while only the maintainer
    could change a destination.
    """
    model = _model(admin, "nour@example.com", "Nour Hassan", "NOUR10")
    model.put(
        "/api/me/payout-destination",
        json={
            "password": PASSWORD,
            "method": PayoutMethod.INSTAPAY,
            "instapay_address_url": NEW_ADDRESS,
            "instapay_phone": "01009999999",
        },
    )

    rows = admin.get("/api/payments/2026-08").json()["affiliates"]
    nour = next(row for row in rows if row["name"] == "Nour Hassan")

    assert nour["destination_changed_at"] is not None


def test_an_untouched_destination_raises_no_warning(admin):
    """A warning that is always on is one nobody reads."""
    _model(admin, "nour@example.com", "Nour Hassan", "NOUR10")

    rows = admin.get("/api/payments/2026-08").json()["affiliates"]
    nour = next(row for row in rows if row["name"] == "Nour Hassan")

    assert nour["destination_changed_at"] is None
