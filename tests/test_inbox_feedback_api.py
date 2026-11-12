"""The feedback routes, as the screens will call them (ADR 0083, batch C1):
the sheet and its filters, the download, Resolved, the survey beside a chat,
the two chat views, Today, and the settings. Every name, number and order
here is made up.
"""

import io
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import func, select, text

from app.core.businesstime import BUSINESS_TIMEZONE, business_date, business_midnight, utcnow
from app.db import SessionLocal, engine
from app.main import app
from app.modules.inbox.models import (
    FeedbackSettings,
    FeedbackSurvey,
    InboxConversation,
)
from app.modules.inbox.services import feedback, feedback_codes
from app.shared.models.audit import AuditEvent
from app.shared.models.identity import UserAccount

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


def _demote_to(role: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = :r"), {"r": role})
    if role == "operations_manager":
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO role_assignment (user_account_id, role) "
                    "SELECT user_account_id, 'customer_service' FROM role_assignment "
                    "WHERE role = 'operations_manager' AND revoked_at IS NULL"
                )
            )


def at(days_ago: int, hour: int = 12):
    """Midday, Cairo time, that many days ago: never near a day's edge."""
    day = business_date(utcnow()) - timedelta(days=days_ago)
    return business_midnight(day) + timedelta(hours=hour)


def day(days_ago: int) -> str:
    return (business_date(utcnow()) - timedelta(days=days_ago)).isoformat()


def chat(db, phone: str, name: str) -> int:
    conversation = InboxConversation(
        phone=phone, name=name, last_message_at=utcnow(), last_inbound_at=utcnow(),
        last_preview="Hi", last_direction="in", unread_count=0,
    )
    db.add(conversation)
    db.flush()
    return conversation.id


def survey(db, order: str, **fields) -> FeedbackSurvey:
    fields.setdefault("state", "sent")
    fields.setdefault("step", "done")
    row = FeedbackSurvey(shopify_order_id=f"id-{order}", order_name=f"#{order}", **fields)
    db.add(row)
    db.flush()
    return row


@pytest.fixture()
def sheet(client):
    """Six asked orders in six different states, plus a skipped and a waiting
    one that must never be listed. Returns the chats' and surveys' ids."""
    with SessionLocal() as db:
        owner = db.scalar(select(UserAccount))
        nour = chat(db, "201005550101", "Nour Adel")
        salma = chat(db, "201005550102", "Salma Ali")
        habiba = chat(db, "201005550103", "Habiba Samir")
        mona = chat(db, "201005550104", "Mona Fathy")
        farida = chat(db, "201005550105", "Farida Hany")
        loved = survey(
            db, "7001", conversation_id=nour, phone="201005550101", customer_name="Nour",
            courier="Bosta", products=["Linen trousers", "Cotton shirt"],
            delivered_at=at(5), sent_at=at(3), rating="loved", rated_at=at(3),
            reason="quality", comment="Beautiful fabric", reorder="very_likely",
            code="FB-AAAAAA", code_sent_at=at(3), code_expires_at=at(3) + timedelta(days=30),
            code_used_at=at(1), code_order_name="#7100",
        )
        unhappy = survey(
            db, "7002", conversation_id=salma, phone="201005550102", customer_name="Salma",
            courier="Aramex", products=["Wide jeans"], step="support",
            delivered_at=at(4), sent_at=at(2), rating="unhappy", rated_at=at(2),
            reason="size_fit", comment="Too small",
        )
        resolved = survey(
            db, "7003", conversation_id=habiba, phone="201005550103", customer_name="Habiba",
            courier="Bosta", products=["Cotton shirt"], step="solved",
            delivered_at=at(6), sent_at=at(4), rating="unhappy", rated_at=at(4),
            reason="delivery", resolved_at=at(3), resolved_by=owner.id, solved=True, solved_at=at(2),
        )
        reopened = survey(
            db, "7004", conversation_id=mona, phone="201005550104", customer_name="Mona",
            courier="Aramex", products=["Wide jeans", "Linen trousers"], step="support",
            delivered_at=at(7), sent_at=at(5), rating="unhappy", rated_at=at(5),
            reason="wrong_item", resolved_at=None, solved=False, solved_at=at(1),
            reopened_count=1,
        )
        okay = survey(
            db, "7005", conversation_id=farida, phone="201005550105", customer_name="Farida",
            courier="Bosta", products=["Silk scarf"],
            delivered_at=at(3), sent_at=at(1), rating="okay", rated_at=at(1), reason="price",
        )
        failed = survey(
            db, "7006", phone="201005550199", customer_name="Dina", courier="Mylerz",
            products=["Silk scarf"], state="failed", step="rating", delivered_at=at(2),
            sent_at=None, last_error="WhatsApp did not answer",
        )
        survey(db, "7007", state="skipped", skip_reason="cancelled", delivered_at=at(2))
        survey(db, "7008", state="waiting", skip_reason="unanswered_message", delivered_at=at(2))
        db.commit()
        return {
            "nour": nour, "salma": salma, "habiba": habiba, "mona": mona, "farida": farida,
            "loved": loved.id, "unhappy": unhappy.id, "resolved": resolved.id,
            "reopened": reopened.id, "okay": okay.id, "failed": failed.id,
            "owner": owner.id,
        }


