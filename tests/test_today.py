"""Today (Phase 2, batch 2.2): what waits for a person, everywhere they work.

Each department's items for each kind of person, and nothing from a department
the person does not hold; the order of the items; the week's orders adding up;
**Today and each department's own screen giving the same number**; one
department failing leaving the others; a model refused. Every name, number and
order here is made up.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.businesstime import BUSINESS_TIMEZONE, business_month, month_add, utcnow
from app.core.passwords import hash_password
from app.db import SessionLocal, engine
from app.main import app
from app.modules.affiliates.models.affiliates import AffiliateProfile
from app.modules.affiliates.models.targets import MonthlyTarget
from app.modules.affiliates.services.targets import targets_not_set
from app.modules.inbox.models import (
    InboxConnection,
    InboxConversation,
    InboxMessage,
    OrderConfirmation,
)
from app.modules.operations.models import OpsBostaDelivery, OpsShopifyOrder
from app.modules.operations.services import freshness
from app.shared.api import today as today_api
from app.shared.api.today import today_body
from app.shared.models.identity import RoleAssignment, UserAccount
from app.shared.models.orders import OrderIndex
from app.shared.services import order_week

NOW = utcnow()
PASSWORD = "quiet-harbour-lantern"


def _cairo(year, month, day, hour=12, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=BUSINESS_TIMEZONE).astimezone(timezone.utc)


# ── Seeding ───────────────────────────────────────────────────────────────────


def _person(db, email: str, *roles: str) -> UserAccount:
    user = UserAccount(email=email, password_hash="x", status="active", display_name=email)
    db.add(user)
    db.flush()
    for role in roles:
        db.add(RoleAssignment(user_account_id=user.id, role=role))
    db.flush()
    return user


def _model(db, name: str, *, status="active", kind="model", created_at=None, start=None) -> AffiliateProfile:
    account = UserAccount(
        email=f"{name.lower().replace(' ', '.')}@example.com", password_hash="x", status="active"
    )
    db.add(account)
    db.flush()
    profile = AffiliateProfile(
        user_account_id=account.id, name=name, status=status, account_kind=kind,
        collaboration_start_month=start,
    )
    if created_at is not None:
        profile.created_at = created_at
    db.add(profile)
    db.flush()
    return profile


def _connected(db) -> None:
    db.add(
        InboxConnection(
            id=1, phone_number_id="100200300400500", business_account_id="777888999000111",
            access_token_encrypted="x", app_secret_encrypted="x", verify_token_encrypted="x",
            access_token_hint="a1b2", app_secret_hint="9f3c", verified_at=NOW,
        )
    )
    db.flush()


def _chat(db, phone: str, *, unread=0) -> InboxConversation:
    conversation = InboxConversation(
        phone=phone, name="Nour", last_message_at=NOW, last_inbound_at=NOW,
        last_preview="Hello", last_direction="in", unread_count=unread,
    )
    db.add(conversation)
    db.flush()
    return conversation


def _message(db, conversation, at, *, direction="in", kind="text", **fields) -> InboxMessage:
    message = InboxMessage(
        conversation_id=conversation.id, direction=direction, kind=kind, body="Hello",
        status="received" if direction == "in" else "sent",
        origin="customer" if direction == "in" else "automatic", occurred_at=at, **fields,
    )
    db.add(message)
    db.flush()
    return message


def _confirmation(
    db, order_id, conversation=None, *, state="sent", answer=None, answered_at=None, placed_at=None
):
    row = OrderConfirmation(
        shopify_order_id=order_id, order_name=f"#{order_id}", state=state, answer=answer,
        answered_at=answered_at, conversation_id=conversation.id if conversation else None,
        phone="201005550188", customer_name="Nour", total_text="1450.00", placed_at=placed_at or NOW,
    )
    db.add(row)
    db.flush()
    return row


def _shopify_open(db, order_id: str, placed_at, *tags: str) -> None:
    db.add(
        OpsShopifyOrder(
            shopify_order_id=order_id, order_number=f"#{order_id}", placed_at=placed_at,
            tags=list(tags), fulfillment_status="UNFULFILLED", seen_at=NOW,
        )
    )
    db.flush()


def _indexed(db, order_id: str, placed_at, **fields) -> OrderIndex:
    row = OrderIndex(
        shopify_order_id=order_id, order_number=f"#{order_id}", placed_at=placed_at,
        business_month=business_month(placed_at), **fields,
    )
    db.add(row)
    db.flush()
    return row


def _at(value: str | None) -> datetime | None:
    """An ISO time from the response, as an instant (the database may answer
    in another offset than the test wrote)."""
    return datetime.fromisoformat(value) if value else None


def _keys(body) -> list[str]:
    return [item["key"] for item in body["items"]]


def _departments(body) -> set[str]:
    return {item["department"] for item in body["items"]}


@pytest.fixture()
def everything(db):
    """Something waiting in every department."""
    freshness.record_success(db, "bosta", 10, at=NOW - timedelta(hours=3))
    freshness.record_failure(db, "bosta", "Bosta didn't answer.", at=NOW - timedelta(minutes=5))
    freshness.record_success(db, "shopify", 2, at=NOW)
    _shopify_open(db, "5001", NOW - timedelta(hours=30), "Confirmed ✅", "bosta_sync_failed")
    chat = _chat(db, "201005550101", unread=1)
    _message(db, chat, NOW - timedelta(minutes=20))
    _model(db, "Salma Applied", status="pending", created_at=NOW - timedelta(days=3))
    _model(db, "Nour Active")
    return db


# ── Who sees what ─────────────────────────────────────────────────────────────


def test_the_owner_sees_every_department(everything):
    db = everything
    body = today_body(db, _person(db, "owner@example.com", "admin"), NOW)

    assert body["departments"] == ["inbox", "operations", "affiliates"]
    assert _departments(body) == {"inbox", "operations", "affiliates"}
    assert set(body["counts"]) == {
        "chats_unread", "models_awaiting_approval", "payments_awaiting_approval"
    }
    assert {k: _at(v) for k, v in body["failures"].items()} == {"bosta": NOW - timedelta(hours=3)}
    assert body["orders"] is not None
    assert body["unread"] == []


def test_customer_service_sees_only_the_inbox(everything):
    db = everything
    body = today_body(db, _person(db, "cs@example.com", "customer_service"), NOW)

    assert body["departments"] == ["inbox"]
    assert _departments(body) == {"inbox"}
    assert set(body["counts"]) == {"chats_unread"}
    assert body["failures"] == {}
    assert body["orders"] is None


def test_the_operations_manager_sees_inbox_operations_and_the_week(everything):
    db = everything
    body = today_body(db, _person(db, "ops@example.com", "operations_manager", "customer_service"), NOW)

    assert body["departments"] == ["inbox", "operations"]
    assert _departments(body) == {"inbox", "operations"}
    assert set(body["counts"]) == {"chats_unread"}
    assert body["orders"] is not None
    # WhatsApp is not connected here: he holds Operations, so it opens there.
    whatsapp = next(i for i in body["items"] if i["key"] == "inbox.whatsapp_not_connected")
    assert whatsapp["go"] == {"label": "Open WhatsApp", "to": "/operations/whatsapp"}


def test_the_affiliate_manager_sees_no_inbox_or_operations(everything):
    db = everything
    body = today_body(db, _person(db, "am@example.com", "affiliate_manager"), NOW)

    assert body["departments"] == ["affiliates"]
    assert _departments(body) == {"affiliates"}
    assert "affiliates.applications" in _keys(body)
    assert "affiliates.payments_awaiting_approval" in _keys(body)
    assert body["orders"] is None


def test_the_content_manager_gets_no_payments_item(everything):
    db = everything
    body = today_body(db, _person(db, "content@example.com", "content_manager"), NOW)

    assert "affiliates.applications" in _keys(body)
    assert "affiliates.payments_awaiting_approval" not in _keys(body)
    # The sidebar's Payments number stays, as /api/operations/counts gave it.
    assert "payments_awaiting_approval" in body["counts"]


def test_customer_service_alone_is_sent_to_chats_for_whatsapp(db):
    body = today_body(db, _person(db, "cs@example.com", "customer_service"), NOW)

    whatsapp = next(i for i in body["items"] if i["key"] == "inbox.whatsapp_not_connected")
    assert whatsapp["broken"] is True
    assert whatsapp["since"] is None and whatsapp["when"] is None
    assert whatsapp["go"] == {"label": "Open Chats", "to": "/inbox/chats"}


# ── Operations ────────────────────────────────────────────────────────────────


def test_a_failed_source_says_since_its_last_good_read(db):
    now = _cairo(2026, 10, 25, 12, 23)
    freshness.record_success(db, "bosta", 10, at=_cairo(2026, 10, 25, 9, 40))
    freshness.record_failure(db, "bosta", "Bosta didn't answer.", at=_cairo(2026, 10, 25, 12, 20))
    freshness.record_failure(db, "estebdal", "E-stebdal didn't answer.", at=_cairo(2026, 10, 24, 14, 20))
    body = today_body(db, _person(db, "ops@example.com", "operations_manager"), now)

    bosta = next(i for i in body["items"] if i["key"] == "operations.source_failed.bosta")
    assert _at(bosta.pop("since")) == _cairo(2026, 10, 25, 9, 40)
    assert bosta == {
        "key": "operations.source_failed.bosta",
        "department": "operations",
        "broken": True,
        "late": True,
        "what": "Bosta has not been read since 09:40",
        "detail": "Its last try failed at 12:20. Its screen shows the last good read.",
        "due": None,
        "when": "elapsed",
        "go": {"label": "Open Bosta", "to": "/operations/bosta"},
    }
    never = next(i for i in body["items"] if i["key"] == "operations.source_failed.estebdal")
    assert never["what"] == "E-stebdal could not be read"
    assert never["detail"].startswith("Its last try failed yesterday at 14:20.")
    assert _at(never["since"]) == _cairo(2026, 10, 24, 14, 20)
    assert {k: _at(v) for k, v in body["failures"].items()} == {
        "bosta": _cairo(2026, 10, 25, 9, 40), "estebdal": None
    }


def test_stale_never_and_unconnected_sources_are_not_items(db):
    freshness.record_success(db, "shopify", 1, at=NOW - timedelta(hours=5))
    freshness.record_not_connected(db, "bosta")
    body = today_body(db, _person(db, "ops@example.com", "operations_manager"), NOW)

    assert not [k for k in _keys(body) if k.startswith("operations.source_failed")]
    assert body["failures"] == {}


def test_confirmed_orders_that_never_reached_bosta_are_the_shopify_card(db):
    freshness.record_success(db, "shopify", 3, at=NOW)
    _shopify_open(db, "5001", NOW - timedelta(hours=30), "Confirmed ✅", "bosta_sync_failed")
    _shopify_open(db, "5002", NOW - timedelta(hours=2), "bosta_sync_failed")
    # Cancelled ones count only on their own card, as on the tab.
    _shopify_open(db, "5003", NOW - timedelta(days=4), "bosta_sync_failed", "Cancelled ❌")
    body = today_body(db, _person(db, "ops@example.com", "operations_manager"), NOW)

    item = next(i for i in body["items"] if i["key"] == "operations.bosta_sync_failed")
    assert item["what"] == "2 confirmed orders never reached Bosta"
    assert item["detail"] == "They will not be picked up until they are sent again"
    assert _at(item["since"]) == (NOW - timedelta(hours=30))
    assert item["when"] == "since" and item["late"] is True and item["broken"] is False
    assert item["go"] == {"label": "Open", "to": "/operations/shopify"}


def test_no_shopify_card_without_numbers_to_show(db):
    _shopify_open(db, "5001", NOW, "bosta_sync_failed")
    body = today_body(db, _person(db, "ops@example.com", "operations_manager"), NOW)

    assert "operations.bosta_sync_failed" not in _keys(body)


# ── Inbox ─────────────────────────────────────────────────────────────────────


def test_customers_waiting_are_counted_from_their_unread_messages(db):
    _connected(db)
    now = _cairo(2026, 10, 25, 12, 0)
    first = _chat(db, "201005550101", unread=2)
    _message(db, first, _cairo(2026, 10, 25, 8, 0))  # read before: not waiting
    _message(db, first, _cairo(2026, 10, 25, 9, 40))  # unread, the oldest
    _message(db, first, _cairo(2026, 10, 25, 9, 50), direction="out")
    _message(db, first, _cairo(2026, 10, 25, 10, 0), kind="reaction")  # never counted
    _message(db, first, _cairo(2026, 10, 25, 11, 0))  # unread
    second = _chat(db, "201005550102", unread=1)
    _message(db, second, _cairo(2026, 10, 25, 11, 30))
    read = _chat(db, "201005550103", unread=0)
    _message(db, read, _cairo(2026, 10, 25, 7, 0))
    body = today_body(db, _person(db, "cs@example.com", "customer_service"), now)

    item = next(i for i in body["items"] if i["key"] == "inbox.waiting_for_reply")
    assert item["what"] == "2 customers are waiting for a reply"
    assert item["detail"] == "The oldest wrote at 09:40"
    assert _at(item["since"]) == _cairo(2026, 10, 25, 9, 40)
    assert item["when"] == "elapsed" and item["late"] is True
    assert item["go"] == {"label": "Open Chats", "to": "/inbox/chats"}
    assert body["counts"] == {"chats_unread": 2}


def test_one_customer_waiting_and_not_yet_late(db):
    _connected(db)
    chat = _chat(db, "201005550101", unread=1)
    _message(db, chat, NOW - timedelta(minutes=20))
    body = today_body(db, _person(db, "cs@example.com", "customer_service"), NOW)

    item = next(i for i in body["items"] if i["key"] == "inbox.waiting_for_reply")
    assert item["what"] == "1 customer is waiting for a reply"
    assert item["late"] is False


def test_customers_who_asked_for_a_change(db):
    """Confirmations' *Change* card as it opens: the last 7 days' orders whose
    customer answered Change and that Shopify has not shipped or cancelled."""
    _connected(db)
    first = NOW - timedelta(hours=26)
    _confirmation(db, "7001", _chat(db, "201005550101"), answer="edit", answered_at=first)
    _confirmation(db, "7002", _chat(db, "201005550102"), answer="edit", answered_at=NOW - timedelta(hours=3))
    # Placed ten days ago: no longer on the card, however it was answered.
    _confirmation(
        db, "7003", _chat(db, "201005550103"), answer="edit",
        answered_at=NOW - timedelta(days=10), placed_at=NOW - timedelta(days=10),
    )
    # Shipped since: Shopify settled it, so it left the card.
    _confirmation(db, "7004", _chat(db, "201005550104"), answer="edit", answered_at=NOW - timedelta(hours=5))
    _indexed(db, "7004", NOW, fulfillment_status="fulfilled")
    body = today_body(db, _person(db, "cs@example.com", "customer_service"), NOW)

    item = next(i for i in body["items"] if i["key"] == "inbox.wants_a_change")
    assert item["what"] == "2 customers asked to change their order"
    assert item["detail"] == "They answered Change on the confirmation message"
    assert item["go"] == {"label": "Open", "to": "/inbox/confirmations?card=edit"}
    assert _at(item["since"]) == first
    assert item["when"] == "since" and item["late"] is True


def test_a_change_dealt_with_long_ago_is_not_waiting(db):
    """Chats' *Wants a change* view keeps a chat whose latest answer was ever
    Change; Today does not count it once the order has left the card."""
    _connected(db)
    _confirmation(
        db, "7101", _chat(db, "201005550111"), answer="edit",
        answered_at=NOW - timedelta(days=40), placed_at=NOW - timedelta(days=40),
    )
    body = today_body(db, _person(db, "cs@example.com", "customer_service"), NOW)

    assert "inbox.wants_a_change" not in {i["key"] for i in body["items"]}


def test_whatsapp_gone_quiet_is_broken(db):
    _connected(db)
    chat = _chat(db, "201005550101")
    sent = NOW - timedelta(minutes=40)
    _message(db, chat, sent, direction="out", wa_message_id="wamid.made-up-1")
    body = today_body(db, _person(db, "cs@example.com", "customer_service"), NOW)

    item = next(i for i in body["items"] if i["key"] == "inbox.whatsapp_quiet")
    assert item["broken"] is True and item["when"] == "elapsed"
    assert _at(item["since"]) == sent
    assert item["what"].startswith("WhatsApp has been quiet since ")
    assert item["detail"] == "Messages went out and nothing has come back"


# ── Affiliates ────────────────────────────────────────────────────────────────


def test_applications_to_review(db):
    now = _cairo(2026, 10, 25, 12, 0)
    _model(db, "Salma", status="pending", created_at=_cairo(2026, 10, 22, 9, 0))
    _model(db, "Habiba", status="pending", created_at=_cairo(2026, 10, 25, 9, 0))
    _model(db, "Nour")
    body = today_body(db, _person(db, "am@example.com", "affiliate_manager"), now)

    item = next(i for i in body["items"] if i["key"] == "affiliates.applications")
    assert item["what"] == "2 model applications to review"
    assert item["detail"] == "The oldest arrived on 22 Oct"
    assert _at(item["since"]) == _cairo(2026, 10, 22, 9, 0)
    assert item["late"] is True and item["when"] == "elapsed"
    assert item["go"] == {"label": "Review", "to": "/affiliates/models?segment=applications"}
    assert body["counts"]["models_awaiting_approval"] == 2


def test_next_months_targets_from_the_24th(db):
    for name in ("Nour", "Salma", "Habiba"):
        _model(db, name)
    _model(db, "HBA10", kind="house")
    _model(db, "Later", start="2027-01")
    _model(db, "Gone", status="archived")
    _model(db, "Declined", status="declined")
    person = _person(db, "content@example.com", "content_manager")

    before = today_body(db, person, _cairo(2026, 11, 23, 12, 0))
    assert "affiliates.targets_not_set" not in _keys(before)

    on = today_body(db, person, _cairo(2026, 11, 24, 12, 0))
    item = next(i for i in on["items"] if i["key"] == "affiliates.targets_not_set")
    assert item["what"] == "December targets are not set"
    assert item["detail"] == "3 models on the Targets list; December starts Tuesday"
    assert item["due"] == "2026-12-01" and item["when"] == "deadline"
    assert item["late"] is False
    assert item["go"] == {"label": "Set targets", "to": "/affiliates/targets?month=2026-12"}


def test_targets_set_for_some_and_late_near_the_month(db):
    nour = _model(db, "Nour")
    _model(db, "Salma")
    db.add(MonthlyTarget(affiliate_id=nour.id, month="2026-12", required_videos=4, required_stories=8))
    db.flush()
    body = today_body(db, _person(db, "am@example.com", "affiliate_manager"), _cairo(2026, 11, 28, 12, 0))

    item = next(i for i in body["items"] if i["key"] == "affiliates.targets_not_set")
    assert item["what"] == "December targets are not set for 1 model"
    assert item["late"] is True


def test_payments_waiting_for_approval_on_the_payments_month(db):
    from app.modules.affiliates.services.payroll import working_month

    _model(db, "Nour")
    body = today_body(db, _person(db, "am@example.com", "affiliate_manager"), NOW)

    item = next(i for i in body["items"] if i["key"] == "affiliates.payments_awaiting_approval")
    month = working_month()
    assert item["what"] == "1 payment waiting for approval"
    assert item["go"]["to"] == f"/affiliates/payments?month={month}"
    assert item["when"] is None and item["since"] is None
    assert body["counts"]["payments_awaiting_approval"] == 1


# ── The order of the list ─────────────────────────────────────────────────────


def test_broken_first_then_the_longest_waiting(db):
    now = _cairo(2026, 10, 25, 12, 0)
    freshness.record_success(db, "shopify", 1, at=_cairo(2026, 10, 25, 11, 0))
    freshness.record_failure(db, "shopify", "Shopify didn't answer.", at=_cairo(2026, 10, 25, 11, 55))
    _shopify_open(db, "5001", _cairo(2026, 10, 20, 9, 0), "bosta_sync_failed")
    chat = _chat(db, "201005550101", unread=1)
    _message(db, chat, _cairo(2026, 10, 25, 10, 0))
    _model(db, "Salma", status="pending", created_at=_cairo(2026, 10, 23, 9, 0))
    _model(db, "Nour")
    body = today_body(db, _person(db, "owner@example.com", "admin"), now)

    assert _keys(body) == [
        # Broken: WhatsApp has no time, so after the failed source.
        "operations.source_failed.shopify",
        "inbox.whatsapp_not_connected",
        # Then oldest first.
        "operations.bosta_sync_failed",
        "affiliates.applications",
        "inbox.waiting_for_reply",
        # Then those with no time, in department order.
        "affiliates.targets_not_set",
        "affiliates.payments_awaiting_approval",
    ]


# ── Orders, last 7 days ───────────────────────────────────────────────────────


def test_the_weeks_rows_add_up_to_the_orders_placed(db):
    now = _cairo(2026, 10, 25, 12, 0)
    day = _cairo(2026, 10, 23, 10, 0)
    chat = _chat(db, "201005550101")
    # cancelled: four ways
    _indexed(db, "1", day, cancelled_at=day)
    _indexed(db, "2", day, financial_status="refunded")
    _indexed(db, "3", day, delivery_state="failed")
    _indexed(db, "4", day)
    _confirmation(db, "4", chat, answer="cancelled", answered_at=day)
    # delivered
    _indexed(db, "5", day, delivery_state="delivered")
    # with Bosta: on the mirror, or fulfilled in Shopify
    _indexed(db, "6", day)
    db.add(
        OpsBostaDelivery(
            bosta_id="b6", tracking_number="t6", type_value="Send", state_code=10,
            created_at=day, shopify_order_number="#6", unfinished=True, synced_at=now,
        )
    )
    _indexed(db, "7", day, fulfillment_status="fulfilled")
    # waiting: sent and unanswered, or asked for a change
    _indexed(db, "8", day)
    _confirmation(db, "8", chat)
    _indexed(db, "9", day)
    _confirmation(db, "9", chat, answer="edit", answered_at=day)
    # confirmed, or paid (no confirmation needed)
    _indexed(db, "10", day)
    _confirmation(db, "10", chat, answer="confirmed", answered_at=day)
    _indexed(db, "11", day)
    _confirmation(db, "11", chat, state="not_needed")
    # never asked: no confirmation, or it could not be sent
    _indexed(db, "12", day)
    _indexed(db, "13", day)
    _confirmation(db, "13", chat, state="failed")
    # A deleted Bosta order is not with Bosta.
    _indexed(db, "14", day)
    db.add(
        OpsBostaDelivery(
            bosta_id="b14", tracking_number="t14", type_value="Send", state_code=10,
            created_at=day, shopify_order_number="#14", unfinished=True, synced_at=now,
            deleted_at=now,
        )
    )
    # Outside the week: before 00:00 Cairo six days ago.
    _indexed(db, "15", _cairo(2026, 10, 18, 23, 59))
    db.flush()

    week = order_week.week(db, now)

    assert week["from"] == "2026-10-19" and week["to"] == "2026-10-25"
    rows = {row["key"]: row["count"] for row in week["rows"]}
    assert rows == {
        "waiting": 2, "confirmed": 2, "with_bosta": 2, "delivered": 1,
        "cancelled": 4, "not_asked": 3,
    }
    assert sum(rows.values()) == week["placed"] == 14
    assert [row["key"] for row in week["rows"]] == [
        "waiting", "confirmed", "with_bosta", "delivered", "cancelled", "not_asked"
    ]
    assert [row["department"] for row in week["rows"]] == [
        "Inbox", "Operations", "Operations", "", "Operations", "Inbox"
    ]


def test_not_asked_is_left_out_when_empty_and_bosta_has_a_time(db):
    now = _cairo(2026, 10, 25, 12, 0)
    freshness.record_success(db, "bosta", 1, at=_cairo(2026, 10, 25, 9, 38))
    _indexed(db, "1", _cairo(2026, 10, 25, 9, 0), delivery_state="delivered")

    week = order_week.week(db, now)

    assert "not_asked" not in [row["key"] for row in week["rows"]]
    assert week["placed"] == 1
    assert _at(week["bosta_as_of"]) == _cairo(2026, 10, 25, 9, 38)


# ── One department failing ────────────────────────────────────────────────────


def test_one_department_failing_leaves_the_others(everything, monkeypatch):
    db = everything

    def broken(session, permissions, now):
        session.execute(text("SELECT * FROM no_such_table"))

    departments = tuple(
        (name, permission, broken if name == "inbox" else reader)
        for name, permission, reader in today_api.DEPARTMENTS
    )
    monkeypatch.setattr(today_api, "DEPARTMENTS", departments)
    body = today_body(db, _person(db, "owner@example.com", "admin"), NOW)

    assert body["unread"] == ["inbox"]
    assert "inbox" not in _departments(body)
    assert {"operations", "affiliates"} <= _departments(body)
    # Absent, never a made-up 0.
    assert "chats_unread" not in body["counts"]
    assert "models_awaiting_approval" in body["counts"]
    # The session survived the failed query: the week was read after it.
    assert body["orders"] is not None


# ── Over HTTP: Today against each screen, and who may ask ─────────────────────


@pytest.fixture()
def owner(fresh_database):
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/bootstrap",
            json={"email": "owner@example.com", "display_name": "Owner", "password": PASSWORD},
        )
        assert response.status_code == 201, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield client


def test_today_and_each_screen_give_the_same_number(owner, monkeypatch):
    with SessionLocal() as db:
        freshness.record_success(db, "shopify", 2, at=NOW)
        _shopify_open(db, "5001", NOW - timedelta(hours=30), "bosta_sync_failed")
        _shopify_open(db, "5002", NOW - timedelta(hours=3), "bosta_sync_failed")
        _shopify_open(db, "5003", NOW - timedelta(hours=3), "No answer")
        for n, unread in enumerate((2, 1, 0, 3)):
            chat = _chat(db, f"20100555010{n}", unread=unread)
            for minutes in range(4):
                _message(db, chat, NOW - timedelta(minutes=10 * (minutes + 1)))
            if n < 2:
                _confirmation(db, f"70{n}", chat, answer="edit", answered_at=NOW - timedelta(hours=n + 1))
        _model(db, "Salma", status="pending", created_at=NOW - timedelta(days=3))
        _model(db, "HBA20", status="pending", kind="house", created_at=NOW - timedelta(days=1))
        nour = _model(db, "Nour")
        _model(db, "Habiba")
        _model(db, "HBA10", kind="house")
        next_month = month_add(business_month(NOW), 1)
        db.add(MonthlyTarget(affiliate_id=nour.id, month=next_month, required_videos=4, required_stories=8))
        db.commit()

    body = owner.get("/api/today").json()
    items = {item["key"]: item for item in body["items"]}

    # Chats: its Unread view. Confirmations: its Change card.
    chips = owner.get("/api/inbox/conversations").json()["counts"]
    assert body["counts"]["chats_unread"] == chips["unread"] == 3
    assert items["inbox.waiting_for_reply"]["what"].startswith(f"{chips['unread']} customers")
    card = owner.get("/api/inbox/confirmations").json()["tiles"]["edit"]
    assert card == 2
    assert items["inbox.wants_a_change"]["what"].startswith(f"{card} customers")

    # Shopify: the bosta_sync_failed card.
    card = next(
        c for c in owner.get("/api/order-ops/shopify").json()["cards"] if c["key"] == "bosta_sync_failed"
    )
    assert items["operations.bosta_sync_failed"]["what"].startswith(f"{card['count']} confirmed")

    # Models: the Applications segment (the roster's pending, house included).
    roster = owner.get("/api/affiliates?include_archived=true").json()["affiliates"]
    segment = sum(1 for row in roster if row["status"] == "pending")
    assert body["counts"]["models_awaiting_approval"] == segment == 2
    assert items["affiliates.applications"]["what"].startswith(f"{segment} model")

    # Payments: Awaiting approval on the month the screen opens on.
    from app.modules.affiliates.services.payroll import working_month

    desk = owner.get(f"/api/payments/{working_month()}").json()["affiliates"]
    not_approved = sum(1 for row in desk if row["state"] == "not_approved")
    assert body["counts"]["payments_awaiting_approval"] == not_approved
    assert items["affiliates.payments_awaiting_approval"]["what"].startswith(f"{not_approved} payment")

    # The sidebar's old numbers agree too.
    counts = owner.get("/api/operations/counts").json()
    assert counts == {
        "models_awaiting_approval": body["counts"]["models_awaiting_approval"],
        "payments_awaiting_approval": body["counts"]["payments_awaiting_approval"],
    }

    # Targets: the grid's open rows with no target.
    grid = owner.get(f"/api/targets/{next_month}").json()["rows"]
    empty = sum(
        1 for row in grid
        if row["account_kind"] != "house" and not row["before_start"] and row["required_videos"] is None
    )
    with SessionLocal() as db:
        # Salma (an application) and Habiba; Nour has hers; the house code is off.
        assert targets_not_set(db, next_month) == (empty, 3)
    assert empty == 2


def test_a_model_may_not_read_today(owner):
    with engine.begin() as connection:
        user_id = connection.execute(
            text(
                "INSERT INTO user_account (email, password_hash, status) "
                "VALUES ('nour@example.com', :p, 'active') RETURNING id"
            ),
            {"p": hash_password(PASSWORD)},
        ).scalar_one()
        connection.execute(
            text("INSERT INTO role_assignment (user_account_id, role) VALUES (:u, 'affiliate')"),
            {"u": user_id},
        )
    owner.cookies.clear()
    signed_in = owner.post("/api/auth/login", json={"email": "nour@example.com", "password": PASSWORD})
    assert signed_in.status_code == 200, signed_in.text
    owner.headers["X-CSRF-Token"] = signed_in.json()["csrf"]

    assert owner.get("/api/today").status_code == 403


def test_signed_out_is_refused(fresh_database):
    with TestClient(app) as client:
        assert client.get("/api/today").status_code == 401


def test_a_customer_who_answered_cancel_and_then_took_the_parcel_was_delivered():
    """The answer counts as the cancellation only until the parcel arrives:
    a delivered order is delivered, whatever was tapped before."""
    from types import SimpleNamespace

    def order(**facts):
        base = dict(
            cancelled_at=None,
            financial_status="pending",
            delivery_state=None,
            fulfillment_status=None,
            return_activity=None,
            return_open=False,
        )
        return SimpleNamespace(**{**base, **facts})

    answered_cancel = ("sent", "cancelled")
    assert order_week.where_it_is(order(delivery_state="delivered"), answered_cancel, True) == "delivered"
    assert order_week.where_it_is(order(), answered_cancel, False) == "cancelled"
    assert order_week.where_it_is(order(), answered_cancel, True) == "cancelled"
    # A cancellation in Shopify still wins over delivered.
    assert (
        order_week.where_it_is(order(delivery_state="delivered", cancelled_at=utcnow()), None, True)
        == "cancelled"
    )
