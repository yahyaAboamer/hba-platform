"""The wording of the feedback messages, and the owner's changes to it
(ADR 0083, decision 3).

**Every word a customer is sent by this feature is listed here once**: its
key, where it sits, what it is for, its built-in wording and WhatsApp's limit
for it. What an admin changes is kept beside the settings (``messages``,
``{key: text}``, only what differs) and ``text`` is the one way the sending
code reads any of it.

What cannot be changed here, and why:

- **The approved messages** (``order_feedback``, ``feedback_resolved`` and
  ``feedback_tried_to_call``) are held by Meta; their words change only in Meta's WhatsApp Manager and
  need Meta's approval again. They are shown (``TEMPLATES``), not editable.
- **What an option records.** An option's id is fixed (it is what is stored
  and what the Feedback sheet filters by); only its title, the words she
  taps, can change. The sheet and its filters keep the built-in titles, so
  the same answer is never counted under two names. Options are not added or
  removed.

A placeholder is a name in braces, such as ``{name}``. Filling one in never
raises: only the names a message may use are replaced; any other brace is left
as it was typed.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.modules.inbox.models import FeedbackSettings
from app.modules.inbox.services import feedback
from app.modules.inbox.services.meta import (
    MAX_BODY,
    MAX_BUTTON_TITLE,
    MAX_LIST_BUTTON,
    MAX_ROW_TITLE,
)
from app.shared.services.audit import record_audit

#: The longest a closing line (and any other plain message here) may be. The
#: closing message is up to four of them joined into one WhatsApp message,
#: whose own limit is 4096 characters.
MAX_LINE = 1000
#: A first name longer than this is cut, so a long one cannot push a message
#: over WhatsApp's limit.
MAX_FIRST_NAME = 40

GROUPS = (
    ("loved", "Loved it"),
    ("okay", "It was okay"),
    ("unhappy", "Not happy"),
    ("shared", "Used on more than one path"),
)

#: ``name -> (what it stands for, an example)``. The example is only what the
#: editor shows; the real value comes from the survey.
PLACEHOLDERS: dict[str, tuple[str, str]] = {
    "name": ("Her first name", "Sara"),
    "code": ("Her personal code", "FB-7K2M9Q"),
    "percent": ("The discount, in percent", str(feedback.DISCOUNT_PERCENT)),
    "days": ("How many days her code lasts", str(feedback.CODE_DAYS)),
    "hours": ("The hours promised for a reply", "24"),
    "order": ("The order's name", "#1234"),
    "url": ("Your review link", "https://example.com/review"),
}
#: What a missing required placeholder costs, in words for the owner.
_REQUIRED_WHY = {
    "code": "the customer never sees her code",
    "url": "the customer never sees your review link",
}
#: The longest each placeholder can come out, for the length check.
_WORST = {
    "name": MAX_FIRST_NAME,
    "code": 20,
    "percent": 3,
    "days": 3,
    "hours": 3,
    # As long as an order's name can be (``FeedbackSurvey.order_name``).
    "order": 40,
    "url": feedback.REVIEW_URL_MAX,
}

#: What Meta approved, word for word. Shown to the owner; never sent from here.
TEMPLATES = (
    {
        "name": feedback.TEMPLATE,
        "body": "Hi {{1}}, your HBA Wear order {{2}} has been delivered. How was it? Tap an answer below.",
        "buttons": [feedback.RATING_TITLES[rating] for rating in feedback.RATINGS],
        "note": (
            "Approved by Meta. It can only be changed in Meta's WhatsApp Manager, "
            "and Meta has to approve it again."
        ),
    },
    {
        "name": feedback.SOLVED_TEMPLATE,
        "body": "About your HBA Wear order {{1}}: was your issue solved?",
        "buttons": ["Yes", "No"],
        "note": (
            "Approved by Meta. It can only be changed in Meta's WhatsApp Manager, "
            "and Meta has to approve it again. It is sent instead of the chat "
            "question when her 24 hours have closed."
        ),
    },
    {
        "name": feedback.TRIED_TEMPLATE,
        "body": "We tried to call you about your order {{1}}. Reply here or tell us a good time to call.",
        "buttons": [],
        "note": (
            "Approved by Meta (22 November 2026). It can only be changed in Meta's WhatsApp "
            "Manager, and Meta has to approve it again. It is sent instead of the chat message "
            "when her 24 hours have closed."
        ),
    },
)
#: What its two buttons say, as the chat shows them.
SOLVED_TEMPLATE_BUTTONS = ("Yes", "No")


@dataclass(frozen=True)
class Item:
    key: str
    group: str
    label: str
    help: str
    default: str
    kind: str  # "text" (a message's words) or "label" (a button or list row)
    max: int
    #: Why ``max`` is what it is, in words for the owner.
    why_max: str
    placeholders: tuple[str, ...] = ()
    required: tuple[str, ...] = ()


# Where each limit comes from, for the message that refuses a longer one.
_WHY_BODY = (
    f"WhatsApp allows at most {MAX_BODY} characters in a message that has options under it."
)
_WHY_LINE = (
    f"A line here can be at most {MAX_LINE} characters, so the whole message stays "
    "within what WhatsApp allows."
)
_WHY_ROW = f"WhatsApp allows at most {MAX_ROW_TITLE} characters on a list option."
_WHY_LIST_BUTTON = f"WhatsApp allows at most {MAX_LIST_BUTTON} characters on the button that opens a list."
_WHY_BUTTON = f"WhatsApp allows at most {MAX_BUTTON_TITLE} characters on a reply button."


def _build() -> tuple[Item, ...]:
    items: list[Item] = []

    def text_item(key, group, label, help_, default, *, why=_WHY_LINE, limit=MAX_LINE, uses=("name",), required=()):
        items.append(Item(key, group, label, help_, default, "text", limit, why, tuple(uses), tuple(required)))

    def label_item(key, group, label, help_, default, *, why, limit):
        items.append(Item(key, group, label, help_, default, "label", limit, why))

    def reasons(rating: str, question: str, wording: str) -> None:
        text_item(
            f"reason_question.{rating}", rating, f"Question: {wording}",
            "Sent right after her first answer, above the list of reasons she can choose from.",
            question, why=_WHY_BODY, limit=MAX_BODY,
        )
        for key, title in feedback.REASONS[rating]:
            label_item(
                f"reason_option.{rating}.{key}", rating, f"List option: {title}",
                "One row in the list. Only the words change; what it records for the sheet does not.",
                title, why=_WHY_ROW, limit=MAX_ROW_TITLE,
            )

    reasons("loved", "What did you like most?", "what she liked most")
    text_item(
        "thanks.loved", "loved", "Thank-you line",
        "The first line of the closing message, sent after she picks a reason.",
        "Thank you, {name}! We're so glad you loved it.",
    )
    text_item(
        "review_line", "loved", "Review request",
        "Added to the closing message only when a review link is set, at the top of this page.",
        "Would you share it in a short review? It takes a minute and helps other customers choose:\n{url}",
        uses=("name", "url"), required=("url",),
    )

    reasons("okay", "What would have made it better?", "what would have made it better")
    text_item(
        "thanks.okay", "okay", "Thank-you line",
        "The first line of the closing message, sent after she picks a reason.",
        "Thank you, {name}. Your honest answer helps us get better.",
    )

    reasons("unhappy", "We're sorry about that. What went wrong?", "what went wrong")
    text_item(
        "support", "unhappy", "Promise of a person",
        "Sent after she picks a reason. A member of the team then follows up.",
        "We're sorry, {name}, and thank you for telling us. A member of our team will message "
        "you here within {hours} hours to make it right.",
        uses=("name", "hours"),
    )
    text_item(
        "tried_to_call", "unhappy", "We tried to call you",
        "Sent once, after the second call to her goes unanswered, while her 24 hours are open. "
        "When they have closed, the message Meta approved goes instead (shown below), and its "
        "words cannot be changed here.",
        feedback.TRIED_CHAT, uses=("name", "order"),
    )
    text_item(
        "solved_question", "unhappy", "Was it solved? (in the chat)",
        "Asked a day after your team marks her as resolved, while her 24 hours are open. When "
        "they have closed, the message Meta approved goes instead (shown below), and its "
        "words cannot be changed here.",
        "Was your issue solved?", why=_WHY_BODY, limit=MAX_BODY,
    )
    for key, title in (("yes", "Yes"), ("no", "No")):
        label_item(
            f"solved_option.{key}", "unhappy", f"Button: {title}",
            "A reply button under the question in the chat. The approved message has its own "
            "buttons, which cannot be changed here.",
            title, why=_WHY_BUTTON, limit=MAX_BUTTON_TITLE,
        )
    text_item(
        "not_solved", "unhappy", "If it is not solved",
        "Sent when she taps No. The chat goes back to your team's follow-up list.",
        "We're sorry it isn't solved yet. We've passed it back to our team, and someone will "
        "message you here within {hours} hours.",
        uses=("name", "hours"),
    )
    text_item(
        "reorder_question", "unhappy", "Will she order again?",
        "Asked when she says her issue was solved.",
        "How likely are you to order from us again?", why=_WHY_BODY, limit=MAX_BODY,
    )
    for key, title in feedback.REORDERS:
        label_item(
            f"reorder_option.{key}", "unhappy", f"Button: {title}",
            "A reply button under the question. Only the words change; what it records does not.",
            title, why=_WHY_BUTTON, limit=MAX_BUTTON_TITLE,
        )
    text_item(
        "thanks.unhappy", "unhappy", "Thank-you line",
        "The first line of the closing message, sent after she says her issue was solved and "
        "answers the last question.",
        "Thank you, {name}. We're glad we could put it right.",
    )

    label_item(
        "list_label", "shared", "Button that opens the list",
        "The button on every list of reasons, the one she taps to see the options.",
        "Choose one", why=_WHY_LIST_BUTTON, limit=MAX_LIST_BUTTON,
    )
    text_item(
        "code_line", "shared", "Her code",
        "Added to the closing message when her personal code could be made.",
        "As a thank you, here is {percent}% off your next order:\n{code}\n"
        "It is yours only, works once, and is valid for {days} days.",
        uses=("name", "percent", "days", "code"), required=("code",),
    )
    text_item(
        "invitation", "shared", "Invitation to write",
        "The last line of the closing message, unless a review request or \"tell us what it was\" "
        "takes its place.",
        "If there is anything we could do better, just reply here.",
    )
    text_item(
        "tell_us", "shared", "Ask what it was",
        "Sent when she chose Something else, so she can say what it was. What she writes back is "
        "kept with her answer.",
        "Please tell us what it was in a few words. Just reply here.",
    )
    return tuple(items)


ITEMS: tuple[Item, ...] = _build()
BY_KEY: dict[str, Item] = {item.key: item for item in ITEMS}

_IDENT = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
#: Her first name with the space or comma in front of it, so that leaving it
#: out leaves no gap: "Thank you, {name}!" -> "Thank you!".
_NAME_AFTER_TEXT = re.compile(r"(?:, | )\{name\}")
_NAME_AT_START = re.compile(r"^\{name\}(?:, | )?")


# ── Reading ───────────────────────────────────────────────────────────────────


def first_name(survey: Any) -> str | None:
    """Her first name as the first question greeted her with, or None when
    that was the fallback ("there") or there is none. Nothing is invented: a
    message with her name in it reads naturally without."""
    given = str(getattr(survey, "customer_name", None) or "").strip()
    first = given.split()[0] if given else ""
    if not first or first.lower() == "there":
        return None
    return first[:MAX_FIRST_NAME]


def saved(cfg: FeedbackSettings | None) -> dict[str, str]:
    """The wording an admin has changed. Anything that is not a message that
    exists, or not words, is not here."""
    found = getattr(cfg, "messages", None) or {}
    return {
        key: value.strip()
        for key, value in found.items()
        if key in BY_KEY and isinstance(value, str) and value.strip()
    }


def text(cfg: FeedbackSettings | None, key: str, **values: Any) -> str:
    """One message: the saved wording or else the built-in, with its
    placeholders filled in.

    **Never raises for what is in the words.** Only the names given in
    ``values`` are replaced, in one pass (so what is put in is never read as
    a placeholder itself); any other brace stays as it was typed. Her name,
    when it is not given or is empty, goes together with the comma or space
    before it. An unknown ``key`` is a mistake in the code and raises.
    """
    words = saved(cfg).get(key) or BY_KEY[key].default
    if not values.get("name"):
        words = _NAME_AT_START.sub("", words, count=1)
        words = _NAME_AFTER_TEXT.sub("", words)
        words = words.replace("{name}", "")

    def put(found: re.Match) -> str:
        value = values.get(found.group(1))
        return found.group(0) if value is None else str(value)

    return _IDENT.sub(put, words)


# ── Checking ──────────────────────────────────────────────────────────────────


def _listed(names: list[str]) -> str:
    shown = ["{" + name + "}" for name in names]
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]


def _check(item: Item, words: str) -> str | None:
    """Why this wording cannot be used for this message, or None."""
    if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in words):
        return "This contains a character that cannot be sent in a message."
    if item.kind == "label" and any(ch in words for ch in "\n\r"):
        return "This must be on one line."
    if len(words) > item.max:
        return f"{item.why_max} This one has {len(words)}."
    for name in dict.fromkeys(_IDENT.findall(words)):
        if name not in item.placeholders:
            if item.placeholders:
                return (
                    f"{{{name}}} cannot be used here; this message can use "
                    f"{_listed(list(item.placeholders))}."
                )
            return f"{{{name}}} cannot be used here; this one is plain words."
    for name in item.required:
        if "{" + name + "}" not in words:
            return (
                f"This message must contain {{{name}}}, or "
                f"{_REQUIRED_WHY.get(name, 'it loses its meaning')}."
            )
    # What it comes to once her name, code and link are in: the message must
    # still fit when they are as long as they can be.
    longest = _IDENT.sub(lambda found: "x" * _WORST[found.group(1)], words)
    if len(longest) > item.max:
        return (
            f"Too long once her name, code or link are filled in. Keep it to "
            f"{item.max} characters even then; this comes to {len(longest)}."
        )
    return None


def validate(values: Mapping[str, str | None]) -> dict[str, str]:
    """``{key: what is wrong}`` for each wording that cannot be saved, in
    words for the owner; empty if all of it can.

    A blank wording is not an error: it means the built-in words are used.
    Two options in one list cannot have the same title (WhatsApp refuses
    that), counting the built-in titles of the options left alone.
    """
    errors: dict[str, str] = {}
    chosen: dict[str, str] = {}
    for key, raw in values.items():
        item = BY_KEY.get(key)
        if item is None:
            errors[key] = "This is not one of the messages that can be edited."
            continue
        if raw is None:
            continue
        if not isinstance(raw, str):
            errors[key] = "The wording must be text."
            continue
        words = raw.strip()
        if not words:
            continue
        if problem := _check(item, words):
            errors[key] = problem
        else:
            chosen[key] = words

    lists: dict[str, list[Item]] = {}
    for item in ITEMS:
        if "_option." in item.key:
            lists.setdefault(item.key.rsplit(".", 1)[0], []).append(item)
    for members in lists.values():
        titles: dict[str, list[str]] = {}
        for member in members:
            title = chosen.get(member.key, member.default)
            titles.setdefault(title.casefold(), []).append(member.key)
        for keys in titles.values():
            if len(keys) < 2:
                continue
            for key in keys:
                if key in chosen and key not in errors:
                    errors[key] = (
                        f"Another option in this list is already called “{chosen[key]}”. "
                        "WhatsApp does not allow two the same."
                    )
    return errors


class MessagesRefused(ValueError):
    """Wording that cannot be saved: ``errors`` is ``{key: why}``."""

    def __init__(self, errors: dict[str, str]):
        super().__init__("Some of the wording cannot be saved.")
        self.errors = errors


# ── What the editor shows ─────────────────────────────────────────────────────


def _flows() -> dict[str, list[dict[str, Any]]]:
    """Each path as the customer meets it: what is sent, in order, and when."""

    def message(ref, when, *, options=(), button=None, with_previous=False):
        return {
            "type": "message", "ref": ref, "when": when, "options": list(options),
            "button": button, "with_previous": with_previous,
        }

    def template(name, when):
        return {
            "type": "template", "ref": name, "when": when, "options": [],
            "button": None, "with_previous": False,
        }

    def options(prefix):
        return [item.key for item in ITEMS if item.key.startswith(prefix)]

    first = template(feedback.TEMPLATE, "Two days after the order is delivered")
    answer = "Right after her first answer"
    return {
        "loved": [
            first,
            message("reason_question.loved", answer, options=options("reason_option.loved."), button="list_label"),
            message("thanks.loved", "After she picks a reason"),
            message("code_line", "If her code could be made", with_previous=True),
            message("review_line", "Only if a review link is set", with_previous=True),
            message(
                "invitation", "Unless a review link is set or she chose Something else",
                with_previous=True,
            ),
            message("tell_us", "Only if she chose Something else", with_previous=True),
        ],
        "okay": [
            first,
            message("reason_question.okay", answer, options=options("reason_option.okay."), button="list_label"),
            message("thanks.okay", "After she picks a reason"),
            message("code_line", "If her code could be made", with_previous=True),
            message("invitation", "Unless she chose Something else", with_previous=True),
            message("tell_us", "Only if she chose Something else", with_previous=True),
        ],
        "unhappy": [
            first,
            message("reason_question.unhappy", answer, options=options("reason_option.unhappy."), button="list_label"),
            message("support", "After she picks a reason"),
            message("tell_us", "Only if she chose Something else", with_previous=True),
            message("tried_to_call", "After the second call with no answer"),
            template(feedback.TRIED_TEMPLATE, "Instead of the message above, when her 24 hours have closed"),
            message(
                "solved_question", "A day after your team marks her as resolved",
                options=options("solved_option."),
            ),
            template(feedback.SOLVED_TEMPLATE, "Instead of the question above, when her 24 hours have closed"),
            message("not_solved", "If she answers No"),
            message("reorder_question", "If she answers Yes", options=options("reorder_option.")),
            message("thanks.unhappy", "After she says how likely she is to order again"),
            message("code_line", "If her code could be made", with_previous=True),
        ],
    }


def describe(cfg: FeedbackSettings | None, *, can_edit: bool = False) -> dict:
    """Everything the editor needs, read without writing."""
    overrides = saved(cfg)
    url = (getattr(cfg, "review_url", None) or "").strip() or None
    hours = getattr(cfg, "reply_hours", None) or 24
    sample = {
        "name": PLACEHOLDERS["name"][1],
        "order": "#1234",
        "code": PLACEHOLDERS["code"][1],
        "percent": feedback.DISCOUNT_PERCENT,
        "days": feedback.CODE_DAYS,
        "hours": hours,
        "url": url,
    }
    examples = {name: str(sample.get(name) or example) for name, (_, example) in PLACEHOLDERS.items()}
    return {
        "can_edit": can_edit,
        "groups": [{"id": key, "title": title} for key, title in GROUPS],
        "items": [
            {
                "key": item.key,
                "group": item.group,
                "label": item.label,
                "help": item.help,
                "kind": item.kind,
                "default": item.default,
                "value": overrides.get(item.key),
                "max": item.max,
                "placeholders": [
                    {
                        "name": name,
                        "meaning": PLACEHOLDERS[name][0],
                        "required": name in item.required,
                        "example": examples[name],
                    }
                    for name in item.placeholders
                ],
            }
            for item in ITEMS
        ],
        "templates": [dict(template) for template in TEMPLATES],
        "flows": _flows(),
        "sample": sample,
    }


# ── Saving ────────────────────────────────────────────────────────────────────

#: How many changed messages an audit entry names before it says "and n more".
_AUDIT_NAMES = 8


def save(
    db: Session,
    values: Mapping[str, str | None],
    *,
    actor_id: int | None,
    actor_email: str | None,
) -> FeedbackSettings:
    """Change the wording: ``{key: words}`` sets a message, a blank or None
    puts the built-in words back; a message not named stays as it is.

    Everything is checked first and nothing is saved if anything is wrong
    (``MessagesRefused``). Wording equal to the built-in is not kept, so a
    later improvement to the built-in words reaches it. Audited by the names
    of the messages changed, not their words.
    """
    row = feedback.get_settings(db)
    before = saved(row)
    candidate: dict[str, Any] = dict(before)
    for key, raw in values.items():
        blank = raw is None or (isinstance(raw, str) and not raw.strip())
        if blank and key in BY_KEY:
            candidate.pop(key, None)  # the built-in words again
        else:
            candidate[key] = raw  # an unknown key or a non-text value is reported below
    if errors := validate(candidate):
        raise MessagesRefused(errors)

    after: dict[str, str] = {}
    for key, raw in candidate.items():
        words = raw.strip().replace("\r\n", "\n")
        if words != BY_KEY[key].default:
            after[key] = words
    changed = [item for item in ITEMS if before.get(item.key) != after.get(item.key)]
    if changed:
        row.messages = after
        row.updated_at = utcnow()
        names = [item.label if item.group == "shared" else f"{_group_title(item)}: {item.label}" for item in changed]
        if len(names) > _AUDIT_NAMES:
            names = names[:_AUDIT_NAMES] + [f"and {len(names) - _AUDIT_NAMES} more"]
        record_audit(
            db,
            action="inbox.feedback_messages_saved",
            subject="feedback_settings",
            actor_id=actor_id,
            actor_email=actor_email,
            after={"changed": names, "count": len(changed)},
        )
    db.flush()
    return row


def _group_title(item: Item) -> str:
    return dict(GROUPS)[item.group]