def orders(client, **params) -> list[str]:
    body = client.get("/api/inbox/feedback", params=params)
    assert body.status_code == 200, body.text
    return [row["order_name"] for row in body.json()["rows"]]


# ── The sheet ─────────────────────────────────────────────────────────────────


def test_the_sheet_lists_asked_orders_newest_question_first(client, sheet):
    body = client.get("/api/inbox/feedback").json()
    # Skipped and waiting are never listed. The failed one has no sent time, so
    # it is placed by when it was recorded (just now): newest.
    assert [row["order_name"] for row in body["rows"]] == [
        "#7006", "#7005", "#7002", "#7001", "#7003", "#7004",
    ]
    assert body["next_offset"] is None
    assert set(body) == {"rows", "next_offset", "summary", "options", "enabled"}


def test_the_sheet_says_whether_the_questions_are_being_sent(client, sheet, monkeypatch):
    """The screen reads the switch from the sheet itself, so it needs no second
    read, and none that asks Shopify."""
    monkeypatch.setattr("app.config.settings.inbox_feedback_enabled", True)
    assert client.get("/api/inbox/feedback").json()["enabled"] is True
    monkeypatch.setattr("app.config.settings.inbox_feedback_enabled", False)
    assert client.get("/api/inbox/feedback").json()["enabled"] is False
    # Every page carries it, and a narrowed one too.
    assert client.get("/api/inbox/feedback", params={"offset": 4, "rating": "loved"}).json()["enabled"] is False


def test_one_row_has_everything_the_screen_needs(client, sheet):
    row = next(r for r in client.get("/api/inbox/feedback").json()["rows"] if r["order_name"] == "#7003")
    assert row == {
        "id": sheet["resolved"],
        "order_id": "id-7003",
        "order_name": "#7003",
        "asked_at": at(4).isoformat(),
        "delivered_at": at(6).isoformat(),
        "sent_at": at(4).isoformat(),
        "customer_name": "Habiba",
        "phone": "201005550103",
        "products": ["Cotton shirt"],
        "courier": "Bosta",
        "state": "sent",
        "state_label": "Sent",
        "skip_reason": None,
        "last_error": None,
        "step": "solved",
        "rating": "unhappy",
        "rated_at": at(4).isoformat(),
        "reason": "delivery",
        "comment": None,
        "comment_at": None,
        "reorder": None,
        "needs_follow_up": False,
        "resolved_at": at(3).isoformat(),
        "resolved_by": sheet["owner"],
        "resolved_by_name": "Owner",
        "solved": True,
        "solved_at": at(2).isoformat(),
        "reopened_count": 0,
        "code": None,
        "code_sent_at": None,
        "code_expires_at": None,
        "code_used_at": None,
        "code_order_name": None,
    }
    print("ROW", json.dumps(row))


def test_a_code_that_was_used_and_a_question_that_failed(client, sheet):
    rows = {r["order_name"]: r for r in client.get("/api/inbox/feedback").json()["rows"]}
    loved = rows["#7001"]
    assert (loved["code"], loved["code_order_name"]) == ("FB-AAAAAA", "#7100")
    assert loved["code_sent_at"] and loved["code_used_at"]
    failed = rows["#7006"]
    assert failed["state"] == "failed" and failed["state_label"] == "Failed"
    assert failed["last_error"] == "WhatsApp did not answer"
    assert failed["asked_at"]  # recorded, never sent: placed by when it was recorded
    assert failed["rating"] is None


