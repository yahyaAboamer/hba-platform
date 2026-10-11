"""The inbox's routes, as the screens will call them (ADR 0059; the plan's
phase 3). Who reaches each, and what a refusal looks like. Every name, number
and order here is made up.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.businesstime import utcnow
from app.db import SessionLocal, engine
from app.main import app
from app.models.inbox import InboxConversation, InboxMessage, OrderConfirmation

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "quiet-harbour-lantern",
}


@pytest.fixture()
def client(fresh_database, monkeypatch):
    monkeypatch.setattr("app.config.settings.worker_enabled", False)
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


@pytest.fixture()
def chat(client) -> int:
    """One customer, one message from her, one order that failed to send."""
    with SessionLocal() as db:
        conversation = InboxConversation(
            phone="201005550188", name="Nour Adel", last_message_at=utcnow(),
            last_inbound_at=utcnow(), last_preview="Hello", last_direction="in", unread_count=1,
        )
        db.add(conversation)
        db.flush()
        db.add(InboxMessage(
            conversation_id=conversation.id, direction="in", kind="text", body="Hello",
            wa_message_id="wamid.HERS", status="received", origin="customer", occurred_at=utcnow(),
        ))
        db.add(OrderConfirmation(
            shopify_order_id="5001", order_name="#31044", state="failed", phone="201005550188",
            customer_name="Nour", conversation_id=conversation.id, placed_at=utcnow(),
            last_error="WhatsApp did not answer",
        ))
        db.commit()
        return conversation.id


def _demote_to(role: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = :r"), {"r": role})


# ── Reading ───────────────────────────────────────────────────────────────────


def test_the_list_the_chat_and_its_orders(client, chat):
    listed = client.get("/api/inbox/conversations").json()
    assert [row["name"] for row in listed["conversations"]] == ["Nour Adel"]
    assert listed["counts"] == {"all": 1, "unread": 1, "edit": 0}
    assert listed["next"] is None

    detail = client.get(f"/api/inbox/conversations/{chat}").json()
    assert detail["phone"] == "201005550188"
    assert [order["order"] for order in detail["orders"]] == ["#31044"]

    messages = client.get(f"/api/inbox/conversations/{chat}/messages").json()
    assert [message["body"] for message in messages["messages"]] == ["Hello"]


def test_a_search_and_a_view_go_through(client, chat):
    assert client.get("/api/inbox/conversations", params={"q": "#31044"}).json()["conversations"]
    assert client.get("/api/inbox/conversations", params={"view": "edit"}).json()["conversations"] == []
    assert client.get("/api/inbox/conversations", params={"view": "everything"}).status_code == 422
    assert client.get("/api/inbox/conversations", params={"before": "nonsense"}).status_code == 422


def test_a_chat_that_is_not_there_is_a_404(client):
    assert client.get("/api/inbox/conversations/987654").status_code == 404
    assert client.get("/api/inbox/conversations/987654/messages").status_code == 404
    assert client.post("/api/inbox/conversations/987654/read").status_code == 404
    assert client.post("/api/inbox/confirmations/987654/send-again").status_code == 404


def test_marking_read_clears_the_count_and_is_kept(client, chat):
    assert client.post(f"/api/inbox/conversations/{chat}/read").json()["unread_count"] == 0
    assert client.get("/api/inbox/conversations").json()["counts"]["unread"] == 0


# ── Sending ───────────────────────────────────────────────────────────────────


def test_a_reply_is_refused_with_the_reason_when_this_server_may_not_send(client, chat):
    """No WhatsApp connection here. 409, in words, and nothing in the chat."""
    refused = client.post(f"/api/inbox/conversations/{chat}/messages", json={"body": "Hi"})
    assert refused.status_code == 409
    assert refused.json()["detail"] == "WhatsApp is not connected."
    assert len(client.get(f"/api/inbox/conversations/{chat}/messages").json()["messages"]) == 1


def test_an_empty_reply_is_a_422(client, chat):
    refused = client.post(f"/api/inbox/conversations/{chat}/messages", json={"body": "  "})
    assert refused.status_code == 422
    assert "Type a message" in refused.json()["detail"]


def test_send_again_is_refused_while_this_server_may_not_send(client, chat):
    refused = client.post("/api/inbox/confirmations/5001/send-again")
    assert refused.status_code == 422
    assert refused.json()["detail"] == "WhatsApp is not connected."


def test_staff_record_her_answer_and_it_is_kept(client, chat):
    answered = client.post("/api/inbox/confirmations/5001/answer", json={"answer": "confirmed"})
    assert answered.status_code == 200
    assert (answered.json()["answer"], answered.json()["tag"]) == ("confirmed", "Confirmed ✅")
    cards = client.get("/api/inbox/confirmations", params={"tile": "confirmed"}).json()
    assert cards["tiles"]["confirmed"] == 1
    assert [order["customer"] for order in cards["orders"]] == ["Nour"]
    assert client.post("/api/inbox/confirmations/5001/answer", json={"answer": "refunded"}).status_code == 422


# ── Who reaches what ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("role", "inbox", "operations"),
    [
        ("admin", 200, 200),
        ("customer_service", 200, 403),
        ("operations_manager", 200, 200),
        ("affiliate_manager", 403, 403),
        ("content_manager", 403, 403),
        ("affiliate", 403, 403),
    ],
)
def test_customer_details_are_in_the_inbox_and_only_for_those_who_hold_it(
    client, chat, role, inbox, operations
):
    if role != "admin":
        _demote_to(role)
    assert client.get("/api/inbox/conversations").status_code == inbox
    assert client.get(f"/api/inbox/conversations/{chat}/messages").status_code == inbox
    assert client.get("/api/inbox/confirmations").status_code == inbox
    assert client.post("/api/inbox/confirmations/5001/answer", json={"answer": "confirmed"}).status_code == inbox
    assert client.get("/api/order-ops/whatsapp").status_code == operations


def test_operations_whatsapp_tab_names_the_order_and_never_the_customer(client, chat):
    body = client.get("/api/order-ops/whatsapp", params={"card": "failed"})
    assert body.status_code == 200
    assert body.json()["cards"]["failed"] == 1
    assert body.json()["orders"][0]["order"] == "#31044"
    assert "201005550188" not in body.text
    assert "Nour" not in body.text


def test_nobody_signed_out_reads_a_chat(fresh_database):
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/inbox/conversations").status_code == 401
        assert anonymous.get("/api/order-ops/whatsapp").status_code == 401
