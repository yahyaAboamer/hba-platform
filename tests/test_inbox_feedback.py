"""Post-delivery feedback, the first half (ADR 0083): who is asked, the first
question, and the interactive messages that carry the rest.

Meta and Shopify are never called: mock transports answer and record what was
asked. Every order, name and number here is made up.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.businesstime import utcnow
from app.modules.inbox.models import (
    FeedbackSettings,
    FeedbackSurvey,
    InboxConversation,
    InboxMessage,
)
from app.modules.inbox.services import events, feedback, feedback_replies, outbound
from app.modules.inbox.services.feedback import (
    decide,
    due_orders,
    requeue_stale_pending,
    send_first_question,
    sweep,
)
from app.modules.inbox.services.meta import MAX_BODY, MetaClient, MetaError
from app.modules.operations.models import OpsEstebdalReturn, OpsRefund
from app.shared.services.jobs import INBOX_WORK, JobKind, PermanentFailure
from app.shared.services.schedule import SCHEDULE
from tests.feedback_support import (  # noqa: F401  (fixtures)
    HER,
    NUMBER_ID,
    TOKEN,
    conversation,
    connected,
    feature_on,
    jobs,
    may_send,
    message,
    meta,
    node,
    order,
    shopify,
    started,
    survey,
)


def _yes(survey_id: int) -> bool:
    return True


# ── Who is due ────────────────────────────────────────────────────────────────


def test_a_delivered_order_two_days_on_is_due(db):
    started(db)
    due = order(db, delivered_ago=timedelta(days=2, hours=1))
    assert due_orders(db) == [due]


@pytest.mark.parametrize(
    "changes",
    [
        {"delivery_state": "in_flight"},
        {"delivery_state": None},
        {"delivered_at": None},
        {"cancelled_at": utcnow()},
        {"financial_status": "REFUNDED"},
        {"financial_status": "voided"},
        {"return_open": True},
        {"return_activity": True},
    ],
)
def test_an_order_that_is_not_a_clean_delivery_is_not_due(db, changes):
    """No delivered date, cancelled, refunded or voided, or any return in Shopify."""
    started(db)
    order(db, **changes)
    assert due_orders(db) == []


@pytest.mark.parametrize(
    ("ago", "due"),
    [
        (timedelta(days=1, hours=23), False),
        (timedelta(days=2, minutes=1), True),
        (timedelta(days=6, hours=23), True),
        (timedelta(days=7, hours=1), False),
    ],
)
def test_it_is_asked_two_days_after_delivery_and_not_after_seven(db, ago, due):
    started(db, days_ago=30)
    row = order(db, delivered_ago=ago)
    assert (due_orders(db) == [row]) is due


def test_nothing_delivered_before_the_feature_was_switched_on_is_due(db):
    feedback.get_settings(db).started_at = utcnow() - timedelta(hours=60)
    order(db, "old", delivered_ago=timedelta(days=3))
    after = order(db, "new", delivered_ago=timedelta(hours=49))
    assert due_orders(db) == [after]


def test_nothing_is_due_before_the_feature_has_ever_run(db):
    order(db)
    assert due_orders(db) == []


def test_an_order_already_decided_is_never_due_again(db):
    started(db)
    row = order(db)
    survey(db, row.shopify_order_id, state="skipped", step="done", skip_reason="no_phone")
    assert due_orders(db) == []


# ── The sweep ─────────────────────────────────────────────────────────────────


def test_nothing_happens_with_the_flag_off(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.inbox_feedback_enabled", False)
    order(db)
    asked: list = []
    # The handler reads no order and makes no client: it returns first.
    feedback._handle_sweep(db, {})
    assert asked == []
    assert db.query(FeedbackSettings).count() == 0
    assert db.query(FeedbackSurvey).count() == 0
    assert jobs(db) == []


def test_the_first_run_switched_on_records_when_it_began_and_asks_about_nothing_earlier(db, feature_on):
    when = utcnow()
    delivered = order(db, delivered_ago=timedelta(days=3))
    asked: list = []

    assert sweep(db, now=when, client=shopify({"7001": node()}, asked)) == 0

    assert db.get(FeedbackSettings, 1).started_at == when
    assert asked == []
    assert db.query(FeedbackSurvey).count() == 0
    assert delivered.delivered_at < when


def test_an_order_delivered_after_it_began_is_decided_two_days_on(db, feature_on):
    began = utcnow()
    sweep(db, now=began, client=shopify({}))
    order(db, delivered_ago=-timedelta(hours=1))  # delivered an hour after it began

    assert sweep(db, now=began + timedelta(days=1), client=shopify({"7001": node()})) == 0
    assert sweep(db, now=began + timedelta(days=3), client=shopify({"7001": node()})) == 1
    assert db.scalar(select(FeedbackSurvey.state)) == "pending"


def test_the_sweep_queues_a_send_for_each_order_to_be_asked_and_not_for_skipped_ones(db, feature_on):
    started(db)
    order(db, "7001")
    order(db, "7002")
    sent_to_her = shopify({"7001": node(), "7002": node(name="#7002", phone="not a number", customer={"firstName": "Sara"}, shippingAddress=None)})

    assert sweep(db, client=sent_to_her) == 2

    rows = {row.shopify_order_id: row for row in db.query(FeedbackSurvey)}
    assert (rows["7001"].state, rows["7002"].state) == ("pending", "skipped")
    assert [(kind, key) for kind, key, _ in jobs(db, JobKind.INBOX_FEEDBACK_SEND)] == [
        (JobKind.INBOX_FEEDBACK_SEND, f"{JobKind.INBOX_FEEDBACK_SEND}:{rows['7001'].id}:0"),
    ]


def test_a_second_sweep_looks_at_nothing_again(db, feature_on):
    started(db)
    order(db)
    assert sweep(db, client=shopify({"7001": node()})) == 1
    asked: list = []
    assert sweep(db, client=shopify({"7001": node()}, asked)) == 0
    assert asked == []
    assert len(jobs(db, JobKind.INBOX_FEEDBACK_SEND)) == 1


def test_a_shopify_outage_stops_the_sweep_and_keeps_what_was_decided(db, feature_on):
    import httpx

    from app.shared.services.shopify.client import ShopifyClient

    started(db)
    order(db, "7001", delivered_ago=timedelta(days=4))
    order(db, "7002", delivered_ago=timedelta(days=3))
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(200, json={"data": {"order": node()}})
        raise httpx.ConnectError("down")

    client = ShopifyClient(
        shop_domain="hba-test.myshopify.com", access_token="shpat_test",
        api_version="2026-07", transport=httpx.MockTransport(handler),
    )
    client.retry_base_seconds = 0
    assert sweep(db, client=client) == 1
    assert [row.shopify_order_id for row in db.query(FeedbackSurvey)] == ["7001"]


def test_the_sweep_is_scheduled_in_the_inbox_lane_and_has_a_handler():
    from app.worker import HANDLERS

    assert feedback_replies.reply  # imported, as app.main imports it, to register its handlers
    for kind in (
        JobKind.INBOX_FEEDBACK_SWEEP, JobKind.INBOX_FEEDBACK_SEND,
        JobKind.INBOX_FEEDBACK_REPLY, JobKind.INBOX_FEEDBACK_ASK_SOLVED,
    ):
        assert kind in INBOX_WORK and kind in HANDLERS
    interval, _ = SCHEDULE[JobKind.INBOX_FEEDBACK_SWEEP]
    assert interval == timedelta(minutes=30)


# ── The skips that need Shopify's and the inbox's own records ─────────────────


def _decided(db, shopify_node=None, **changes) -> FeedbackSurvey:
    started(db)
    row = order(db, **changes)
    return decide(db, row, node() if shopify_node is None else (shopify_node or None), utcnow())


def test_an_order_with_nothing_against_it_is_to_be_asked_and_keeps_what_the_question_needs(db):
    row = _decided(db)
    assert (row.state, row.step, row.skip_reason) == ("pending", "rating", None)
    assert (row.phone, row.customer_name, row.order_name) == (HER, "Nour", "#7001")
    assert (row.products, row.courier) == (["Linen Shirt", "Wide Trousers"], "Bosta")
    assert row.delivered_at is not None


def test_an_order_with_no_first_name_is_asked_as_there(db):
    row = _decided(db, node(customer={"firstName": None, "phone": "01005550188"}))
    assert row.customer_name == "there"


@pytest.mark.parametrize(
    ("shopify_node", "reason"),
    [
        ({}, feedback.SKIP_NOT_FOUND),
        (node(cancelledAt="2026-11-01T10:00:00Z"), feedback.SKIP_CANCELLED),
        (node(test=True), feedback.SKIP_TEST),
        (node(phone=None, customer={"firstName": "Nour"}, shippingAddress=None), feedback.SKIP_NO_PHONE),
        (node(phone="12345", customer={}, shippingAddress={"phone": "0233445566"}), feedback.SKIP_BAD_PHONE),
    ],
)
def test_the_order_itself_can_rule_it_out(db, shopify_node, reason):
    row = _decided(db, shopify_node)
    assert (row.state, row.skip_reason, row.step) == ("skipped", reason, "done")


def test_a_skipped_order_keeps_no_customer_detail(db):
    row = _decided(db, node(test=True))
    assert (row.phone, row.customer_name, row.products) == (None, None, [])
    assert row.order_name == "#7001"


def test_a_return_waiting_for_review_rules_it_out(db):
    db.add(
        OpsEstebdalReturn(
            estebdal_id="e1", return_number="#7001-R1", order_number="#7001",
            requested_at=utcnow(), seen_at=utcnow(),
        )
    )
    db.flush()
    assert _decided(db).skip_reason == feedback.SKIP_RETURN


def _refund(db, **changes) -> None:
    values = {"khazenly_number": "KH-HBA-1", "kind": "return", "order_number": "#7001"}
    values.update(changes)
    db.add(OpsRefund(**values))
    db.flush()


def test_a_refund_still_owed_rules_it_out(db):
    _refund(db)
    assert _decided(db).skip_reason == feedback.SKIP_RETURN


def test_a_refund_already_paid_does_not(db):
    _refund(
        db, paid_on=date(2026, 11, 5), paid_recorded_at=utcnow(), amount=450,
        method="instapay", refund_to="01005550188",
    )
    assert _decided(db).state == "pending"


def test_another_orders_return_does_not_rule_it_out(db):
    _refund(db, order_number="#7099")
    assert _decided(db).state == "pending"


def test_the_same_phone_is_not_asked_twice_in_60_days(db):
    started(db)
    survey(db, "6001", sent_at=utcnow() - timedelta(days=59), state="sent")
    assert _decided(db).skip_reason == feedback.SKIP_ASKED_RECENTLY


def test_after_60_days_she_is_asked_again(db):
    started(db)
    survey(db, "6001", sent_at=utcnow() - timedelta(days=61), created_at=utcnow() - timedelta(days=61))
    assert _decided(db).state == "pending"


def test_an_order_skipped_earlier_does_not_count_as_asking_her(db):
    started(db)
    survey(db, "6001", state="skipped", step="done", skip_reason="test_order", sent_at=None)
    assert _decided(db).state == "pending"


def test_button_taps_leave_unread_messages_that_do_not_block(db):
    """Every customer who tapped Confirm has one, and nobody has opened her chat."""
    chat = conversation(db, unread=3)
    message(db, chat, kind="button", ago=timedelta(hours=1))
    message(db, chat, kind="reaction", ago=timedelta(minutes=30))
    assert _decided(db).state == "pending"


def test_an_unanswered_text_within_72_hours_makes_it_wait_and_stores_nothing_of_hers(db):
    chat = conversation(db)
    message(db, chat, ago=timedelta(hours=5))
    started(db)
    when = utcnow()
    row = decide(db, order(db), node(), when)
    assert (row.state, row.skip_reason, row.step) == ("waiting", feedback.WAIT_UNANSWERED, "rating")
    assert row.next_attempt_at == when + timedelta(hours=6)
    assert (row.phone, row.customer_name, row.products) == (None, None, [])
    assert row.order_name == "#7001" and row.courier == "Bosta"


def test_an_old_unanswered_text_does_not_block(db):
    chat = conversation(db)
    message(db, chat, ago=timedelta(hours=73))
    assert _decided(db).state == "pending"


@pytest.mark.parametrize(
    "setup",
    [
        "automatic reply",       # not an answer from a person
        "staff reply before",    # an answer to something she wrote earlier
    ],
)
def test_only_a_later_staff_message_answers_her(db, setup):
    chat = conversation(db)
    if setup == "automatic reply":
        message(db, chat, ago=timedelta(hours=5))
        message(db, chat, direction="out", origin="automatic", ago=timedelta(hours=1))
    else:
        message(db, chat, direction="out", ago=timedelta(hours=9))
        message(db, chat, ago=timedelta(hours=5))
    assert _decided(db).state == "waiting"


def test_a_staff_reply_after_her_text_clears_it(db):
    chat = conversation(db)
    message(db, chat, ago=timedelta(hours=5))
    message(db, chat, direction="out", ago=timedelta(hours=1))
    assert _decided(db).state == "pending"


def test_after_staff_reply_the_waiting_order_is_asked_on_the_next_sweep(db, feature_on):
    started(db)
    order(db)
    chat = conversation(db)
    message(db, chat, ago=timedelta(hours=5))
    client = shopify({"7001": node()})

    assert sweep(db, client=client) == 1
    row = db.query(FeedbackSurvey).one()
    assert row.state == "waiting" and jobs(db, JobKind.INBOX_FEEDBACK_SEND) == []

    # Not looked at again before its six hours are up.
    asked: list = []
    assert sweep(db, now=utcnow() + timedelta(hours=1), client=shopify({"7001": node()}, asked)) == 0
    assert asked == [] and row.state == "waiting"

    message(db, chat, direction="out", ago=timedelta(minutes=30))  # staff answered
    assert sweep(db, now=utcnow() + timedelta(hours=7), client=client) == 1

    assert (row.state, row.skip_reason, row.step, row.next_attempt_at) == ("pending", None, "rating", None)
    assert (row.phone, row.customer_name, row.products) == (HER, "Nour", ["Linen Shirt", "Wide Trousers"])
    assert [key for _, key, _ in jobs(db, JobKind.INBOX_FEEDBACK_SEND)] == [
        f"{JobKind.INBOX_FEEDBACK_SEND}:{row.id}:0"
    ]
    assert db.query(FeedbackSurvey).count() == 1


def test_a_waiting_order_still_blocked_waits_another_six_hours(db, feature_on):
    started(db)
    order(db)
    chat = conversation(db)
    message(db, chat, ago=timedelta(hours=5))
    sweep(db, client=shopify({"7001": node()}))
    later = utcnow() + timedelta(hours=7)

    assert sweep(db, now=later, client=shopify({"7001": node()})) == 1
    row = db.query(FeedbackSurvey).one()
    assert (row.state, row.next_attempt_at) == ("waiting", later + timedelta(hours=6))


def test_a_waiting_order_past_seven_days_is_dropped_without_asking_shopify(db, feature_on):
    started(db)
    order(db, delivered_ago=timedelta(days=6, hours=23))
    chat = conversation(db)
    message(db, chat, ago=timedelta(hours=5))
    sweep(db, client=shopify({"7001": node()}))
    row = db.query(FeedbackSurvey).one()
    assert row.state == "waiting"

    asked: list = []
    assert sweep(db, now=utcnow() + timedelta(hours=7), client=shopify({"7001": node()}, asked)) == 0
    assert asked == []
    assert (row.state, row.skip_reason, row.step, row.next_attempt_at) == (
        "skipped", "waited_too_long", "done", None,
    )
    assert jobs(db, JobKind.INBOX_FEEDBACK_SEND) == []


def test_deciding_a_waiting_order_after_seven_days_drops_it(db):
    started(db)
    chat = conversation(db)
    message(db, chat, ago=timedelta(hours=5))
    indexed = order(db, delivered_ago=timedelta(days=6, hours=23))
    assert decide(db, indexed, node(), utcnow()).state == "waiting"
    assert decide(db, indexed, node(), utcnow() + timedelta(hours=7)).skip_reason == "waited_too_long"


def test_a_waiting_order_that_has_since_had_a_return_is_skipped_for_good(db):
    started(db)
    chat = conversation(db)
    message(db, chat, ago=timedelta(hours=5))
    indexed = order(db)
    assert decide(db, indexed, node(), utcnow()).state == "waiting"
    indexed.return_activity = True
    row = decide(db, indexed, node(), utcnow() + timedelta(hours=7))
    assert (row.state, row.skip_reason) == ("skipped", feedback.SKIP_RETURN)


def test_waiting_orders_are_not_on_the_sheet_unless_asked_for(db):
    survey(db, "1", state="waiting", step="rating", phone=None, wa_message_id=None, sent_at=None, skip_reason="unanswered_message")
    survey(db, "2")
    assert [row["order_id"] for row in feedback.rows(db)] == ["2"]
    assert sorted(row["order_id"] for row in feedback.rows(db, include_skipped=True)) == ["1", "2"]


def test_a_customer_with_an_unhappy_answer_not_yet_resolved_waits(db):
    """Past the 60 days, which would cover it, she is still waiting for a person."""
    survey(
        db, "6001", rating="unhappy", step="support", rated_at=utcnow() - timedelta(days=80),
        sent_at=utcnow() - timedelta(days=90), created_at=utcnow() - timedelta(days=90),
    )
    row = _decided(db)
    assert (row.state, row.skip_reason) == ("waiting", feedback.WAIT_UNHAPPY_OPEN)


def test_once_resolved_an_unhappy_customer_is_not_a_reason_to_skip(db):
    survey(
        db, "6001", rating="unhappy", step="done", rated_at=utcnow() - timedelta(days=90),
        sent_at=utcnow() - timedelta(days=90), created_at=utcnow() - timedelta(days=90),
    )
    assert _decided(db).state == "pending"


def test_two_orders_for_one_phone_in_one_sweep_ask_her_once(db, feature_on):
    started(db)
    order(db, "7001", delivered_ago=timedelta(days=4))
    order(db, "7002", delivered_ago=timedelta(days=3))
    sweep(db, client=shopify({"7001": node(), "7002": node(name="#7002")}))
    states = {row.shopify_order_id: (row.state, row.skip_reason) for row in db.query(FeedbackSurvey)}
    assert states == {"7001": ("pending", None), "7002": ("skipped", "asked_recently")}


def test_deciding_an_order_twice_records_it_once(db):
    started(db)
    row = order(db)
    first = decide(db, row, node(), utcnow())
    second = decide(db, row, node(test=True), utcnow())
    assert first.id == second.id and second.state == "pending"
    assert db.query(FeedbackSurvey).count() == 1


# ── The first question ────────────────────────────────────────────────────────


def _pending(db, **changes) -> FeedbackSurvey:
    return survey(db, state="pending", sent_at=None, wa_message_id=None, **changes)


def test_without_permission_it_records_what_would_have_been_sent_and_sends_nothing(db, connected):
    row = _pending(db)
    asked: list = []
    send_first_question(db, row.id, client=meta(asked), claim=_yes)
    assert (row.state, asked) == ("would_send", [])
    assert db.query(InboxMessage).count() == 0


def test_the_first_question_is_the_approved_template_with_three_buttons(db, may_send):
    row = _pending(db)
    asked: list = []
    send_first_question(db, row.id, client=meta(asked), claim=_yes)

    sent = asked[0]
    assert (sent["to"], sent["type"]) == (HER, "template")
    template = sent["template"]
    assert (template["name"], template["language"]) == ("order_feedback", {"code": "en"})
    body, *buttons = template["components"]
    assert [p["text"] for p in body["parameters"]] == ["Nour", "#7001"]
    assert [(b["sub_type"], b["index"], b["parameters"][0]["payload"]) for b in buttons] == [
        ("quick_reply", "0", "fb_loved_7001"),
        ("quick_reply", "1", "fb_okay_7001"),
        ("quick_reply", "2", "fb_unhappy_7001"),
    ]


def test_a_sent_question_is_on_the_survey_and_in_the_chat(db, may_send):
    row = _pending(db)
    send_first_question(db, row.id, client=meta([]), claim=_yes)

    assert (row.state, row.wa_message_id, row.attempts, row.last_error) == (
        "sent", "wamid.SENT1", 1, None,
    )
    assert row.sent_at is not None
    chat = db.query(InboxConversation).one()
    assert (chat.phone, chat.name, row.conversation_id) == (HER, "Nour", chat.id)
    message = db.query(InboxMessage).one()
    assert (message.kind, message.origin, message.template_name, message.shopify_order_id) == (
        "template", "automatic", "order_feedback", "7001",
    )
    assert message.body == "Order feedback · #7001"
    assert message.extra == {"buttons": ["Loved it", "It was okay", "Not happy"]}
    assert message.wa_message_id == "wamid.SENT1"


def test_a_question_is_sent_only_while_it_is_waiting(db, may_send):
    asked: list = []
    for index, state in enumerate(("sent", "would_send", "sending", "failed", "no_whatsapp", "skipped")):
        row = survey(db, f"8{index}", state=state, wa_message_id=None)
        send_first_question(db, row.id, client=meta(asked), claim=_yes)
        assert row.state == state
    assert asked == []
    assert send_first_question(db, 987654, client=meta(asked), claim=_yes) is None


def test_a_question_someone_else_claimed_is_not_sent(db, may_send):
    asked: list = []
    row = _pending(db)
    send_first_question(db, row.id, client=meta(asked), claim=lambda _id: False)
    assert asked == [] and row.state == "pending"


def test_a_question_whatsapp_did_not_answer_is_tried_again_later(db, may_send):
    row = _pending(db)
    send_first_question(db, row.id, client=meta([], refuse=(400, 131000)), claim=_yes)
    assert (row.state, row.attempts) == ("pending", 1)
    assert row.next_attempt_at > utcnow()
    assert [key for _, key, _ in jobs(db, JobKind.INBOX_FEEDBACK_SEND)] == [
        f"{JobKind.INBOX_FEEDBACK_SEND}:{row.id}:1"
    ]


def test_after_the_last_attempt_it_is_failed(db, may_send):
    row = _pending(db, attempts=outbound.MAX_ATTEMPTS - 1)
    send_first_question(db, row.id, client=meta([], refuse=(400, 131000)), claim=_yes)
    assert row.state == "failed" and jobs(db, JobKind.INBOX_FEEDBACK_SEND) == []


def test_a_number_with_no_whatsapp_is_not_tried_again(db, may_send):
    row = _pending(db)
    send_first_question(db, row.id, client=meta([], refuse=(400, 131026)), claim=_yes)
    assert (row.state, row.last_error) == ("no_whatsapp", "WhatsApp could not reach this number (code 131026)")
    assert jobs(db, JobKind.INBOX_FEEDBACK_SEND) == []


def test_a_refusal_that_will_not_change_is_failed(db, may_send):
    row = _pending(db)
    send_first_question(db, row.id, client=meta([], refuse=(400, 132001)), claim=_yes)
    assert row.state == "failed"


def test_a_question_left_sending_by_a_crash_is_failed_never_resent(db, may_send):
    stuck = survey(db, "8001", state="sending", wa_message_id=None)
    stuck.updated_at = utcnow() - timedelta(minutes=11)
    fresh = survey(db, "8002", state="sending", wa_message_id=None)
    db.flush()

    assert feedback.recover_interrupted(db) == 1
    db.refresh(stuck)
    assert (stuck.state, stuck.last_error) == ("failed", outbound.INTERRUPTED)
    assert fresh.state == "sending"


def test_a_delivery_failure_marks_the_survey_by_its_message(db, may_send):
    row = _pending(db)
    send_first_question(db, row.id, client=meta([]), claim=_yes)

    assert events.apply_status(
        db, {"id": "wamid.SENT1", "status": "failed", "errors": [{"code": 131026}]}
    )
    db.refresh(row)
    assert row.state == "no_whatsapp"

    other = survey(
        db, "7002", state="sent", wa_message_id="wamid.OTHER", conversation_id=row.conversation_id
    )
    db.add(
        InboxMessage(
            conversation_id=row.conversation_id, direction="out", kind="template", body="x",
            wa_message_id="wamid.OTHER", status="sent", origin="automatic", occurred_at=utcnow(),
        )
    )
    db.flush()
    events.apply_status(db, {"id": "wamid.OTHER", "status": "failed", "errors": [{"code": 132001}]})
    db.refresh(other)
    assert other.state == "failed"


def test_the_send_job_needs_a_survey_and_does_nothing_with_the_flag_off(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.inbox_feedback_enabled", False)
    row = _pending(db)
    feedback._handle_send(db, {"survey_id": row.id})
    assert row.state == "pending"
    with pytest.raises(PermanentFailure):
        feedback._handle_send(db, {})


# ── The sheet's reads ─────────────────────────────────────────────────────────


def test_the_sheet_lists_asked_orders_newest_delivery_first_and_filters(db):
    survey(db, "1", delivered_at=utcnow() - timedelta(days=5), rating="loved", reason="quality", courier="Bosta", products=["Linen Shirt"])
    survey(db, "2", delivered_at=utcnow() - timedelta(days=4), rating="unhappy", reason="delivery", courier="Aramex", products=["Wide Trousers"])
    survey(db, "3", delivered_at=utcnow() - timedelta(days=3), state="skipped", step="done", skip_reason="no_phone", phone=None)

    assert [row["order_id"] for row in feedback.rows(db)] == ["2", "1"]
    assert [row["order_id"] for row in feedback.rows(db, include_skipped=True)] == ["3", "2", "1"]
    assert [row["order_id"] for row in feedback.rows(db, rating="loved")] == ["1"]
    assert [row["order_id"] for row in feedback.rows(db, reason="delivery")] == ["2"]
    assert [row["order_id"] for row in feedback.rows(db, courier="Bosta")] == ["1"]
    assert [row["order_id"] for row in feedback.rows(db, product="trousers")] == ["2"]
    assert [row["order_id"] for row in feedback.rows(db, since=utcnow() - timedelta(days=4, hours=1))] == ["2"]
    assert [row["order_id"] for row in feedback.rows(db, until=utcnow() - timedelta(days=4, hours=1))] == ["1"]
    assert feedback.rows(db, product="100%") == []


def test_needs_follow_up_is_an_unhappy_answer_waiting_for_a_person(db):
    waiting = survey(db, "1", rating="unhappy", step="support", rated_at=utcnow() - timedelta(hours=3))
    survey(db, "2", rating="unhappy", step="solved", rated_at=utcnow())
    survey(db, "3", rating="okay", step="support", rated_at=utcnow())
    older = survey(db, "4", rating="unhappy", step="support", rated_at=utcnow() - timedelta(hours=9))

    listed = feedback.needs_follow_up(db)
    assert [row["id"] for row in listed] == [older.id, waiting.id]
    assert all(row["needs_follow_up"] for row in listed)


# ── The interactive messages (MetaClient) ─────────────────────────────────────


def _client(asked: list) -> MetaClient:
    return meta(asked)


def test_buttons_are_an_interactive_reply_message():
    asked: list = []
    client = _client(asked)
    wamid = client.send_buttons(
        HER, "Was your issue solved?",
        [{"id": "fbs_yes_9", "title": "Yes"}, {"id": "fbs_no_9", "title": "No"}],
    )
    assert wamid == "wamid.SENT1"
    assert asked[0]["to"] == HER and asked[0]["type"] == "interactive"
    interactive = asked[0]["interactive"]
    assert interactive["type"] == "button"
    assert interactive["body"] == {"text": "Was your issue solved?"}
    assert interactive["action"]["buttons"] == [
        {"type": "reply", "reply": {"id": "fbs_yes_9", "title": "Yes"}},
        {"type": "reply", "reply": {"id": "fbs_no_9", "title": "No"}},
    ]


def test_a_list_is_an_interactive_list_message():
    asked: list = []
    _client(asked).send_list(
        HER, "What did you like most?", "Choose one",
        [{"id": "fbr_quality_9", "title": "Quality"}, {"id": "fbr_fit_9", "title": "Fit"}],
    )
    interactive = asked[0]["interactive"]
    assert interactive["type"] == "list"
    assert interactive["action"] == {
        "button": "Choose one",
        "sections": [{"rows": [{"id": "fbr_quality_9", "title": "Quality"}, {"id": "fbr_fit_9", "title": "Fit"}]}],
    }


@pytest.mark.parametrize(
    "buttons",
    [
        [],
        [{"id": str(n), "title": "x"} for n in range(4)],
        [{"id": "a", "title": "x" * 21}],
        [{"id": "a", "title": ""}],
        [{"id": "", "title": "ok"}],
    ],
)
def test_buttons_beyond_whatsapps_limits_are_refused_before_asking(buttons):
    asked: list = []
    with pytest.raises(MetaError) as refused:
        _client(asked).send_buttons(HER, "Hello", buttons)
    assert refused.value.kind == "invalid" and asked == []


@pytest.mark.parametrize(
    ("body", "label", "rows"),
    [
        ("Hello", "Pick", []),
        ("Hello", "Pick", [{"id": str(n), "title": "x"} for n in range(11)]),
        ("Hello", "Pick", [{"id": "a", "title": "x" * 25}]),
        ("Hello", "x" * 21, [{"id": "a", "title": "ok"}]),
        ("Hello", "", [{"id": "a", "title": "ok"}]),
        ("x" * (MAX_BODY + 1), "Pick", [{"id": "a", "title": "ok"}]),
        ("", "Pick", [{"id": "a", "title": "ok"}]),
    ],
)
def test_a_list_beyond_whatsapps_limits_is_refused_before_asking(body, label, rows):
    asked: list = []
    with pytest.raises(MetaError) as refused:
        _client(asked).send_list(HER, body, label, rows)
    assert refused.value.kind == "invalid" and asked == []


def test_ten_rows_and_three_buttons_at_the_limit_are_sent():
    asked: list = []
    client = _client(asked)
    client.send_list(HER, "Hello", "x" * 20, [{"id": str(n), "title": "y" * 24} for n in range(10)])
    client.send_buttons(HER, "Hello", [{"id": str(n), "title": "z" * 20} for n in range(3)])
    assert len(asked) == 2


def test_every_word_the_customer_is_sent_fits_whatsapps_limits():
    """The wording is ours to edit; this is what stops an edit that Meta would refuse."""
    assert len(feedback.LIST_LABEL) <= 20
    for rating, rows in feedback.REASONS.items():
        assert len(rows) <= 10
        assert len(feedback.REASON_QUESTIONS[rating]) <= MAX_BODY
        for key, title in rows:
            assert len(title) <= 24 and len(f"fbr_{key}_999999999999") <= 256
    for key, title in (*feedback.SOLVED_BUTTONS, *feedback.REORDERS):
        assert len(title) <= 20
    assert len(feedback.REORDERS) <= 3 and len(feedback.SOLVED_BUTTONS) <= 3
    for title in feedback.RATING_TITLES.values():
        assert len(title) <= 20
    # Reasons the customer can name are the grammar's: nothing the template or a
    # list sends could be refused as a tap.
    for rows in feedback.REASONS.values():
        for key, _ in rows:
            assert feedback_replies.parse_payload(f"fbr_{key}_12").value == key


def test_an_interactive_message_is_in_the_chat_as_text_with_its_choices(db, may_send):
    chat = conversation(db)
    message = outbound.send_buttons(
        db, chat, "Was your issue solved?",
        [{"id": "fbs_yes_9", "title": "Yes"}, {"id": "fbs_no_9", "title": "No"}],
        origin="automatic", source_ref="x:1", client=meta([]),
    )
    assert (message.kind, message.status, message.origin) == ("text", "sent", "automatic")
    assert message.extra == {"buttons": ["Yes", "No"], "interactive": "buttons"}
    assert chat.last_preview == "Was your issue solved?"


def test_an_interactive_message_outside_the_24_hours_is_refused(db, may_send):
    chat = conversation(db, wrote_ago=timedelta(hours=30))
    asked: list = []
    with pytest.raises(outbound.NotSent) as refused:
        outbound.send_list(
            db, chat, "Hello", "Pick", [{"id": "a", "title": "ok"}],
            origin="automatic", client=meta(asked),
        )
    assert refused.value.kind == "window_closed" and asked == []


# ── Who counts as asked, and a question that never went out ───────────────────


@pytest.mark.parametrize(
    ("state", "blocks"),
    [
        ("sent", True),
        ("pending", True),     # on its way: stops a second order's question in the same sweep
        ("sending", True),
        ("would_send", False),  # only recorded: nobody was asked
        ("failed", False),
        ("no_whatsapp", False),
    ],
)
def test_only_a_question_that_went_out_or_is_on_its_way_counts_as_asking_her(db, state, blocks):
    started(db)
    survey(
        db, "6001", state=state, wa_message_id=None,
        sent_at=utcnow() - timedelta(days=10) if state == "sent" else None,
    )
    assert (_decided(db).skip_reason == feedback.SKIP_ASKED_RECENTLY) is blocks


def test_a_question_never_sent_is_queued_again_once_it_is_stale(db):
    stale = _pending(db, shopify_order_id="1")
    stale.updated_at = utcnow() - timedelta(minutes=31)
    fresh = _pending(db, shopify_order_id="2")
    fresh.updated_at = utcnow() - timedelta(minutes=10)
    retrying = _pending(db, shopify_order_id="3", next_attempt_at=utcnow() + timedelta(hours=1))
    retrying.updated_at = utcnow() - timedelta(minutes=40)
    too_old = _pending(db, shopify_order_id="4", delivered_at=utcnow() - timedelta(days=8))
    too_old.updated_at = utcnow() - timedelta(minutes=40)
    db.flush()

    assert requeue_stale_pending(db) == 1
    assert [key for _, key, _ in jobs(db, JobKind.INBOX_FEEDBACK_SEND)] == [
        f"{JobKind.INBOX_FEEDBACK_SEND}:{stale.id}:0"
    ]
    # Queued again while that job still waits: absorbed, not doubled.
    requeue_stale_pending(db)
    assert len(jobs(db, JobKind.INBOX_FEEDBACK_SEND)) == 1


def test_the_sweep_queues_a_stale_pending_question_again(db, feature_on):
    started(db)
    stale = _pending(db)
    stale.updated_at = utcnow() - timedelta(hours=2)
    db.flush()
    sweep(db, client=shopify({}))
    assert [key for _, key, _ in jobs(db, JobKind.INBOX_FEEDBACK_SEND)] == [
        f"{JobKind.INBOX_FEEDBACK_SEND}:{stale.id}:0"
    ]


def test_a_question_whose_send_ended_without_sending_is_sent_by_the_requeued_job(db, may_send):
    """The whole mend: the flag was off when the first job ran, the row stayed
    pending, the sweep queued it again, and now it goes."""
    row = _pending(db)
    asked: list = []
    send_first_question(db, row.id, client=meta(asked), claim=_yes)
    assert row.state == "sent" and len(asked) == 1