def test_each_filter(client, sheet):
    assert sorted(orders(client, rating="loved")) == ["#7001"]
    assert sorted(orders(client, rating="unhappy")) == ["#7002", "#7003", "#7004"]
    assert sorted(orders(client, reason="delivery")) == ["#7003"]
    assert sorted(orders(client, product="TROUSERS")) == ["#7001", "#7004"]
    assert sorted(orders(client, courier="Aramex")) == ["#7002", "#7004"]
    assert sorted(orders(client, state="needs_follow_up")) == ["#7002", "#7004"]
    assert sorted(orders(client, state="resolved")) == ["#7003"]
    assert sorted(orders(client, state="reopened")) == ["#7004"]
    # Free text: order name, customer name, phone either way round.
    assert orders(client, q="#7005") == ["#7005"]
    assert orders(client, q="7005") == ["#7005"]
    assert orders(client, q="habiba") == ["#7003"]
    assert orders(client, q="201005550104") == ["#7004"]
    assert orders(client, q="01005550104") == ["#7004"]
    assert orders(client, q="nobody") == []
    # A % typed in the box is a letter.
    assert orders(client, product="%") == []


def test_the_dates_are_the_day_she_was_asked(client, sheet):
    # Asked 5, 4, 3, 2 and 1 days ago (+ the failed one, recorded today).
    assert sorted(orders(client, since=day(3), until=day(2))) == ["#7001", "#7002"]
    assert sorted(orders(client, since=day(1))) == ["#7005", "#7006"]
    assert sorted(orders(client, until=day(5))) == ["#7004"]
    assert orders(client, since=day(0), until=day(0)) == ["#7006"]
    both = orders(client, since=day(4), until=day(4), rating="unhappy")
    assert both == ["#7003"]


def test_the_summary_follows_the_filters(client, sheet):
    summary = client.get("/api/inbox/feedback").json()["summary"]
    assert summary == {
        "asked": 5, "answered": 5, "loved": 1, "okay": 1, "unhappy": 3,
        "needs_follow_up": 2, "solved": 1, "codes_sent": 1, "codes_used": 1,
        "not_reached": 1,
    }
    print("SUMMARY", json.dumps(summary))
    narrowed = client.get("/api/inbox/feedback", params={"courier": "Aramex"}).json()["summary"]
    assert narrowed == {
        "asked": 2, "answered": 2, "loved": 0, "okay": 0, "unhappy": 2,
        "needs_follow_up": 2, "solved": 0, "codes_sent": 0, "codes_used": 0,
        "not_reached": 0,
    }


def test_asked_counts_only_questions_that_reached_the_customer(client, sheet):
    with SessionLocal() as db:
        survey(db, "7020", state="no_whatsapp", sent_at=None, delivered_at=at(2))
        survey(db, "7021", state="would_send", sent_at=None, delivered_at=at(2))
        survey(db, "7022", state="pending", sent_at=None, delivered_at=at(2))
        db.commit()
    summary = client.get("/api/inbox/feedback").json()["summary"]
    assert summary["asked"] == 5 and summary["not_reached"] == 3


def test_the_filters_menus(client, sheet):
    options = client.get("/api/inbox/feedback").json()["options"]
    assert options["couriers"] == ["Aramex", "Bosta", "Mylerz"]
    assert options["ratings"] == [
        {"id": "loved", "title": "Loved it"},
        {"id": "okay", "title": "It was okay"},
        {"id": "unhappy", "title": "Not happy"},
    ]
    assert options["reasons"]["unhappy"] == [
        {"id": "size_fit", "title": "Size / fit"}, {"id": "quality", "title": "Quality"},
        {"id": "wrong_item", "title": "Wrong item"}, {"id": "delivery", "title": "Delivery"},
        {"id": "other", "title": "Something else"},
    ]
    assert set(options["reasons"]) == {"loved", "okay", "unhappy"}
    assert [s["id"] for s in options["states"]] == ["needs_follow_up", "resolved", "reopened"]
    print("OPTIONS", json.dumps(options))


