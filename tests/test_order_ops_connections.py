"""The Bosta and E-stebdal keys in Settings (ADR 0057 §10; build plan phase 6).

The same rules as the Shopify connection: saved encrypted, tried against the
provider before saving, never shown, logged or audited - and a refused key
leaves the one in use as it was. No provider is called: the check is
replaced, or a mock transport stands in.
"""

import json

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.db import SessionLocal, engine
from app.main import app
from app.modules.operations.models import OpsIntegrationKey
from app.modules.operations.services import bosta, connections, estebdal
from app.modules.operations.services.polling import KeyRefused, SourceUnavailable

BOSTA_KEY = "bosta-read-only-key-0000a1b2"
ESTEBDAL_KEY = "estebdal-key-00000000009f3c"


@pytest.fixture()
def protected(monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.settings_encryption_key", Fernet.generate_key().decode()
    )
    monkeypatch.setattr("app.config.settings.bosta_api_key", "")
    monkeypatch.setattr("app.config.settings.estebdal_api_key", "")


def _accept(provider, key):
    return None


def _refuse(provider, key):
    raise KeyRefused("Bosta refused the key.")


def _save(db, provider, key, checker=_accept):
    return connections.save(db, provider, key, actor_id=None, actor_email=None, checker=checker)


# ── Which key is in use ───────────────────────────────────────────────────────


def test_with_no_key_anywhere_there_is_none(db, protected):
    found = connections.effective(db, "bosta")
    assert (found.key, found.source) == ("", None)
    assert connections.describe(db, "bosta")["hint"] is None


def test_the_servers_own_key_is_used_until_one_is_saved(db, protected, monkeypatch):
    monkeypatch.setattr("app.config.settings.estebdal_api_key", ESTEBDAL_KEY)
    described = connections.describe(db, "estebdal")
    assert described["source"] == "environment"
    assert described["hint"] == "ends in 9f3c"
    assert connections.api_key(db, "estebdal") == ESTEBDAL_KEY


def test_a_saved_key_wins_over_the_servers(db, protected, monkeypatch):
    monkeypatch.setattr("app.config.settings.bosta_api_key", "the-servers-own-key-9999")
    _save(db, "bosta", BOSTA_KEY)
    assert connections.api_key(db, "bosta") == BOSTA_KEY
    assert connections.describe(db, "bosta")["source"] == "saved"


def test_a_saved_key_this_server_cannot_read_falls_back_and_says_so(db, protected, monkeypatch):
    _save(db, "bosta", BOSTA_KEY)
    monkeypatch.setattr(
        "app.config.settings.settings_encryption_key", Fernet.generate_key().decode()
    )
    monkeypatch.setattr("app.config.settings.bosta_api_key", "the-servers-own-key-9999")

    found = connections.effective(db, "bosta")

    assert found.source == "environment"
    assert found.key == "the-servers-own-key-9999"
    assert "cannot be read" in found.problem


