"""The Shopify connection saved from Settings (owner, decision b).

Only authorised staff change it; the secret is stored encrypted and never
appears in a response, a log line or the audit trail; a failed update leaves
the working connection exactly as it was. A fake Shopify answers - nothing here
reaches a shop.
"""
import logging

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import engine
from app.main import app
from app.services.shopify.client import REQUIRED_SCOPES, ShopifyError

BOOTSTRAP = {"email": "owner@example.com", "display_name": "Owner", "password": "quiet-harbour-lantern"}
SECRET = "shpss_the-real-secret-9f3a7c21"
NEW_SECRET = "shpss_a-newer-secret-55d0e8b4"
URL = "/api/operations/shopify-connection"
FORM = {"shop_domain": "hbawear.myshopify.com", "client_id": "client-id-1234abcd", "client_secret": SECRET}


@pytest.fixture()
def client(fresh_database, monkeypatch):
    monkeypatch.setattr("app.config.settings.settings_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr("app.config.settings.shopify_shop_domain", "")
    monkeypatch.setattr("app.config.settings.shopify_client_id", "")
    monkeypatch.setattr("app.config.settings.shopify_client_secret", "")
    monkeypatch.setattr("app.config.settings.shopify_access_token", "")
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _shopify(monkeypatch, *, answers=True, scopes=REQUIRED_SCOPES, seen=None):
    """Stand in for Shopify's answer to `{ shop { name } }`."""

    def check(domain, client_id, secret):
        if seen is not None:
            seen.append((domain, client_id, secret))
        if not answers:
            raise ShopifyError("Shopify rejected the credentials (401)")
        return "HBA Wear", set(scopes)

    monkeypatch.setattr("app.services.shopify.connection.check", check)


def _stored():
    with engine.connect() as connection:
        return connection.execute(text("select * from shopify_connection")).mappings().all()


def _audit_text():
    with engine.connect() as connection:
        rows = connection.execute(text("select action, before_json::text, after_json::text from audit_event")).all()
    return " ".join(" ".join(str(part) for part in row) for row in rows)


def test_a_working_connection_is_saved_encrypted_and_never_shown(client, monkeypatch, caplog):
    _shopify(monkeypatch)
    caplog.set_level(logging.DEBUG)

    response = client.put(URL, json=FORM)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "saved" and body["shop_domain"] == "hbawear.myshopify.com"
    assert body["secret_saved"] is True and body["client_id_hint"] == "••••abcd"
    assert SECRET not in response.text

    [row] = _stored()
    assert row["client_secret_encrypted"] != SECRET and SECRET not in row["client_secret_encrypted"]
    # It is still the secret, once decrypted with the server's key.
    from app.config import settings
    assert Fernet(settings.settings_encryption_key.encode()).decrypt(row["client_secret_encrypted"].encode()).decode() == SECRET

    assert SECRET not in client.get(URL).text
    assert SECRET not in _audit_text() and "shopify.connection_updated" in _audit_text()
    assert SECRET not in caplog.text


def test_the_saved_connection_is_the_one_every_client_uses(client, monkeypatch):
    _shopify(monkeypatch)
    client.put(URL, json=FORM)

    from app.services.shopify.sync import build_client

    built = build_client()
    assert built.shop_domain == "hbawear.myshopify.com"
    assert built._client_id == FORM["client_id"] and built._client_secret == SECRET


def test_a_refused_connection_changes_nothing(client, monkeypatch):
    _shopify(monkeypatch)
    client.put(URL, json=FORM)
    before = _stored()

    _shopify(monkeypatch, answers=False)
    response = client.put(URL, json={**FORM, "client_secret": NEW_SECRET})

    assert response.status_code == 422
    assert "has not changed" in response.json()["detail"]
    assert NEW_SECRET not in response.text
    assert _stored() == before


def test_missing_scopes_are_refused_and_named(client, monkeypatch):
    _shopify(monkeypatch, scopes=REQUIRED_SCOPES - {"read_all_orders"})

    response = client.put(URL, json=FORM)

    assert response.status_code == 422
    assert "read_all_orders" in response.json()["detail"]
    assert _stored() == []


def test_a_blank_secret_keeps_the_saved_one(client, monkeypatch):
    seen = []
    _shopify(monkeypatch, seen=seen)
    client.put(URL, json=FORM)

    response = client.put(URL, json={**FORM, "client_secret": ""})

    assert response.status_code == 200
    assert seen[-1][2] == SECRET  # the saved secret was tested again, not an empty one
    assert "secret kept" in _audit_text()


def test_a_blank_client_id_keeps_the_saved_one(client, monkeypatch):
    seen = []
    _shopify(monkeypatch, seen=seen)
    client.put(URL, json=FORM)

    response = client.put(URL, json={"shop_domain": FORM["shop_domain"], "client_id": "", "client_secret": ""})

    assert response.status_code == 200
    assert seen[-1][1:] == (FORM["client_id"], SECRET)


def test_a_first_save_needs_the_secret(client, monkeypatch):
    _shopify(monkeypatch)
    response = client.put(URL, json={**FORM, "client_secret": ""})
    assert response.status_code == 422 and _stored() == []


def test_without_an_encryption_key_nothing_is_saved(client, monkeypatch):
    monkeypatch.setattr("app.config.settings.settings_encryption_key", "")
    _shopify(monkeypatch)

    response = client.put(URL, json=FORM)

    assert response.status_code == 422
    assert "SETTINGS_ENCRYPTION_KEY" in response.json()["detail"]
    assert _stored() == []
    assert client.get(URL).json()["can_save"] is False


def test_only_authorised_staff_see_or_change_it(client, monkeypatch):
    _shopify(monkeypatch)
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = 'affiliate_manager'"))

    assert client.get(URL).status_code == 403
    assert client.put(URL, json=FORM).status_code == 403
    assert _stored() == []


def test_a_saved_connection_the_key_cannot_read_falls_back_to_the_environment(client, monkeypatch):
    _shopify(monkeypatch)
    client.put(URL, json=FORM)
    monkeypatch.setattr("app.config.settings.settings_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr("app.config.settings.shopify_shop_domain", "env-shop.myshopify.com")
    monkeypatch.setattr("app.config.settings.shopify_client_id", "env-id")
    monkeypatch.setattr("app.config.settings.shopify_client_secret", "env-secret")

    body = client.get(URL).json()

    assert body["source"] == "environment" and body["shop_domain"] == "env-shop.myshopify.com"
    assert "cannot be read" in body["problem"]


def test_a_domain_that_is_not_a_shop_is_refused_in_plain_words(client, monkeypatch):
    seen = []
    _shopify(monkeypatch, seen=seen)
    response = client.put(URL, json={**FORM, "shop_domain": "hbawear.store"})
    assert response.status_code == 422
    assert "your-store.myshopify.com" in response.json()["detail"]
    assert seen == [] and _stored() == []  # Shopify was not even asked