def test_paging(client, sheet):
    first = client.get("/api/inbox/feedback", params={"limit": 4}).json()
    assert len(first["rows"]) == 4 and first["next_offset"] == 4
    second = client.get("/api/inbox/feedback", params={"limit": 4, "offset": 4}).json()
    assert len(second["rows"]) == 2 and second["next_offset"] is None
    names = [r["order_name"] for r in first["rows"] + second["rows"]]
    assert len(set(names)) == 6
    # The summary counts the whole filter, not the page.
    assert first["summary"]["asked"] == 5
    assert client.get("/api/inbox/feedback", params={"limit": 0}).status_code == 422
    assert client.get("/api/inbox/feedback", params={"limit": 500}).status_code == 422
    assert client.get("/api/inbox/feedback", params={"rating": "great"}).status_code == 422


# ── The download ──────────────────────────────────────────────────────────────


def test_the_download_is_an_xlsx_of_the_filtered_rows(client, sheet):
    with SessionLocal() as db:
        survey(
            db, "7009", phone="201005550177", customer_name="=HYPERLINK(\"x\")",
            courier="Bosta", products=["Silk scarf"], delivered_at=at(2), sent_at=at(1),
            rating="okay", rated_at=at(1), reason="other", comment="=1+1",
        )
        db.commit()
    response = client.get("/api/inbox/feedback/download", params={"courier": "Bosta"})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    today = utcnow().astimezone(BUSINESS_TIMEZONE).date().isoformat()
    assert response.headers["content-disposition"] == f'attachment; filename="feedback-{today}.xlsx"'
    sheet_ = load_workbook(io.BytesIO(response.content)).active
    lines = list(sheet_.iter_rows(values_only=True))
    assert list(lines[0]) == [
        "Asked", "Customer", "Phone", "Order", "Products", "Courier", "Delivered", "Rating",
        "Reason", "Comment", "Would order again", "Resolved by", "Resolved on", "Solved",
        "Times reopened", "Code", "Code sent", "Code used", "Used on order", "Sending",
        "Problem",
    ]
    body = {line[3]: line for line in lines[1:]}
    assert set(body) == {"#7001", "#7003", "#7005", "#7009"}
    nour = body["#7001"]
    assert nour[1] == "Nour" and nour[2] == "201005550101"
    assert nour[4] == "Linen trousers; Cotton shirt"
    assert (nour[7], nour[8], nour[9], nour[10]) == ("Loved it", "Quality", "Beautiful fabric", "Very likely")
    assert (nour[15], nour[19]) == ("FB-AAAAAA", "Sent")
    assert nour[0].date() == business_date(utcnow()) - timedelta(days=3)  # a real date
    assert nour[17] is not None and nour[18] == "#7100"
    assert body["#7003"][11] == "Owner" and body["#7003"][13] == "Yes"
    # A customer's words are text, never a formula.
    assert body["#7009"][9] == "=1+1" and body["#7009"][1].startswith("=HYPERLINK")


def test_a_download_is_audited_and_carries_no_search_words(client, sheet):
    assert client.get("/api/inbox/feedback/download", params={"q": "habiba", "rating": "unhappy"}).status_code == 200
    with SessionLocal() as db:
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "inbox.feedback_downloaded"))
        assert event is not None and event.department == "inbox"
        assert event.after_json["rows"] == 1
        assert event.after_json["filters"] == {"rating": "unhappy", "q": "given"}
        assert "habiba" not in json.dumps(event.after_json)


def test_a_control_character_in_a_comment_does_not_break_the_download(client, sheet):
    with SessionLocal() as db:
        survey(
            db, "7011", phone="201005550178", customer_name="Sara\x01",
            courier="Bosta", products=["Silk\x0bscarf"], delivered_at=at(2), sent_at=at(1),
            rating="okay", rated_at=at(1), reason="other", comment="fine\x07 =1+1\x1f",
        )
        db.commit()
    response = client.get("/api/inbox/feedback/download", params={"q": "7011"})
    assert response.status_code == 200, response.text
    [row] = list(load_workbook(io.BytesIO(response.content)).active.iter_rows(min_row=2, values_only=True))
    assert row[1] == "Sara" and row[4] == "Silkscarf" and row[9] == "fine =1+1"


def test_dates_out_of_range_or_the_wrong_way_round_are_a_422_in_words(client, sheet):
    for path in ("/api/inbox/feedback", "/api/inbox/feedback/download"):
        far = client.get(path, params={"until": "9999-12-31"})
        assert far.status_code == 422 and "out of range" in far.json()["detail"]
        backwards = client.get(path, params={"since": day(1), "until": day(3)})
        assert backwards.status_code == 422 and "after" in backwards.json()["detail"]
        assert client.get(path, params={"since": day(3), "until": day(3)}).status_code == 200


