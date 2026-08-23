"""Shopify webhook receipt.

The endpoint does as little as possible: verify the signature, record an
immutable receipt, enqueue the work, return 200. Everything slow happens in the
worker, because Shopify retries any webhook that does not answer quickly.

This is the only public, unauthenticated endpoint on the service. Its signature
is its authentication, and everything it does before verifying is attack
surface - so it does nothing before verifying.
"""

import base64
import hashlib
import hmac
import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.signals import Anomaly
from app.db import engine
from app.main import app
from app.services.shopify.webhooks import MAX_BODY_BYTES, verify_shopify_hmac

SECRET = "test-webhook-secret"


def _sign(body: bytes, secret: str = SECRET) -> str:
    return base64.b64encode(
        hmac.new(secret.encode(), body, hashlib.sha256).digest()
    ).decode()


@pytest.fixture()
def client(fresh_database, monkeypatch):
    monkeypatch.setattr("app.config.settings.shopify_webhook_secret", SECRET)
    monkeypatch.setattr("app.config.settings.worker_enabled", False)
    with TestClient(app) as test_client:
        yield test_client


def _post(
    client, payload, *, event_id="evt-1", topic="orders/create", secret=SECRET
):
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Hmac-Sha256": _sign(body, secret),
        "X-Shopify-Topic": topic,
    }
    if event_id is not None:
        headers["X-Shopify-Webhook-Id"] = event_id
    return client.post("/api/webhooks/shopify", content=body, headers=headers)


def _count(table: str) -> int:
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT count(*) FROM {table}")).scalar()


def _jobs() -> list[tuple]:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT kind, payload, dedupe_key FROM background_job ORDER BY id")
        ).all()


# ── Signature ──────────────────────────────────────────────────────────────────


def test_a_correct_signature_verifies():
    body = b'{"id":1}'
    assert verify_shopify_hmac(body, _sign(body), SECRET) is True


def test_a_wrong_signature_is_rejected():
    assert verify_shopify_hmac(b'{"id":1}', _sign(b'{"id":2}'), SECRET) is False


def test_verification_uses_the_raw_body_not_reserialised_json():
    """Re-serialising changes the bytes and breaks the signature.

    Shopify signs exactly what it sent, whitespace and key order included.
    """
    original = b'{"id": 1,  "name":  "spaced"}'
    signature = _sign(original)
    reserialised = json.dumps(json.loads(original)).encode()
    assert verify_shopify_hmac(original, signature, SECRET) is True
    assert verify_shopify_hmac(reserialised, signature, SECRET) is False


@pytest.mark.parametrize("bad", ["", "not-base64!!", None, "AAAA"])
def test_a_missing_or_malformed_signature_is_rejected_not_crashed(bad):
    assert verify_shopify_hmac(b"{}", bad, SECRET) is False


def test_verification_fails_closed_without_a_secret():
    """An unconfigured secret must reject everything, never accept everything."""
    assert verify_shopify_hmac(b"{}", _sign(b"{}"), "") is False


# ── The endpoint ───────────────────────────────────────────────────────────────


def test_a_signed_webhook_is_accepted(client):
    assert _post(client, {"id": 5123456789}).status_code == 200


def test_an_unsigned_webhook_is_rejected(client):
    response = client.post(
        "/api/webhooks/shopify",
        content=b'{"id":1}',
        headers={"X-Shopify-Webhook-Id": "evt-x", "X-Shopify-Topic": "orders/create"},
    )
    assert response.status_code == 401


def test_a_forged_webhook_is_rejected(client):
    assert _post(client, {"id": 1}, secret="the-wrong-secret").status_code == 401


def test_a_rejected_webhook_records_nothing(client, caplog):
    """Recording unverified requests would let anyone fill an append-only table
    that cannot be pruned. It is reported instead.
    """
    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        _post(client, {"id": 1}, secret="the-wrong-secret")

    assert _count("integration_event") == 0
    assert _count("background_job") == 0
    assert Anomaly.WEBHOOK_REJECTED in caplog.text


