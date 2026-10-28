"""The address Meta calls (ADR 0059, point 13; the plan's phase 3).

Verify, write it down, queue the work, answer. Like the Shopify receiver, it
is public and unauthenticated, so everything it does before the signature
verifies is attack surface. Every key and number here is made up.
"""

import hashlib
import hmac
import json

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.signals import Anomaly
from app.db import SessionLocal, engine
from app.main import app
from app.modules.inbox.services import connection
from app.modules.inbox.services.meta import NumberInfo

APP_SECRET = "made-up-app-secret-000000009f3c"
CHECK_WORD = "made-up-check-word-0001"
NUMBER_ID = "100200300400500"
URL = "/api/webhooks/meta"

CALLBACK = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "1",
        "changes": [{
            "field": "messages",
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {"phone_number_id": NUMBER_ID},
                "contacts": [{"profile": {"name": "Nour"}, "wa_id": "201005550188"}],
                "messages": [{
                    "from": "201005550188", "id": "wamid.IN1", "timestamp": "1760180000",
                    "type": "text", "text": {"body": "Hello"},
                }],
            },
        }],
    }],
}


@pytest.fixture()
def protected(fresh_database, monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.settings_encryption_key", Fernet.generate_key().decode()
    )
    monkeypatch.setattr("app.config.settings.worker_enabled", False)


@pytest.fixture()
def client(protected):
    with SessionLocal() as db:
        connection.save_whatsapp(
            db,
            phone_number_id=NUMBER_ID,
            business_account_id="777888999000111",
            access_token="EAAG-made-up-access-key-0000a1b2",
            app_secret=APP_SECRET,
            verify_token=CHECK_WORD,
            actor_id=None,
            actor_email=None,
            checker=lambda *args: NumberInfo("+20 100 555 0100", "HBA Wear", "GREEN"),
        )
        db.commit()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def unconnected(protected):
    with TestClient(app) as test_client:
        yield test_client


def _sign(body: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post(client, payload=CALLBACK, *, secret=APP_SECRET, raw: bytes | None = None, signed=True):
    body = raw if raw is not None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if signed:
        headers["X-Hub-Signature-256"] = _sign(body, secret)
    return client.post(URL, content=body, headers=headers)


def _count(table: str) -> int:
    with engine.connect() as connection_:
        return connection_.execute(text(f"SELECT count(*) FROM {table}")).scalar()


def _jobs() -> list[tuple]:
    with engine.connect() as connection_:
        return connection_.execute(
            text("SELECT kind, dedupe_key FROM background_job WHERE kind LIKE 'inbox%' ORDER BY id")
        ).all()


# ── A callback ────────────────────────────────────────────────────────────────


def test_a_signed_callback_is_stored_whole_and_queued(client):
    response = _post(client)
    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}

    with engine.connect() as connection_:
        event_id, digest, payload, processed = connection_.execute(
            text("SELECT id, digest, payload, processed_at FROM meta_webhook_event")
        ).one()
    assert digest == hashlib.sha256(json.dumps(CALLBACK).encode()).hexdigest()
    assert payload == CALLBACK
    assert processed is None
    assert _jobs() == [("inbox_apply_event", f"inbox_apply_event:{event_id}")]


def test_the_receiver_only_writes_it_down(client):
    """Applying is the job's. Nothing is in the chat until the job has run."""
    _post(client)
    assert _count("inbox_message") == 0
    assert _count("inbox_conversation") == 0


def test_a_callback_meta_repeats_is_acknowledged_and_not_queued_again(client):
    first = _post(client)
    second = _post(client)
    assert (first.status_code, second.status_code) == (200, 200)
    assert second.json() == {"status": "duplicate"}
    assert _count("meta_webhook_event") == 1
    assert len(_jobs()) == 1