def test_a_download_of_too_many_rows_asks_for_a_narrower_range(client, sheet, monkeypatch):
    from app.modules.inbox import api

    monkeypatch.setattr(api, "DOWNLOAD_MAX_ROWS", 5)
    ok = client.get("/api/inbox/feedback/download", params={"courier": "Aramex"})
    assert ok.status_code == 200  # 2 rows
    five = client.get("/api/inbox/feedback/download")  # 6 rows
    assert five.status_code == 422 and "narrower date range" in five.json()["detail"]
    monkeypatch.setattr(api, "DOWNLOAD_MAX_ROWS", 6)
    assert client.get("/api/inbox/feedback/download").status_code == 200
    with SessionLocal() as db:  # a refused download is not audited as a download
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "inbox.feedback_downloaded")) == 2


def test_an_empty_download_is_still_a_sheet(client, sheet):
    response = client.get("/api/inbox/feedback/download", params={"q": "nobody"})
    assert response.status_code == 200
    lines = list(load_workbook(io.BytesIO(response.content)).active.iter_rows(values_only=True))
    assert len(lines) == 1


# ── Resolved ──────────────────────────────────────────────────────────────────


def test_resolved_marks_the_follow_up_and_says_who(client, sheet):
    response = client.post(f"/api/inbox/feedback/{sheet['unhappy']}/resolve")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["resolved_by_name"] == "Owner" and body["resolved_at"]
    assert body["needs_follow_up"] is False and body["step"] == "solved"
    row = next(r for r in client.get("/api/inbox/feedback").json()["rows"] if r["id"] == sheet["unhappy"])
    assert row["resolved_by_name"] == "Owner"


def test_resolved_is_refused_in_words(client, sheet):
    assert client.post("/api/inbox/feedback/999999/resolve").status_code == 404
    # Not unhappy.
    refused = client.post(f"/api/inbox/feedback/{sheet['loved']}/resolve")
    assert refused.status_code == 422
    assert "unhappy" in refused.json()["detail"]
    # Already resolved: pressed twice.
    assert client.post(f"/api/inbox/feedback/{sheet['unhappy']}/resolve").status_code == 200
    again = client.post(f"/api/inbox/feedback/{sheet['unhappy']}/resolve")
    assert again.status_code == 422


# ── In the chat ───────────────────────────────────────────────────────────────


def test_the_chat_carries_the_latest_survey(client, sheet):
    detail = client.get(f"/api/inbox/conversations/{sheet['salma']}").json()
    assert detail["feedback"] == {
        "id": sheet["unhappy"],
        "order_name": "#7002",
        "asked_at": at(2).isoformat(),
        "state": "sent",
        "rating": "unhappy",
        "rated_at": at(2).isoformat(),
        "reason": "size_fit",
        "reason_title": "Size / fit",
        "comment": "Too small",
        "reorder": None,
        "step": "support",
        "needs_follow_up": True,
        "resolved_at": None,
        "resolved_by_name": None,
        "solved": None,
        "reopened_count": 0,
        "last_error": None,
        "code": None,
        "code_used": False,
    }
    print("CHAT", json.dumps(detail["feedback"]))
    used = client.get(f"/api/inbox/conversations/{sheet['nour']}").json()["feedback"]
    assert used["code"] == "FB-AAAAAA" and used["code_used"] is True
    resolved = client.get(f"/api/inbox/conversations/{sheet['habiba']}").json()["feedback"]
    assert resolved["resolved_by_name"] == "Owner" and resolved["solved"] is True


def test_a_chat_without_a_survey_says_null(client, sheet):
    with SessionLocal() as db:
        lonely = chat(db, "201005550150", "Lonely")
        db.commit()
    assert client.get(f"/api/inbox/conversations/{lonely}").json()["feedback"] is None


# ── The chat list ─────────────────────────────────────────────────────────────


def _view(client, view: str) -> list[str]:
    body = client.get("/api/inbox/conversations", params={"view": view})
    assert body.status_code == 200, body.text
    return sorted(c["name"] for c in body.json()["conversations"])


def test_the_follow_up_and_neutral_views(client, sheet):
    assert _view(client, "follow_up") == ["Mona Fathy", "Salma Ali"]
    assert _view(client, "neutral") == ["Farida Hany"]
    assert len(_view(client, "all")) == 5