def test_the_rejection_does_not_echo_the_body_or_the_secret(client, caplog):
    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        _post(client, {"secret_field": "sensitive-value"}, secret="wrong")

    assert "sensitive-value" not in caplog.text
    assert SECRET not in caplog.text


def test_an_accepted_webhook_records_a_receipt_and_a_job(client):
    _post(client, {"id": 5123456789})

    with engine.connect() as connection:
        event = connection.execute(
            text("SELECT source, topic, external_id, entity_id FROM integration_event")
        ).one()
    assert event == ("shopify", "orders/create", "evt-1", "5123456789")

    kind, payload, _ = _jobs()[0]
    assert kind == "shopify_sync_order"
    assert payload["order_id"] == "5123456789"
    assert payload["reason"] == "orders/create"


def test_the_receipt_names_the_order_it_was_about(client):
    """"Did we ever receive anything for order X?" is the question asked when
    an order goes missing, so the receipt has to be able to answer it.
    """
    _post(client, {"id": 5123456789}, event_id="evt-e")
    with engine.connect() as connection:
        found = connection.execute(
            text("SELECT count(*) FROM integration_event WHERE entity_id = :i"),
            {"i": "5123456789"},
        ).scalar()
    assert found == 1


def test_a_redelivered_webhook_is_acknowledged_but_not_requeued(client):
    """Shopify retries. Processing twice would double-count an order."""
    first = _post(client, {"id": 5123456789}, event_id="evt-dup")
    second = _post(client, {"id": 5123456789}, event_id="evt-dup")

    assert first.status_code == 200
    assert second.status_code == 200
    assert _count("integration_event") == 1
    assert _count("background_job") == 1


# ── One order, several topics ──────────────────────────────────────────────────


def test_the_same_order_arriving_under_three_topics_queues_one_job(client):
    """Shopify sends create, then updated, then paid, within seconds of each
    other. Each is a distinct event and must be recorded - but syncing the same
    order three times fetches the same data three times for the same result.
    """
    _post(client, {"id": 999}, event_id="evt-a", topic="orders/create")
    _post(client, {"id": 999}, event_id="evt-b", topic="orders/updated")
    _post(client, {"id": 999}, event_id="evt-c", topic="orders/fulfilled")

    assert _count("integration_event") == 3, "every delivery is a separate receipt"
    assert _count("background_job") == 1, "but one piece of work"

    _, _, dedupe_key = _jobs()[0]
    assert dedupe_key == "shopify_sync_order:999"


def test_different_orders_queue_separate_jobs(client):
    _post(client, {"id": 111}, event_id="evt-1")
    _post(client, {"id": 222}, event_id="evt-2")
    assert _count("background_job") == 2


# ── Refunds name a different field ─────────────────────────────────────────────


def test_a_refund_webhook_syncs_the_order_not_the_refund(client):
    """A refund payload's `id` is the REFUND's id; the order is in `order_id`.

    Reading `id` here would queue a sync for a number that is not an order -
    which either finds nothing, or finds an unrelated order with that id and
    silently attributes a stranger's money.
    """
    _post(
        client,
        {"id": 77777, "order_id": 5123456789, "note": "returned"},
        event_id="evt-r",
        topic="refunds/create",
    )

    _, payload, dedupe_key = _jobs()[0]
    assert payload["order_id"] == "5123456789", "queued the refund id, not the order"
    assert dedupe_key == "shopify_sync_order:5123456789"


def test_a_refund_and_its_order_collapse_into_one_sync(client):
    _post(client, {"id": 5123456789}, event_id="evt-o", topic="orders/updated")
    _post(
        client,
        {"id": 77777, "order_id": 5123456789},
        event_id="evt-r2",
        topic="refunds/create",
    )
    assert _count("background_job") == 1