def test_the_reads_use_the_key_in_use(db, protected, monkeypatch):
    _save(db, "estebdal", ESTEBDAL_KEY)
    seen = []

    def handler(request):
        seen.append(request.headers["x-api-key"])
        return httpx.Response(200, json={"data": [], "meta": {"hasNextPage": False}})

    real = estebdal.EstebdalClient

    def client(key, **kwargs):
        return real(key, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(estebdal, "EstebdalClient", client)
    estebdal.read(db)
    assert seen == [ESTEBDAL_KEY]


# ── Saving one ────────────────────────────────────────────────────────────────


def test_a_saved_key_is_stored_encrypted_with_its_last_four(db, protected):
    described = _save(db, "bosta", BOSTA_KEY)
    row = db.get(OpsIntegrationKey, "bosta")
    assert BOSTA_KEY not in row.secret_encrypted
    assert row.hint == "a1b2"
    assert described["hint"] == "ends in a1b2"
    assert described["verified_at"] is not None
    assert BOSTA_KEY not in json.dumps(described)


def test_a_refused_key_is_not_saved_and_the_one_in_use_stays(db, protected):
    _save(db, "bosta", BOSTA_KEY)
    with pytest.raises(connections.KeyNotSaved) as refused:
        _save(db, "bosta", "a-wrong-key-zzzz9999", checker=_refuse)
    assert str(refused.value) == (
        "Bosta did not accept this key (Bosta refused the key.). The key in use has not changed."
    )
    assert "a-wrong-key" not in str(refused.value)
    assert connections.api_key(db, "bosta") == BOSTA_KEY


@pytest.mark.parametrize(
    ("key", "message"),
    [
        ("", "Enter the Bosta key."),
        ("two words", "doesn't look like"),
        ("x" * 600, "doesn't look like"),
        ("key-with-a-“smart”-quote-1234", "doesn't look like"),
        ("key-with-a-tab	-1234567", "doesn't look like"),
    ],
)
def test_a_key_that_is_not_one_is_refused_before_asking(db, protected, key, message):
    asked = []
    with pytest.raises(connections.KeyNotSaved, match=message):
        _save(db, "bosta", key, checker=lambda *args: asked.append(args))
    assert asked == []


def test_nothing_is_saved_without_an_encryption_key(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.settings_encryption_key", "")
    with pytest.raises(connections.KeyNotSaved, match="SETTINGS_ENCRYPTION_KEY is not set"):
        _save(db, "bosta", BOSTA_KEY)
    assert db.scalar(select(OpsIntegrationKey)) is None


# ── The one read that proves a key ────────────────────────────────────────────


def test_the_bosta_check_is_one_small_search_with_the_key():
    seen = []

    def handler(request):
        seen.append((request.headers["authorization"], json.loads(request.content)))
        return httpx.Response(200, json={"data": {"deliveries": []}})

    client = bosta.BostaClient(BOSTA_KEY, transport=httpx.MockTransport(handler))
    client.check()
    assert seen == [(BOSTA_KEY, {"limit": 1, "page": 1})]


def test_the_estebdal_check_needs_a_real_answer():
    client = estebdal.EstebdalClient(
        ESTEBDAL_KEY,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"oops": 1})),
    )
    with pytest.raises(SourceUnavailable):
        client.check()


# ── Through the API ───────────────────────────────────────────────────────────

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "quiet-harbour-lantern",
}


@pytest.fixture()
def client(fresh_database, protected, monkeypatch):
    monkeypatch.setattr(connections, "check", _accept)
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _audit_text() -> str:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT action, before_json::text, after_json::text FROM audit_event "
                "WHERE action = 'order_ops.key_saved'"
            )
        ).all()
    return json.dumps([list(map(str, row)) for row in rows])


def test_an_admin_saves_a_key_and_never_sees_it_again(client):
    saved = client.put("/api/order-ops/connections/bosta", json={"key": BOSTA_KEY})
    read = client.get("/api/order-ops/connections/bosta")

    assert saved.status_code == 200, saved.text
    assert read.json()["source"] == "saved"
    assert read.json()["hint"] == "ends in a1b2"
    for body in (saved.text, read.text, _audit_text()):
        assert BOSTA_KEY not in body
    assert "order_ops.key_saved" in _audit_text()


def test_a_refused_key_is_a_422_in_words(client, monkeypatch):
    monkeypatch.setattr(connections, "check", _refuse)
    response = client.put("/api/order-ops/connections/bosta", json={"key": "a-wrong-key-zzzz9999"})
    assert response.status_code == 422
    assert "The key in use has not changed." in response.json()["detail"]
    assert "a-wrong-key" not in response.text


def test_an_overlong_key_is_refused_without_echoing_it(client):
    response = client.put("/api/order-ops/connections/bosta", json={"key": "k" * 600})
    assert response.status_code == 422
    assert "k" * 600 not in response.text
    assert "doesn't look like" in response.json()["detail"]


def test_an_unknown_provider_is_refused(client):
    assert client.get("/api/order-ops/connections/aramex").status_code == 422


@pytest.mark.parametrize("role", ["operations_manager", "affiliate_manager", "content_manager"])
def test_only_an_admin_reaches_the_keys(client, role):
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = :r"), {"r": role})
    assert client.get("/api/order-ops/connections/bosta").status_code == 403
    assert (
        client.put("/api/order-ops/connections/bosta", json={"key": BOSTA_KEY}).status_code == 403
    )
    with SessionLocal() as session:
        assert session.scalar(select(OpsIntegrationKey)) is None