def test_a_neutral_answer_older_than_two_weeks_is_not_neutral(client, sheet):
    with SessionLocal() as db:
        old = chat(db, "201005550160", "Old Okay")
        survey(db, "7010", conversation_id=old, rating="okay", rated_at=at(15), sent_at=at(16),
               reason="price")
        # Latest answered is a newer loved one: not neutral either.
        mixed = chat(db, "201005550161", "Mixed")
        survey(db, "7011", conversation_id=mixed, rating="okay", rated_at=at(5), sent_at=at(6),
               reason="price")
        survey(db, "7012", conversation_id=mixed, rating="loved", rated_at=at(2), sent_at=at(3),
               reason="quality")
        db.commit()
    assert _view(client, "neutral") == ["Farida Hany"]


def test_each_row_wears_a_small_marker(client, sheet):
    body = client.get("/api/inbox/conversations").json()
    markers = {c["name"]: c["feedback"] for c in body["conversations"]}
    assert markers == {
        "Nour Adel": None,
        "Salma Ali": "follow_up",
        "Habiba Samir": None,
        "Mona Fathy": "reopened",
        "Farida Hany": "neutral",
    }
    print("ROWMARK", json.dumps(next(c for c in body["conversations"] if c["name"] == "Salma Ali")))


def test_the_chips_count_follow_up(client, sheet):
    counts = client.get("/api/inbox/conversations").json()["counts"]
    assert counts == {"all": 5, "unread": 0, "edit": 0, "follow_up": 2}
    # Resolving takes the chat out of the chip and the view.
    client.post(f"/api/inbox/feedback/{sheet['unhappy']}/resolve")
    assert client.get("/api/inbox/conversations").json()["counts"]["follow_up"] == 1
    assert _view(client, "follow_up") == ["Mona Fathy"]


# ── Today ─────────────────────────────────────────────────────────────────────


def test_today_says_who_needs_a_follow_up_and_who_was_not_helped(client, sheet):
    body = client.get("/api/today").json()
    items = {item["key"]: item for item in body["items"]}
    follow = items["inbox.feedback_follow_up"]
    assert follow["what"] == "2 unhappy customers need a follow-up"
    assert follow["department"] == "inbox"
    assert follow["go"] == {"label": "Open Chats", "to": "/inbox/chats?view=follow_up"}
    assert follow["when"] == "elapsed" and follow["late"] is True  # asked 2 and 5 days ago
    reopened = items["inbox.feedback_reopened"]
    assert reopened["what"] == "1 customer says their issue was not solved"
    assert reopened["late"] is True
    # The same number as the chat list's chip.
    chips = client.get("/api/inbox/conversations").json()["counts"]
    assert body["counts"]["chats_follow_up"] == chips["follow_up"] == 2
    print("TODAY", json.dumps({"follow": follow, "reopened": reopened, "counts": body["counts"]}))


def test_today_is_quiet_when_nobody_is_waiting(client):
    body = client.get("/api/today").json()
    keys = {item["key"] for item in body["items"]}
    assert "inbox.feedback_follow_up" not in keys and "inbox.feedback_reopened" not in keys
    assert body["counts"]["chats_follow_up"] == 0


def test_a_single_one_is_worded_in_the_singular(client, sheet):
    client.post(f"/api/inbox/feedback/{sheet['unhappy']}/resolve")
    items = {i["key"]: i for i in client.get("/api/today").json()["items"]}
    assert items["inbox.feedback_follow_up"]["what"] == "1 unhappy customer needs a follow-up"


# ── Settings ──────────────────────────────────────────────────────────────────


def test_settings_read(client, monkeypatch):
    monkeypatch.setattr("app.config.settings.inbox_feedback_enabled", True)
    monkeypatch.setattr(feedback_codes, "codes_ready", lambda db: (False, "No permission yet."))
    body = client.get("/api/inbox/feedback/settings").json()
    assert body == {
        "enabled": True, "started_at": None, "review_url": None, "reply_hours": 24,
        "codes_ready": {"ready": False, "reason": "No permission yet."},
    }
    print("SETTINGS", json.dumps(body))
    # Reading never writes the row.
    with SessionLocal() as db:
        assert db.get(FeedbackSettings, 1) is None