# ── Topics and payloads we cannot act on ───────────────────────────────────────


def test_an_unrecognised_topic_is_recorded_but_not_queued(client):
    """Acknowledge it so Shopify stops retrying; do not invent work for it."""
    response = _post(client, {"id": 1}, event_id="evt-t", topic="app/uninstalled")
    assert response.status_code == 200
    assert _count("integration_event") == 1
    assert _count("background_job") == 0


def test_an_order_topic_with_no_usable_id_is_reported(client, caplog):
    """Recorded and acknowledged, but nothing can be done with it - and that is
    worth saying, because it means Shopify's payload is not what we assume.
    """
    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        response = _post(client, {"no_id_here": True}, event_id="evt-n")

    assert response.status_code == 200
    assert _count("integration_event") == 1
    assert _count("background_job") == 0
    assert Anomaly.WEBHOOK_UNUSABLE in caplog.text


def test_a_body_that_is_not_an_object_does_not_crash_the_endpoint(client):
    response = _post(client, [1, 2, 3], event_id="evt-l")
    assert response.status_code == 200
    assert _count("background_job") == 0


def test_a_body_that_is_not_json_is_recorded_not_crashed(client):
    body = b"this is not json"
    response = client.post(
        "/api/webhooks/shopify",
        content=body,
        headers={
            "X-Shopify-Hmac-Sha256": _sign(body),
            "X-Shopify-Topic": "orders/create",
            "X-Shopify-Webhook-Id": "evt-bad",
        },
    )
    assert response.status_code == 200
    assert _count("integration_event") == 1


def test_a_webhook_without_an_id_is_still_processed(client):
    """Absent a delivery id, fall back to a content hash rather than dropping
    it. Two identical bodies then deduplicate, which is the safe direction.
    """
    response = _post(client, {"id": 42}, event_id=None, topic="orders/updated")
    assert response.status_code == 200
    assert _count("integration_event") == 1

    _post(client, {"id": 42}, event_id=None, topic="orders/updated")
    assert _count("integration_event") == 1


# ── Abuse ──────────────────────────────────────────────────────────────────────


def test_an_oversized_body_is_refused_before_it_is_read(client):
    """The only unauthenticated endpoint here. An order payload is a few KB;
    anything near a megabyte is not Shopify.
    """
    body = b"x" * (MAX_BODY_BYTES + 1)
    response = client.post(
        "/api/webhooks/shopify",
        content=body,
        headers={
            "X-Shopify-Hmac-Sha256": _sign(body),
            "X-Shopify-Topic": "orders/create",
            "X-Shopify-Webhook-Id": "evt-big",
        },
    )
    assert response.status_code == 413
    assert _count("integration_event") == 0


def test_a_missing_secret_rejects_everything(client, monkeypatch):
    """Fail closed. An unconfigured secret must never mean "accept anything"."""
    monkeypatch.setattr("app.config.settings.shopify_webhook_secret", "")
    assert _post(client, {"id": 1}).status_code == 401
    assert _count("integration_event") == 0


def test_the_webhook_endpoint_needs_no_session(client):
    """Shopify has no cookie. Its signature is its authentication."""
    assert "hba_session" not in client.cookies
    assert _post(client, {"id": 1}).status_code == 200


# ── Configuration is visible ───────────────────────────────────────────────────


def test_health_reports_whether_webhooks_can_be_received(client, monkeypatch):
    """Without the secret every webhook is rejected and orders stop arriving,
    with nothing but 401s in Shopify's own dashboard to say so.
    """
    body = client.get("/api/health/ready").json()
    assert body["checks"]["shopify"]["webhooks_configured"] is True

    monkeypatch.setattr("app.config.settings.shopify_webhook_secret", "")
    body = client.get("/api/health/ready").json()
    assert body["checks"]["shopify"]["webhooks_configured"] is False
