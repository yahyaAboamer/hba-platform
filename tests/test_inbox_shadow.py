"""The silent run checked against n8n (ADR 0059; the plan's phase 2).

Every order and number here is made up.
"""

import io
import json
from datetime import datetime, timedelta, timezone

from app.models.inbox import OrderConfirmation
from app.services.inbox import shadow
from app.services.inbox.confirmations import BAD_PHONE, PAID

DAY = datetime(2026, 10, 12, tzinfo=timezone.utc)


def _row(db, order_id, state, *, placed=DAY + timedelta(hours=3), why=None):
    db.add(
        OrderConfirmation(
            shopify_order_id=order_id,
            order_name=f"#{order_id}",
            state=state,
            last_error=why,
            placed_at=placed,
            phone="201005550188" if state == "would_send" else None,
            customer_name="Nour" if state == "would_send" else None,
        )
    )
    db.flush()


def test_when_both_would_message_the_same_orders_they_agree(db):
    _row(db, "1", "would_send")
    _row(db, "2", "would_send")
    _row(db, "3", "not_needed", why=PAID)
    result = shadow.compare(db, ["1", "2"], since=DAY)
    assert (result["n8n_sent"], result["we_would_send"], result["agree"]) == (2, 2, 2)
    assert result["only_n8n"] == [] and result["only_us"] == []
    assert result["our_states"] == {"not_needed": 1, "would_send": 2}


def test_an_order_n8n_messaged_and_we_would_not_says_what_we_decided_and_why(db):
    """The dangerous direction: at the switch this customer would hear nothing."""
    _row(db, "1", "would_send")
    _row(db, "2", "bad_phone", why=BAD_PHONE)
    result = shadow.compare(db, ["1", "2", "9"], since=DAY)
    assert result["agree"] == 1
    assert result["only_n8n"] == [
        {"order_id": "2", "order": "#2", "ours": "bad_phone", "why": BAD_PHONE},
        {"order_id": "9", "order": None, "ours": "not_seen", "why": None},
    ]


def test_an_order_we_would_message_and_n8n_did_not_is_listed(db):
    _row(db, "1", "would_send")
    _row(db, "2", "would_send")
    result = shadow.compare(db, ["1"], since=DAY)
    assert result["only_us"] == [{"order_id": "2", "order": "#2"}]


def test_only_orders_placed_in_the_window_are_ours_to_compare(db):
    _row(db, "1", "would_send", placed=DAY - timedelta(hours=1))
    _row(db, "2", "would_send")
    _row(db, "3", "would_send", placed=DAY + timedelta(days=1, hours=1))
    result = shadow.compare(db, ["2"], since=DAY, until=DAY + timedelta(days=1))
    assert (result["we_would_send"], result["agree"]) == (1, 1)
    assert result["only_us"] == []


def test_the_report_carries_no_name_phone_or_message(db):
    _row(db, "1", "would_send")
    _row(db, "2", "would_send")
    report = json.dumps(shadow.compare(db, ["1"], since=DAY))
    assert "201005550188" not in report
    assert "Nour" not in report


def test_blank_lines_and_spaces_in_n8ns_list_are_ignored(db):
    _row(db, "1", "would_send")
    result = shadow.compare(db, ["1", "", " 1 ", "\n"], since=DAY)
    assert (result["n8n_sent"], result["agree"]) == (1, 1)


def test_run_by_hand_it_prints_the_report_and_fails_on_a_difference(db, monkeypatch, capsys):
    _row(db, "1", "would_send")
    _row(db, "2", "would_send")

    class _Session:
        def __enter__(self):
            return db

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("app.db.SessionLocal", lambda: _Session())

    monkeypatch.setattr("sys.stdin", io.StringIO("1\n2\n"))
    assert shadow.main(["--since", "2026-10-12"]) == 0
    assert json.loads(capsys.readouterr().out)["agree"] == 2

    monkeypatch.setattr("sys.stdin", io.StringIO("1\n"))
    assert shadow.main(["--since", "2026-10-12", "--until", "2026-10-13"]) == 1
    assert json.loads(capsys.readouterr().out)["only_us"] == [{"order_id": "2", "order": "#2"}]