def test_settings_read_when_shopify_is_not_connected(client):
    body = client.get("/api/inbox/feedback/settings").json()
    assert body["enabled"] is False
    assert body["codes_ready"]["ready"] is False and body["codes_ready"]["reason"]


def test_an_admin_saves_the_link_and_the_hours(client):
    saved = client.put(
        "/api/inbox/feedback/settings",
        json={"review_url": "https://g.page/r/hba/review", "reply_hours": 48},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {
        "enabled": False, "started_at": None, "review_url": "https://g.page/r/hba/review",
        "reply_hours": 48,
    }
    read = client.get("/api/inbox/feedback/settings").json()
    assert (read["review_url"], read["reply_hours"]) == ("https://g.page/r/hba/review", 48)
    # Only what is sent changes; empty clears the link.
    assert client.put("/api/inbox/feedback/settings", json={"reply_hours": 12}).json()["review_url"] == (
        "https://g.page/r/hba/review"
    )
    cleared = client.put("/api/inbox/feedback/settings", json={"review_url": ""}).json()
    assert cleared["review_url"] is None and cleared["reply_hours"] == 12
    with SessionLocal() as db:
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "inbox.feedback_settings_saved")))
        assert len(events) == 3
        assert events[0].department == "inbox"


@pytest.mark.parametrize(
    "body",
    [
        {"review_url": "http://example.com/review"},
        {"review_url": "example.com/review"},
        {"review_url": "https://"},
        {"review_url": "https://exa mple.com"},
        {"review_url": "https://example.com/" + "a" * 500},
        {"reply_hours": 0},
        {"reply_hours": 73},
        {"reply_hours": None},
    ],
)
def test_settings_that_make_no_sense_are_refused_and_change_nothing(client, body):
    refused = client.put("/api/inbox/feedback/settings", json=body)
    assert refused.status_code == 422
    assert client.get("/api/inbox/feedback/settings").json()["reply_hours"] == 24
    with SessionLocal() as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "inbox.feedback_settings_saved")) is None


def test_the_limits_themselves_are_allowed(client):
    assert client.put("/api/inbox/feedback/settings", json={"reply_hours": 1}).status_code == 200
    assert client.put("/api/inbox/feedback/settings", json={"reply_hours": 72}).status_code == 200
    url = "https://example.com/" + "a" * (500 - len("https://example.com/"))
    assert len(url) == 500
    assert client.put("/api/inbox/feedback/settings", json={"review_url": url}).status_code == 200


# ── Who may do what ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", ["customer_service", "operations_manager"])
def test_customer_service_lists_downloads_and_resolves_but_never_changes_settings(client, sheet, role):
    _demote_to(role)
    assert client.get("/api/inbox/feedback").status_code == 200
    assert client.get("/api/inbox/feedback/download").status_code == 200
    assert client.get("/api/inbox/feedback/settings").status_code == 200
    assert client.post(f"/api/inbox/feedback/{sheet['unhappy']}/resolve").status_code == 200
    assert client.put("/api/inbox/feedback/settings", json={"reply_hours": 12}).status_code == 403
    assert client.get("/api/inbox/conversations", params={"view": "follow_up"}).status_code == 200


@pytest.mark.parametrize("role", ["affiliate_manager", "content_manager", "affiliate"])
def test_a_role_without_the_inbox_gets_nothing(client, sheet, role):
    _demote_to(role)
    assert client.get("/api/inbox/feedback").status_code == 403
    assert client.get("/api/inbox/feedback/download").status_code == 403
    assert client.get("/api/inbox/feedback/settings").status_code == 403
    assert client.post(f"/api/inbox/feedback/{sheet['unhappy']}/resolve").status_code == 403
    assert client.put("/api/inbox/feedback/settings", json={"reply_hours": 12}).status_code == 403
    assert client.get("/api/inbox/conversations", params={"view": "neutral"}).status_code == 403


def test_nobody_signed_out_reaches_the_feedback(fresh_database):
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/inbox/feedback").status_code == 401
        assert anonymous.get("/api/inbox/feedback/download").status_code == 401
        assert anonymous.get("/api/inbox/feedback/settings").status_code == 401


def test_the_new_view_is_refused_nowhere_but_unknown_views_are(client, sheet):
    assert client.get("/api/inbox/conversations", params={"view": "follow_up"}).status_code == 200
    assert client.get("/api/inbox/conversations", params={"view": "angry"}).status_code == 422
