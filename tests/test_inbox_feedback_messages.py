"""Post-delivery feedback: the wording is the owner's to edit (ADR 0083, decision 3).

The registry of every message (``feedback_messages``), what an edit does to
what a customer is sent, the new *No* reply, and the two routes. The flows run
as administrator's tests do (the questions switched off for everyone else), with
WhatsApp and Shopify mocked: nothing leaves the machine and every name, number
and order is made up.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.businesstime import utcnow
from app.db import SessionLocal
from app.modules.inbox.models import FeedbackSettings, InboxConversation, InboxMessage
from app.modules.inbox.services import (
    feedback,
    feedback_messages,
    feedback_replies,
)
from app.shared.models.audit import AuditEvent
from tests.feedback_support import (  # noqa: F401  (fixtures)
    HER,
    connected,
    conversation,
    feature_on,
    jobs,
    may_send,
    survey,
)
from tests.test_inbox_feedback_api import _demote_to, client  # noqa: F401  (fixtures)
from tests.test_inbox_feedback_codes import CODE_SHAPE, shop  # noqa: F401  (fixtures)
from tests.test_inbox_feedback_events import _bodies, apply, interactive_tap, template_tap
from tests.test_inbox_feedback_test_send import (  # noqa: F401  (fixtures)
    send,
    tap_list,
    tap_rating,
    the_test,
    run_replies,
    world,
)

NOT_SOLVED = (
    "We're sorry it isn't solved yet. We've passed it back to our team, and someone will "
    "message you here within 24 hours."
)


def edit(db, **values):
    """Save wording the way the route does, keys written with ``__`` for ``.``."""
    feedback_messages.save(
        db, {key.replace("__", "."): words for key, words in values.items()},
        actor_id=None, actor_email=None,
    )


def rows_of(message: dict) -> list[dict]:
    return message["interactive"]["action"]["sections"][0]["rows"]


# ── The built-in words ────────────────────────────────────────────────────────


def test_the_built_in_words_are_the_owners_new_ones():
    said = {item.key: item.default for item in feedback_messages.ITEMS}
    assert said["reason_question.loved"] == "What did you like most?"
    assert said["reason_question.okay"] == "What would have made it better?"
    assert said["reason_question.unhappy"] == "We're sorry about that. What went wrong?"
    assert said["list_label"] == "Choose one"
    assert said["thanks.loved"] == "Thank you, {name}! We're so glad you loved it."
    assert said["thanks.okay"] == "Thank you, {name}. Your honest answer helps us get better."
    assert said["thanks.unhappy"] == "Thank you, {name}. We're glad we could put it right."
    assert said["code_line"] == (
        "As a thank you, here is {percent}% off your next order:\n{code}\n"
        "It is yours only, works once, and is valid for {days} days."
    )
    assert said["review_line"] == (
        "Would you share it in a short review? It takes a minute and helps other customers "
        "choose:\n{url}"
    )
    assert said["invitation"] == "If there is anything we could do better, just reply here."
    assert said["tell_us"] == "Please tell us what it was in a few words. Just reply here."
    assert said["support"] == (
        "We're sorry, {name}, and thank you for telling us. A member of our team will message "
        "you here within {hours} hours to make it right."
    )
    assert said["solved_question"] == "Was your issue solved?"
    assert (said["solved_option.yes"], said["solved_option.no"]) == ("Yes", "No")
    assert said["not_solved"] == (
        "We're sorry it isn't solved yet. We've passed it back to our team, and someone will "
        "message you here within {hours} hours."
    )
    assert said["reorder_question"] == "How likely are you to order from us again?"


def test_every_option_the_sheet_knows_is_in_the_registry_with_its_built_in_title():
    for rating, rows in feedback.REASONS.items():
        for key, title in rows:
            item = feedback_messages.BY_KEY[f"reason_option.{rating}.{key}"]
            assert (item.default, item.kind, item.max, item.group) == (title, "label", 24, rating)
    for key, title in feedback.REORDERS:
        item = feedback_messages.BY_KEY[f"reorder_option.{key}"]
        assert (item.default, item.kind, item.max) == (title, "label", 20)


def test_every_built_in_message_can_be_saved_as_it_is_and_fits_whatsapp():
    assert feedback_messages.validate({item.key: item.default for item in feedback_messages.ITEMS}) == {}
    assert len({item.key for item in feedback_messages.ITEMS}) == len(feedback_messages.ITEMS)
    groups = {key for key, _ in feedback_messages.GROUPS}
    assert {item.group for item in feedback_messages.ITEMS} <= groups


# ── Her name ──────────────────────────────────────────────────────────────────


def test_her_name_is_put_in_where_the_words_ask_for_it():
    assert feedback_messages.text(None, "thanks.loved", name="Sara") == (
        "Thank you, Sara! We're so glad you loved it."
    )
    assert feedback_messages.text(None, "support", name="Sara", hours=24) == (
        "We're sorry, Sara, and thank you for telling us. A member of our team will message "
        "you here within 24 hours to make it right."
    )


@pytest.mark.parametrize("name", [None, ""])
def test_without_her_name_the_words_still_read_naturally(name):
    assert feedback_messages.text(None, "thanks.loved", name=name) == (
        "Thank you! We're so glad you loved it."
    )
    assert feedback_messages.text(None, "thanks.okay", name=name) == (
        "Thank you. Your honest answer helps us get better."
    )
    assert feedback_messages.text(None, "support", name=name, hours=24) == (
        "We're sorry, and thank you for telling us. A member of our team will message "
        "you here within 24 hours to make it right."
    )
    # A caller that never mentions her name gets the same.
    assert feedback_messages.text(None, "thanks.loved") == "Thank you! We're so glad you loved it."


def test_her_name_in_other_places_leaves_no_gap_either():
    cfg = SimpleNamespace(
        messages={
            "invitation": "{name}, tell us more.",
            "tell_us": "Hi {name}, tell us.",
            "list_label": "x",
        }
    )
    assert feedback_messages.text(cfg, "invitation") == "tell us more."
    assert feedback_messages.text(cfg, "invitation", name="Sara") == "Sara, tell us more."
    assert feedback_messages.text(cfg, "tell_us") == "Hi, tell us."


def test_her_first_name_is_the_first_word_of_the_one_the_first_question_used():
    assert feedback_messages.first_name(SimpleNamespace(customer_name="Mary Ann")) == "Mary"
    assert feedback_messages.first_name(SimpleNamespace(customer_name="Nour")) == "Nour"
    # The first question's own fallback is not a name.
    assert feedback_messages.first_name(SimpleNamespace(customer_name="there")) is None
    assert feedback_messages.first_name(SimpleNamespace(customer_name=None)) is None
    assert feedback_messages.first_name(None) is None
    assert len(feedback_messages.first_name(SimpleNamespace(customer_name="N" * 200))) == 40


def test_braces_that_are_not_placeholders_never_break_the_words():
    cfg = SimpleNamespace(
        messages={
            "invitation": "Odd { braces } and {0} and {{name}} and {unknown} and } { and {name",
            "tell_us": "{",
            "list_label": "}{",
        }
    )
    said = feedback_messages.text(cfg, "invitation", name="Sara", code="X")
    assert said == "Odd { braces } and {0} and {Sara} and {unknown} and } { and {name"
    assert feedback_messages.text(cfg, "tell_us") == "{"
    assert feedback_messages.text(cfg, "list_label") == "}{"
    # What is put in is never read as a placeholder itself.
    assert feedback_messages.text(None, "thanks.loved", name="{name}") == (
        "Thank you, {name}! We're so glad you loved it."
    )
    # A placeholder the caller gave no value for stays as typed instead of failing.
    assert feedback_messages.text(None, "code_line", percent=20) == (
        "As a thank you, here is 20% off your next order:\n{code}\n"
        "It is yours only, works once, and is valid for {days} days."
    )


def test_a_saved_wording_that_is_not_words_falls_back_to_the_built_in():
    cfg = SimpleNamespace(messages={"invitation": 5, "tell_us": "   ", "nonsense": "x"})
    assert feedback_messages.text(cfg, "invitation") == feedback_messages.BY_KEY["invitation"].default
    assert feedback_messages.text(cfg, "tell_us") == feedback_messages.BY_KEY["tell_us"].default
    assert feedback_messages.saved(cfg) == {}


# ── Checking ──────────────────────────────────────────────────────────────────


def test_unknown_messages_are_refused():
    errors = feedback_messages.validate({"nonsense": "x", "reason_option.loved.nope": "x"})
    assert set(errors) == {"nonsense", "reason_option.loved.nope"}
    assert "not one of the messages" in errors["nonsense"]


def test_a_list_option_has_at_most_24_characters():
    assert feedback_messages.validate({"reason_option.loved.fit": "x" * 24}) == {}
    errors = feedback_messages.validate({"reason_option.loved.fit": "x" * 25})
    assert errors["reason_option.loved.fit"].startswith(
        "WhatsApp allows at most 24 characters on a list option."
    )


def test_a_button_and_the_lists_own_button_have_at_most_20_characters():
    for key, why in (
        ("solved_option.yes", "on a reply button"),
        ("reorder_option.maybe", "on a reply button"),
        ("list_label", "on the button that opens a list"),
    ):
        assert feedback_messages.validate({key: "x" * 20}) == {}
        assert why in feedback_messages.validate({key: "x" * 21})[key]


def test_a_question_with_options_has_at_most_1024_characters_and_a_closing_line_1000():
    assert feedback_messages.validate({"reason_question.loved": "x" * 1024}) == {}
    assert "1024" in feedback_messages.validate({"reason_question.loved": "x" * 1025})["reason_question.loved"]
    assert feedback_messages.validate({"invitation": "x" * 1000}) == {}
    assert "1000" in feedback_messages.validate({"invitation": "x" * 1001})["invitation"]


def test_a_line_that_comes_to_too_much_once_the_link_is_in_is_refused():
    long_but_typed_ok = "x" * 600 + " {url}"
    error = feedback_messages.validate({"review_line": long_but_typed_ok})["review_line"]
    assert "once her name, code or link are filled in" in error


def test_a_message_must_keep_what_it_exists_to_carry():
    assert feedback_messages.validate({"code_line": "Here you go: {code}"}) == {}
    assert feedback_messages.validate({"code_line": "Here is 20% off."})["code_line"] == (
        "This message must contain {code}, or the customer never sees her code."
    )
    assert feedback_messages.validate({"review_line": "Please review us"})["review_line"] == (
        "This message must contain {url}, or the customer never sees your review link."
    )


def test_a_placeholder_a_message_cannot_use_is_refused_in_plain_words():
    errors = feedback_messages.validate(
        {"thanks.loved": "Your code {code}", "support": "In {days} days", "list_label": "{name}"}
    )
    assert errors["thanks.loved"] == "{code} cannot be used here; this message can use {name}."
    assert errors["support"] == "{days} cannot be used here; this message can use {name} and {hours}."
    assert errors["list_label"] == "{name} cannot be used here; this one is plain words."
    # A typo is caught too, rather than sent to her as it is.
    assert "{nmae} cannot be used here" in feedback_messages.validate({"thanks.loved": "Hi {nmae}"})["thanks.loved"]


def test_tried_to_call_words_are_editable_and_take_the_order(db):
    """The message after the second unanswered call (ADR 0088) names the order."""
    item = feedback_messages.BY_KEY["tried_to_call"]
    assert (item.group, item.kind, item.placeholders) == ("unhappy", "text", ("name", "order"))
    assert item.default == (
        "We tried to call you about your order {order}. Reply here or tell us a good time to call."
    )
    assert feedback_messages.validate({"tried_to_call": "Hi {name}, about {order}"}) == {}
    assert feedback_messages.validate({"tried_to_call": "Your code {code}"})["tried_to_call"] == (
        "{code} cannot be used here; this message can use {name} and {order}."
    )
    saved = feedback_messages.save(
        db, {"tried_to_call": "Hi {name}, about {order}"}, actor_id=None, actor_email=None
    )
    assert feedback_messages.text(saved, "tried_to_call", name="Nour", order="#7001") == "Hi Nour, about #7001"


def test_blank_is_the_built_in_words_not_an_error():
    assert feedback_messages.validate({"thanks.loved": "", "invitation": "   ", "tell_us": None}) == {}


def test_a_label_is_one_line_and_nothing_has_characters_that_cannot_be_sent():
    assert "one line" in feedback_messages.validate({"reason_option.loved.fit": "a\nb"})["reason_option.loved.fit"]
    assert "cannot be sent" in feedback_messages.validate({"invitation": "a\x00b"})["invitation"]
    assert feedback_messages.validate({"invitation": "two\nlines are fine here"}) == {}
    assert feedback_messages.validate({"invitation": 5})["invitation"] == "The wording must be text."


def test_two_options_in_one_list_cannot_have_the_same_title():
    errors = feedback_messages.validate(
        {"reason_option.loved.fit": "Style", "reason_option.loved.design": "style"}
    )
    assert set(errors) == {"reason_option.loved.fit", "reason_option.loved.design"}
    assert "already called" in errors["reason_option.loved.fit"]
    # Against an option left alone, which still has its built-in title.
    errors = feedback_messages.validate({"reason_option.loved.fit": "Quality"})
    assert list(errors) == ["reason_option.loved.fit"]
    # The same title in another list is fine.
    assert feedback_messages.validate({"reason_option.okay.price": "Fit"}) == {}
    # Swapping two titles is not a clash.
    assert feedback_messages.validate(
        {"solved_option.yes": "No", "solved_option.no": "Yes"}
    ) == {}


# ── Saving ────────────────────────────────────────────────────────────────────


def test_saving_keeps_only_what_differs_and_a_blank_puts_the_built_in_back(db):
    edit(db, thanks__loved="  Thanks a lot, {name}!  ", invitation="If there is anything we could do better, just reply here.")
    row = feedback.get_settings(db)
    assert row.messages == {"thanks.loved": "Thanks a lot, {name}!"}
    assert feedback_messages.text(row, "thanks.loved", name="Sara") == "Thanks a lot, Sara!"
    edit(db, thanks__loved="")
    assert feedback.get_settings(db).messages == {}
    edit(db, thanks__loved="Again")
    edit(db, thanks__loved=None)
    assert feedback.get_settings(db).messages == {}


def test_a_message_not_named_stays_as_it_is(db):
    edit(db, thanks__loved="One", thanks__okay="Two")
    edit(db, thanks__okay="Three")
    assert feedback.get_settings(db).messages == {"thanks.loved": "One", "thanks.okay": "Three"}


def test_nothing_is_saved_if_any_of_it_cannot_be(db):
    edit(db, thanks__loved="Kept")
    with pytest.raises(feedback_messages.MessagesRefused) as refused:
        feedback_messages.save(
            db,
            {"thanks.okay": "Fine", "code_line": "no code here", "nonsense": "x"},
            actor_id=None, actor_email=None,
        )
    assert set(refused.value.errors) == {"code_line", "nonsense"}
    assert feedback.get_settings(db).messages == {"thanks.loved": "Kept"}


def test_a_change_is_audited_by_the_names_of_the_messages_and_never_their_words(db):
    edit(db, thanks__loved="A secret new wording", reason_option__loved__fit="Style")
    [event] = db.scalars(
        select(AuditEvent).where(AuditEvent.action == "inbox.feedback_messages_saved")
    )
    assert event.department == "inbox"
    assert event.after_json["count"] == 2
    assert "Loved it: Thank-you line" in event.after_json["changed"]
    assert "secret" not in str(event.after_json) and "Style" not in str(event.after_json)
    # Saving what is already saved changes nothing, so it is not another entry.
    edit(db, thanks__loved="A secret new wording")
    assert len(list(db.scalars(select(AuditEvent).where(AuditEvent.action == "inbox.feedback_messages_saved")))) == 1


# ── What a customer is sent ───────────────────────────────────────────────────


def test_the_loved_path_says_the_edited_words_and_the_ids_do_not_change(db, world):
    cfg = feedback.get_settings(db)
    cfg.review_url = "https://reviews.example/hba"
    edit(
        db,
        reason_question__loved="Which part made you smile?",
        reason_option__loved__quality="Great quality",
        reason_option__loved__other="Another thing",
        list_label="Pick one",
        thanks__loved="Lovely, {name}!",
        code_line="Your gift: {code} ({percent}% for {days} days).",
        review_line="Review us here {url}",
        invitation="Write us anything.",
    )
    send(db, world)
    row = the_test(db)
    tap_rating(db, row, "loved", "wamid.L1")

    asked = world.asked[-1]
    assert asked["interactive"]["body"] == {"text": "Which part made you smile?"}
    assert asked["interactive"]["action"]["button"] == "Pick one"
    assert [(r["id"], r["title"]) for r in rows_of(asked)] == [
        (f"fbr_quality_{row.id}", "Great quality"),
        (f"fbr_fit_{row.id}", "Fit"),
        (f"fbr_design_{row.id}", "Design"),
        (f"fbr_delivery_{row.id}", "Delivery"),
        (f"fbr_other_{row.id}", "Another thing"),
    ]

    tap_list(db, row, "quality", "wamid.L2")
    db.refresh(row)
    assert (row.reason, row.step) == ("quality", "comment")
    # She loved it and a review link is set: thanks, her code, the link - and no invitation.
    assert _bodies(world.asked)[-1] == (
        f"Lovely, Yahya!\n\nYour gift: {row.code} (20% for 30 days).\n\n"
        "Review us here https://reviews.example/hba"
    )
    assert CODE_SHAPE.fullmatch(row.code)


def test_a_loved_customer_with_no_review_link_is_invited_to_write(db, world):
    edit(db, invitation="Write us anything.", tell_us="What was it?")
    send(db, world)
    row = the_test(db)
    tap_rating(db, row, "loved", "wamid.L1")
    tap_list(db, row, "fit", "wamid.L2")
    closing = _bodies(world.asked)[-1]
    assert closing.startswith("Thank you, Yahya! We're so glad you loved it.")
    assert closing.endswith("Write us anything.") and "What was it?" not in closing


def test_a_loved_customer_who_chose_something_else_is_asked_what_it_was_in_place_of_the_invitation(db, world):
    edit(db, invitation="Write us anything.", tell_us="What was it?")
    send(db, world)
    other = the_test(db)
    tap_rating(db, other, "loved", "wamid.M1")
    tap_list(db, other, "other", "wamid.M2")
    closing = _bodies(world.asked)[-1]
    assert closing.endswith("What was it?") and "Write us anything." not in closing


def test_the_okay_path_says_the_edited_words(db, world):
    edit(
        db,
        reason_question__okay="How could we do better?",
        reason_option__okay__size_fit="Sizing",
        thanks__okay="Noted, {name}.",
    )
    send(db, world)
    row = the_test(db)
    tap_rating(db, row, "okay", "wamid.O1")
    asked = world.asked[-1]
    assert asked["interactive"]["body"] == {"text": "How could we do better?"}
    assert (rows_of(asked)[0]["id"], rows_of(asked)[0]["title"]) == (f"fbr_size_fit_{row.id}", "Sizing")
    tap_list(db, row, "price", "wamid.O2")
    closing = _bodies(world.asked)[-1]
    assert closing.startswith("Noted, Yahya.") and closing.endswith(
        "If there is anything we could do better, just reply here."
    )


def test_the_unhappy_path_to_the_end_says_the_edited_words_in_every_message(db, world):
    edit(
        db,
        reason_question__unhappy="What happened?",
        reason_option__unhappy__wrong_item="Not what I ordered",
        support="Sorry {name}. We reply in {hours} hours.",
        solved_question="Did we fix it?",
        solved_option__yes="Fixed",
        solved_option__no="Not yet",
        reorder_question="Would you buy again?",
        reorder_option__very_likely="Definitely",
        reorder_option__maybe="Perhaps",
        reorder_option__unlikely="No thanks",
        thanks__unhappy="Glad it is sorted, {name}.",
    )
    send(db, world)
    row = the_test(db)
    tap_rating(db, row, "unhappy", "wamid.U1")
    asked = world.asked[-1]
    assert asked["interactive"]["body"] == {"text": "What happened?"}
    assert [r["title"] for r in rows_of(asked)][2] == "Not what I ordered"
    tap_list(db, row, "wrong_item", "wamid.U2")
    assert _bodies(world.asked)[-1] == "Sorry Yahya. We reply in 24 hours."

    feedback_replies.resolve(db, row.id, world.owner, "Agreed an exchange")
    feedback_replies._handle_ask_solved(db, {"survey_id": row.id})
    asked = world.asked[-1]
    assert asked["interactive"]["body"] == {"text": "Did we fix it?"}
    assert [b["reply"] for b in asked["interactive"]["action"]["buttons"]] == [
        {"id": f"fbs_yes_{row.id}", "title": "Fixed"},
        {"id": f"fbs_no_{row.id}", "title": "Not yet"},
    ]

    apply(db, interactive_tap("button_reply", f"fbs_yes_{row.id}", "Fixed", "wamid.U3"))
    run_replies(db)
    asked = world.asked[-1]
    assert asked["interactive"]["body"] == {"text": "Would you buy again?"}
    assert [b["reply"] for b in asked["interactive"]["action"]["buttons"]] == [
        {"id": f"fbo_very_likely_{row.id}", "title": "Definitely"},
        {"id": f"fbo_maybe_{row.id}", "title": "Perhaps"},
        {"id": f"fbo_unlikely_{row.id}", "title": "No thanks"},
    ]

    apply(db, interactive_tap("button_reply", f"fbo_maybe_{row.id}", "Perhaps", "wamid.U4"))
    run_replies(db)
    db.refresh(row)
    assert (row.step, row.reorder, row.solved) == ("done", "maybe", True)
    closing = _bodies(world.asked)[-1]
    assert closing.startswith("Glad it is sorted, Yahya.") and row.code in closing
    assert "just reply here" not in closing


def test_unhappy_and_something_else_is_still_asked_what_it_was_after_the_promise(db, world):
    edit(db, tell_us="What was it?")
    send(db, world)
    row = the_test(db)
    tap_rating(db, row, "unhappy", "wamid.U1")
    tap_list(db, row, "other", "wamid.U2")
    said = _bodies(world.asked)[-1]
    assert said.startswith("We're sorry, Yahya, and thank you for telling us.")
    assert said.endswith("\n\nWhat was it?")


def test_the_approved_message_keeps_its_own_buttons_whatever_the_chat_ones_say(db, world):
    edit(db, solved_option__yes="Fixed", solved_option__no="Not yet")
    send(db, world)
    row = the_test(db)
    tap_rating(db, row, "unhappy", "wamid.U1")
    tap_list(db, row, "size_fit", "wamid.U2")
    feedback_replies.resolve(db, row.id, world.owner, "Agreed an exchange")
    db.get(InboxConversation, row.conversation_id).last_inbound_at = utcnow() - timedelta(hours=30)
    db.flush()
    feedback_replies._handle_ask_solved(db, {"survey_id": row.id})

    template = world.asked[-1]["template"]
    assert template["name"] == "feedback_resolved"
    # Their payloads are the same ids; only the chat's own titles are edited.
    assert [b["parameters"][0]["payload"] for b in template["components"][1:]] == [
        f"fbs_yes_{row.id}", f"fbs_no_{row.id}",
    ]
    message = db.scalar(select(InboxMessage).where(InboxMessage.template_name == "feedback_resolved"))
    assert message.extra["buttons"] == ["Yes", "No"]


def test_the_sheet_and_its_filters_keep_the_built_in_names_whatever_the_list_says(db, world):
    edit(db, reason_option__loved__quality="Great quality", reorder_option__maybe="Perhaps")
    assert feedback.reason_title("loved", "quality") == "Quality"
    assert feedback.REORDER_TITLES["maybe"] == "Maybe"
    assert {"id": "quality", "title": "Quality"} in feedback.options(db)["reasons"]["loved"]


# ── She says it was not solved ────────────────────────────────────────────────


def _not_solved(db, world, *, wamid="wamid.U3", before_tap=lambda: None):
    send(db, world)
    row = the_test(db)
    tap_rating(db, row, "unhappy", "wamid.U1")
    tap_list(db, row, "size_fit", "wamid.U2")
    feedback_replies.resolve(db, row.id, world.owner, "Agreed an exchange")
    feedback_replies._handle_ask_solved(db, {"survey_id": row.id})
    asked_before = len(world.asked)
    before_tap()
    apply(db, interactive_tap("button_reply", f"fbs_no_{row.id}", "No", wamid))
    return row, asked_before


def test_no_is_told_a_person_will_write_again_once_even_if_the_job_runs_twice(db, world):
    row, before = _not_solved(db, world)
    run_replies(db)
    run_replies(db)

    assert (row.solved, row.step, row.reopened_count) == (False, "support", 1)
    [said] = world.asked[before:]
    assert said["type"] == "text" and said["text"]["body"] == NOT_SOLVED
    stored = db.scalar(select(InboxMessage).where(InboxMessage.source_ref == "fb:wamid.U3"))
    assert (stored.origin, stored.status, stored.body) == ("automatic", "sent", NOT_SOLVED)
    # The rest of what *No* does is unchanged: back to the team's list.
    assert [r["id"] for r in feedback.needs_follow_up(db)] == []  # a test is never in it
    assert (row.resolved_at, row.solved_asked_at) == (None, None)


def test_the_promised_hours_and_the_wording_in_it_are_the_current_ones(db, world):
    feedback.get_settings(db).reply_hours = 48
    edit(db, not_solved="Sorry {name}, a person writes within {hours} hours.")
    row, before = _not_solved(db, world)
    run_replies(db)
    assert _bodies(world.asked[before:]) == ["Sorry Yahya, a person writes within 48 hours."]


def test_no_is_not_answered_where_no_other_reply_would_be(db, world, monkeypatch):
    """Sending is switched off for customers just before she taps, and her
    number is not a test number: she is reopened for a person all the same,
    and nothing is sent."""

    def switch_off():
        monkeypatch.setattr("app.config.settings.inbox_send_to_customers", False)
        monkeypatch.setattr("app.config.settings.inbox_test_numbers", "")

    row, before = _not_solved(db, world, before_tap=switch_off)
    run_replies(db)
    assert len(world.asked) == before
    assert (row.solved, row.step, row.reopened_count) == (False, "support", 1)


def test_a_real_customer_who_says_no_is_told_only_when_the_feature_is_on(db, world, monkeypatch):
    chat = conversation(db)
    real = survey(
        db, conversation_id=chat.id, rating="unhappy", reason="quality",
        step="solved", solved_asked_at=utcnow(), resolved_at=utcnow(),
    )
    apply(db, interactive_tap("button_reply", f"fbs_no_{real.id}", "No", "wamid.R1"))
    assert (real.step, real.reopened_count) == ("support", 1)
    run_replies(db)  # the feature is off, and this is no test
    assert [m for m in _bodies(world.asked) if m == NOT_SOLVED] == []

    monkeypatch.setattr("app.config.settings.inbox_feedback_enabled", True)
    run_replies(db)
    assert _bodies(world.asked).count(NOT_SOLVED) == 1
    run_replies(db)
    assert _bodies(world.asked).count(NOT_SOLVED) == 1


# ── The two routes ────────────────────────────────────────────────────────────


def test_reading_gives_the_editor_everything_and_writes_nothing(client):
    body = client.get("/api/inbox/feedback/messages").json()
    assert set(body) == {"can_edit", "groups", "items", "templates", "flows", "sample"}
    assert body["can_edit"] is True
    assert body["groups"] == [
        {"id": "loved", "title": "Loved it"},
        {"id": "okay", "title": "It was okay"},
        {"id": "unhappy", "title": "Not happy"},
        {"id": "shared", "title": "Used on more than one path"},
    ]
    keys = [item["key"] for item in body["items"]]
    assert len(keys) == len(set(keys)) == len(feedback_messages.ITEMS)
    by_key = {item["key"]: item for item in body["items"]}
    assert all(
        set(item) == {"key", "group", "label", "help", "kind", "default", "value", "max", "placeholders"}
        and item["value"] is None and item["group"] in {g["id"] for g in body["groups"]}
        for item in body["items"]
    )
    assert by_key["code_line"]["placeholders"] == [
        {"name": "name", "meaning": "Her first name", "required": False, "example": "Sara"},
        {"name": "percent", "meaning": "The discount, in percent", "required": False, "example": "20"},
        {"name": "days", "meaning": "How many days her code lasts", "required": False, "example": "30"},
        {"name": "code", "meaning": "Her personal code", "required": True, "example": "FB-7K2M9Q"},
    ]
    assert (by_key["reason_option.loved.fit"]["kind"], by_key["reason_option.loved.fit"]["max"]) == ("label", 24)
    assert (by_key["thanks.loved"]["kind"], by_key["thanks.loved"]["max"]) == ("text", 1000)
    assert by_key["reason_question.loved"]["max"] == 1024
    assert "message Meta approved goes instead" in by_key["solved_question"]["help"]
    assert body["sample"] == {
        "name": "Sara", "order": "#1234", "code": "FB-7K2M9Q", "percent": 20, "days": 30,
        "hours": 24, "url": None,
    }
    assert [(t["name"], t["buttons"]) for t in body["templates"]] == [
        ("order_feedback", ["Loved it", "It was okay", "Not happy"]),
        ("feedback_resolved", ["Yes", "No"]),
        ("feedback_tried_to_call", []),
    ]
    assert body["templates"][0]["body"] == (
        "Hi {{1}}, your HBA Wear order {{2}} has been delivered. How was it? Tap an answer below."
    )
    assert body["templates"][1]["body"] == "About your HBA Wear order {{1}}: was your issue solved?"
    assert body["templates"][2]["body"] == (
        "We tried to call you about your order {{1}}. Reply here or tell us a good time to call."
    )
    assert all("Meta" in t["note"] for t in body["templates"])
    # Reading never writes the settings row.
    with SessionLocal() as db:
        assert db.get(FeedbackSettings, 1) is None


def test_the_paths_only_point_at_messages_and_templates_that_exist(client):
    body = client.get("/api/inbox/feedback/messages").json()
    keys = {item["key"] for item in body["items"]}
    templates = {t["name"] for t in body["templates"]}
    assert set(body["flows"]) == {"loved", "okay", "unhappy"}
    for path, steps in body["flows"].items():
        assert steps[0]["type"] == "template" and steps[0]["ref"] == "order_feedback"
        for step in steps:
            assert set(step) == {"type", "ref", "when", "options", "button", "with_previous"}
            assert step["when"]
            if step["type"] == "template":
                assert step["ref"] in templates
            else:
                assert step["ref"] in keys
                assert {i["key"]: i for i in body["items"]}[step["ref"]]["kind"] == "text"
            assert set(step["options"]) <= keys
            if step["button"]:
                assert step["button"] in keys
    # Every list of options she is shown is in a path, in the order she meets it.
    assert [s["ref"] for s in body["flows"]["loved"][:3]] == [
        "order_feedback", "reason_question.loved", "thanks.loved",
    ]
    assert body["flows"]["loved"][1]["options"] == [
        f"reason_option.loved.{key}" for key, _ in feedback.REASONS["loved"]
    ]
    unhappy = [s["ref"] for s in body["flows"]["unhappy"]]
    assert unhappy.index("solved_question") < unhappy.index("feedback_resolved") < unhappy.index("not_solved")
    assert unhappy.index("not_solved") < unhappy.index("reorder_question") < unhappy.index("thanks.unhappy")
    assert unhappy.index("support") < unhappy.index("tried_to_call") < unhappy.index("feedback_tried_to_call")
    assert unhappy.index("feedback_tried_to_call") < unhappy.index("solved_question")
    # Every editable message that is not an option or a button is on some path.
    on_a_path = {s["ref"] for steps in body["flows"].values() for s in steps} | {
        s["button"] for steps in body["flows"].values() for s in steps if s["button"]
    } | {o for steps in body["flows"].values() for s in steps for o in s["options"]}
    assert keys <= on_a_path


def test_the_sample_uses_the_saved_link_and_hours(client):
    assert client.put(
        "/api/inbox/feedback/settings",
        json={"review_url": "https://g.page/r/hba/review", "reply_hours": 48},
    ).status_code == 200
    sample = client.get("/api/inbox/feedback/messages").json()["sample"]
    assert (sample["url"], sample["hours"]) == ("https://g.page/r/hba/review", 48)


def test_an_admin_saves_wording_and_gets_the_same_body_back(client):
    saved = client.put(
        "/api/inbox/feedback/messages",
        json={"values": {"thanks.loved": "Thanks {name}!", "reason_option.loved.fit": "Style"}},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body == client.get("/api/inbox/feedback/messages").json()
    by_key = {item["key"]: item for item in body["items"]}
    assert by_key["thanks.loved"]["value"] == "Thanks {name}!"
    assert by_key["reason_option.loved.fit"]["value"] == "Style"
    assert by_key["thanks.okay"]["value"] is None
    # Null puts the built-in words back; what is not named stays.
    again = client.put("/api/inbox/feedback/messages", json={"values": {"thanks.loved": None}}).json()
    by_key = {item["key"]: item for item in again["items"]}
    assert by_key["thanks.loved"]["value"] is None and by_key["reason_option.loved.fit"]["value"] == "Style"
    with SessionLocal() as db:
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "inbox.feedback_messages_saved")))
        assert len(events) == 2 and events[0].department == "inbox"
        assert "Thanks" not in str([e.after_json for e in events])


def test_wording_that_cannot_be_used_is_refused_in_full_and_nothing_is_saved(client):
    assert client.put(
        "/api/inbox/feedback/messages", json={"values": {"thanks.okay": "Kept"}}
    ).status_code == 200
    refused = client.put(
        "/api/inbox/feedback/messages",
        json={
            "values": {
                "thanks.loved": "Fine words",
                "code_line": "no code in this one",
                "reason_option.loved.fit": "x" * 30,
                "nonsense": "x",
            }
        },
    )
    assert refused.status_code == 422
    errors = refused.json()["detail"]["errors"]
    assert set(errors) == {"code_line", "reason_option.loved.fit", "nonsense"}
    assert errors["code_line"] == "This message must contain {code}, or the customer never sees her code."
    after = {i["key"]: i["value"] for i in client.get("/api/inbox/feedback/messages").json()["items"]}
    assert after["thanks.okay"] == "Kept" and after["thanks.loved"] is None
    with SessionLocal() as db:
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "inbox.feedback_messages_saved")))
        assert len(events) == 1  # only the first, good, save


def test_a_value_that_is_not_text_is_refused(client):
    assert client.put("/api/inbox/feedback/messages", json={"values": {"thanks.loved": 5}}).status_code == 422
    assert client.put("/api/inbox/feedback/messages", json={}).status_code == 200  # nothing to change


@pytest.mark.parametrize("role", ["customer_service", "operations_manager"])
def test_customer_service_reads_the_wording_but_never_changes_it(client, role):
    _demote_to(role)
    read = client.get("/api/inbox/feedback/messages")
    assert read.status_code == 200 and read.json()["can_edit"] is False
    refused = client.put("/api/inbox/feedback/messages", json={"values": {"thanks.loved": "Nope"}})
    assert refused.status_code == 403
    with SessionLocal() as db:
        assert db.get(FeedbackSettings, 1) is None or not db.get(FeedbackSettings, 1).messages
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "inbox.feedback_messages_saved")) is None


@pytest.mark.parametrize("role", ["affiliate_manager", "content_manager", "affiliate"])
def test_a_role_without_the_inbox_gets_nothing_here(client, role):
    _demote_to(role)
    assert client.get("/api/inbox/feedback/messages").status_code == 403
    assert client.put("/api/inbox/feedback/messages", json={"values": {}}).status_code == 403


def test_nobody_signed_out_reaches_the_wording(fresh_database):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anonymous:
        assert anonymous.get("/api/inbox/feedback/messages").status_code == 401
        assert anonymous.put("/api/inbox/feedback/messages", json={"values": {}}).status_code == 401