def test_then_the_job_puts_her_message_in_the_chat(client):
    from app.worker import LANES, run_one

    _post(client)
    with SessionLocal() as db:
        assert run_one(db, "test-worker", only=LANES["inbox"]["only"]) is True
    assert _count("inbox_message") == 1
    with engine.connect() as connection_:
        assert connection_.execute(
            text("SELECT processed_at IS NOT NULL FROM meta_webhook_event")
        ).scalar() is True


# ── What is refused ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "tamper",
    [
        {"signed": False},
        {"secret": "somebody-elses-secret"},
    ],
)
def test_a_callback_meta_did_not_sign_is_refused_and_records_nothing(client, caplog, tamper):
    response = _post(client, **tamper)
    assert response.status_code == 401
    assert _count("meta_webhook_event") == 0
    assert _jobs() == []
    assert Anomaly.WEBHOOK_REJECTED in caplog.text


def test_a_signature_for_other_bytes_is_refused(client):
    body = json.dumps(CALLBACK).encode()
    response = client.post(
        URL, content=body + b" ", headers={"X-Hub-Signature-256": _sign(body)}
    )
    assert response.status_code == 401
    assert _count("meta_webhook_event") == 0


def test_the_refusal_echoes_nothing_of_the_body_or_the_secret(client, caplog):
    response = _post(client, {"entry": "a-marker-in-the-body"}, secret="wrong")
    assert "a-marker-in-the-body" not in response.text
    assert "a-marker-in-the-body" not in caplog.text
    assert APP_SECRET not in caplog.text


def test_with_whatsapp_not_connected_everything_is_refused(unconnected):
    """No app secret must never mean "accept everything"."""
    body = json.dumps(CALLBACK).encode()
    for header in (_sign(body), _sign(body, ""), None):
        headers = {"X-Hub-Signature-256": header} if header else {}
        assert unconnected.post(URL, content=body, headers=headers).status_code == 401
    assert _count("meta_webhook_event") == 0


def test_an_oversized_body_is_refused_before_it_is_read(client):
    from app.shared.api.webhooks import META_MAX_BODY_BYTES

    body = b"x" * (META_MAX_BODY_BYTES + 1)
    response = client.post(URL, content=body, headers={"X-Hub-Signature-256": _sign(body)})
    assert response.status_code == 413
    assert _count("meta_webhook_event") == 0


def test_a_signed_body_that_is_not_a_callback_is_acknowledged_and_not_stored(client, caplog):
    """Refusing it would have Meta retry the same bytes for days."""
    for raw in (b"not json", b"[1, 2, 3]", b'"text"'):
        response = _post(client, raw=raw)
        assert response.status_code == 200
        assert response.json() == {"status": "ignored"}
    assert _count("meta_webhook_event") == 0
    assert Anomaly.WEBHOOK_UNUSABLE in caplog.text


def test_the_address_needs_no_session(client):
    assert _post(client).status_code == 200


# ── Meta's check when the address is set ──────────────────────────────────────


def _verify(client, **params):
    query = {"hub.mode": "subscribe", "hub.verify_token": CHECK_WORD, "hub.challenge": "1158201444"}
    query.update(params)
    return client.get(URL, params={key: value for key, value in query.items() if value is not None})


def test_the_right_check_word_is_answered_with_the_challenge(client):
    response = _verify(client)
    assert response.status_code == 200
    assert response.text == "1158201444"
    assert response.headers["content-type"].startswith("text/plain")


@pytest.mark.parametrize(
    "params",
    [
        {"hub.verify_token": "a-guess"},
        {"hub.verify_token": ""},
        {"hub.verify_token": None},
        {"hub.mode": "unsubscribe"},
        {"hub.challenge": None},
        {"hub.challenge": "9" * 500},
    ],
)
def test_anything_else_is_refused(client, params):
    response = _verify(client, **params)
    assert response.status_code == 403
    assert "1158201444" not in response.text


def test_the_check_is_refused_when_whatsapp_is_not_connected(unconnected):
    assert _verify(unconnected).status_code == 403
    assert _verify(unconnected, **{"hub.verify_token": ""}).status_code == 403
