"""Post-delivery feedback, batch B (ADR 0083, point 5): the one Shopify discount,
a code for each customer who finishes, the closing words that carry it, used
or not, and the 30-day clean-up.

Shopify is never called: a real ``ShopifyClient`` talks to a small in-memory
store over ``httpx.MockTransport`` (``Shop``), which holds the one discount and
its codes and records what it was asked. Every order, code and number is made
up.
"""

import json
import re
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import event, select, text

from app.core.businesstime import utcnow
from app.modules.inbox.services import (
    connection,
    feedback,
    feedback_codes,
    feedback_messages,
    feedback_replies,
    tags,
)
from app.shared.models.integration import BackgroundJob
from app.shared.services.jobs import (
    INBOX_WORK,
    JobKind,
    JobStatus,
    PermanentFailure,
    enqueue,
)
from app.shared.services.schedule import SCHEDULE
from app.shared.services.shopify.client import ShopifyClient, ShopifyError
from tests.feedback_support import (  # noqa: F401  (fixtures)
    HER,
    conversation,
    connected,
    feature_on,
    jobs,
    may_send,
    meta,
    order,
    shopify,
    started,
    survey,
)
from tests.test_inbox_feedback_events import apply, interactive_tap, template_tap

CODE_SHAPE = re.compile(r"FB-[A-HJ-KM-NP-Z2-9]{6}")


# ── A small Shopify ───────────────────────────────────────────────────────────


class Shop:
    """The parts of Shopify the codes use, in memory, over a mock transport.

    Holds the one discount (``discount``, or None if there is none) and its
    codes (``codes``: id -> ``{"code", "uses"}``), and records every call by
    operation name in ``calls``. ``fail[name]`` is a list of responses given,
    first to last, before the real answer; ``adds_done`` is whether Shopify has
    finished adding a code by the time it is asked.
    """

    def __init__(self, scopes: str = "write_orders,write_discounts") -> None:
        self.scopes = scopes
        self.discount: str | None = None
        self.discount_inputs: list[dict] = []
        self.codes: dict[str, dict] = {}
        self.calls: list[tuple[str, dict]] = []
        self.fail: dict[str, list[httpx.Response]] = {}
        self.adds_done = True
        self.reject_next_add = False
        self.pending: dict[str, tuple[str, str]] = {}
        self._next = 100

    def names(self, name: str) -> list[dict]:
        return [variables for called, variables in self.calls if called == name]

    def _id(self, kind: str) -> str:
        self._next += 1
        return f"gid://shopify/{kind}/{self._next}"

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/access_token"):
            return httpx.Response(
                200, json={"access_token": "tok", "scope": self.scopes, "expires_in": 86399}
            )
        body = json.loads(request.read())
        name = re.search(r"(?:query|mutation)\s+(\w+)", body["query"]).group(1)
        variables = body.get("variables") or {}
        self.calls.append((name, variables))
        if self.fail.get(name):
            return self.fail[name].pop(0)
        return httpx.Response(200, json={"data": getattr(self, f"_{name}")(variables)})

    # Each operation answers like the real one, as far as the platform reads it.

    def _FeedbackDiscountCheck(self, v):
        return {"discountNode": {"id": v["id"]} if v["id"] == self.discount else None}

    def _FeedbackDiscountCreate(self, v):
        self.discount_inputs.append(v["input"])
        self.discount = self._id("DiscountCodeNode")
        return {
            "discountCodeBasicCreate": {"codeDiscountNode": {"id": self.discount}, "userErrors": []}
        }

    def _creation(self, bulk_id, code, done, failed=None):
        redeem = {"id": self.pending[bulk_id][1]} if done and not failed else None
        errors = [{"code": failed, "message": "Code is already in use"}] if failed else []
        return {
            "id": bulk_id,
            "done": done,
            "codesCount": 1,
            "importedCount": 1 if done and not failed else 0,
            "failedCount": 1 if failed else 0,
            "codes": {"nodes": [{"code": code, "errors": errors, "discountRedeemCode": redeem}]},
        }

    def _FeedbackCodeAdd(self, v):
        code = v["codes"][0]["code"]
        if v["discountId"] != self.discount:
            return {
                "discountRedeemCodeBulkAdd": {
                    "bulkCreation": None,
                    "userErrors": [{"code": "INVALID", "field": ["discountId"], "message": "No such discount"}],
                }
            }
        bulk_id, redeem_id = self._id("DiscountRedeemCodeBulkCreation"), self._id("DiscountRedeemCode")
        self.pending[bulk_id] = (code, redeem_id)
        taken = self.reject_next_add or any(c["code"] == code for c in self.codes.values())
        self.reject_next_add = False
        if not taken and self.adds_done:
            self.codes[redeem_id] = {"code": code, "uses": 0}
        done = self.adds_done or taken
        return {
            "discountRedeemCodeBulkAdd": {
                "bulkCreation": self._creation(bulk_id, code, done, "TAKEN" if taken else None),
                "userErrors": [],
            }
        }

    def _FeedbackCodeAddStatus(self, v):
        code, redeem_id = self.pending[v["id"]]
        # By the second look Shopify has finished, unless told otherwise.
        done = getattr(self, "finishes", True)
        if done:
            self.codes.setdefault(redeem_id, {"code": code, "uses": 0})
        return {"discountRedeemCodeBulkCreation": self._creation(v["id"], code, done)}

    def _FeedbackCodesById(self, v):
        return {
            "nodes": [
                {"id": i, "code": self.codes[i]["code"], "asyncUsageCount": self.codes[i]["uses"]}
                if i in self.codes
                else None
                for i in v["ids"]
            ]
        }

    def _FeedbackCodeByCode(self, v):
        nodes = [
            {"id": i, "code": c["code"], "asyncUsageCount": c["uses"]}
            for i, c in self.codes.items()
            if v["code"].lower() in c["code"].lower()
        ]
        return {"discountNode": {"discount": {"codes": {"nodes": nodes}}}}

    def _FeedbackCodesRemove(self, v):
        for gid in v["ids"]:
            self.codes.pop(gid, None)
        return {"discountCodeRedeemCodeBulkDelete": {"job": {"id": "gid://shopify/Job/1"}, "userErrors": []}}

    def client(self) -> ShopifyClient:
        client = ShopifyClient(
            shop_domain="hba-test.myshopify.com",
            client_id="second-app",
            client_secret="made-up-secret",
            api_version="2026-07",
            transport=httpx.MockTransport(self.handle),
        )
        client.retry_base_seconds = 0
        return client


@pytest.fixture()
def shop(monkeypatch):
    """A Shopify the second app is connected to, and the writes that must reach
    the database in a transaction of their own recorded instead."""
    store = Shop()
    monkeypatch.setattr(tags, "tags_client", lambda _db: store.client())
    store.remembered = []
    monkeypatch.setattr(feedback_codes, "_remember_discount", lambda gid: store.remembered.append(("discount", gid)))
    monkeypatch.setattr(
        feedback_codes, "_remember_code",
        lambda *args: store.remembered.append(("code", *args)),
    )
    monkeypatch.setattr(
        feedback_codes, "_remember_drawn",
        lambda *args: store.remembered.append(("drawn", *args)),
    )
    return store


def server_error() -> httpx.Response:
    return httpx.Response(503, json={})


def refused(code: str, message: str = "Shopify says no") -> dict:
    return {"code": code, "field": None, "message": message}


# ── codes_ready ───────────────────────────────────────────────────────────────


def test_codes_are_not_ready_without_the_second_app(db):
    assert feedback_codes.codes_ready(db) == (False, feedback_codes.NOT_CONNECTED)


def test_codes_are_not_ready_when_the_app_may_not_manage_discounts(db, shop):
    shop.scopes = "write_orders"
    ready, why = feedback_codes.codes_ready(db)
    assert ready is False and why == feedback_codes.NO_PERMISSION
    assert "write_discounts" in why


def test_codes_are_not_ready_when_shopify_does_not_answer(db, monkeypatch):
    dead = Shop()
    dead.handle = lambda request: httpx.Response(503, json={})
    client = ShopifyClient(
        shop_domain="hba-test.myshopify.com", client_id="a", client_secret="b",
        transport=httpx.MockTransport(dead.handle),
    )
    client.retry_base_seconds = 0
    monkeypatch.setattr(tags, "tags_client", lambda _db: client)
    ready, why = feedback_codes.codes_ready(db)
    assert ready is False and why.startswith("Shopify did not answer")


def test_codes_are_ready_with_the_permission(db, shop):
    assert feedback_codes.codes_ready(db) == (True, None)


def test_saving_the_second_app_does_not_need_the_discount_permission():
    """Order tagging must keep working without it: only write_orders is required."""
    assert connection.TAGS_SCOPE == "write_orders"
    assert connection.DISCOUNTS_SCOPE == "write_discounts"


# ── The one discount ──────────────────────────────────────────────────────────


def test_the_discount_is_made_once_and_then_reused(db, shop):
    first = feedback_codes.ensure_discount(db, shop.client())
    second = feedback_codes.ensure_discount(db, shop.client())
    assert first == second == shop.discount
    assert len(shop.names("FeedbackDiscountCreate")) == 1
    assert feedback.get_settings(db).discount_gid == first
    # Written down in a transaction of its own, the moment Shopify had made it.
    assert shop.remembered == [("discount", first)]


def test_the_discount_is_twenty_percent_one_use_per_code_and_once_per_customer(db, shop):
    feedback_codes.ensure_discount(db, shop.client())
    [made] = shop.discount_inputs
    assert made["title"] == "Feedback 20%"
    assert made["customerGets"] == {"value": {"percentage": 0.2}, "items": {"all": True}}
    assert made["context"] == {"all": "ALL"}
    assert made["usageLimit"] == 1 and made["appliesOncePerCustomer"] is True
    assert "endsAt" not in made and made["startsAt"]
    assert "minimumRequirement" not in made
    # The first code Shopify insists on is never given to anyone.
    assert CODE_SHAPE.fullmatch(made["code"]) is None and made["code"].startswith("FB-")
    assert len(made["code"]) == 3 + feedback_codes.SETUP_CODE_LENGTH


def test_a_discount_deleted_by_hand_is_made_again(db, shop):
    first = feedback_codes.ensure_discount(db, shop.client())
    shop.discount = None  # somebody deleted it in Shopify
    second = feedback_codes.ensure_discount(db, shop.client())
    assert second != first and second == shop.discount
    assert len(shop.names("FeedbackDiscountCreate")) == 2
    assert feedback.get_settings(db).discount_gid == second


def test_a_refused_discount_is_not_stored(db, shop, monkeypatch):
    client = shop.client()
    monkeypatch.setattr(
        shop, "_FeedbackDiscountCreate",
        lambda v: {"discountCodeBasicCreate": {"codeDiscountNode": None, "userErrors": [refused("INVALID")]}},
    )
    with pytest.raises(feedback_codes.CodeRefused):
        feedback_codes.ensure_discount(db, client)
    assert feedback.get_settings(db).discount_gid is None and shop.remembered == []


def test_two_jobs_asking_for_the_discount_take_it_in_turn(db, shop):
    """The second finds the first's discount: the lock is held to the end of the
    transaction, and what the first stored is read again after it."""
    client = shop.client()
    ids = {feedback_codes.ensure_discount(db, client) for _ in range(3)}
    assert len(ids) == 1 and len(shop.names("FeedbackDiscountCreate")) == 1
    locked = db.execute(text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")).scalar()
    assert locked >= 1


# ── A code each ───────────────────────────────────────────────────────────────


def _issue(db, row, **kwargs):
    return feedback_codes.issue_code(db, row, **kwargs)


def test_a_code_is_issued_once_per_survey_and_reused_on_a_second_call(db, shop):
    row = survey(db)
    code = _issue(db, row)
    assert CODE_SHAPE.fullmatch(code)
    calls = len(shop.calls)
    assert _issue(db, row) == code
    assert len(shop.calls) == calls  # nothing asked of Shopify the second time
    assert row.code == code and len(shop.codes) == 1
    assert {entry["code"] for entry in shop.codes.values()} == {code}


def test_the_code_is_kept_with_its_shopify_id_and_thirty_days(db, shop):
    row = survey(db)
    before = utcnow()
    code = _issue(db, row)
    [(redeem_id, held)] = shop.codes.items()
    assert held["code"] == code and row.code_gid == redeem_id
    assert row.code_expires_at - before >= timedelta(days=30) - timedelta(seconds=5)
    assert row.code_expires_at - utcnow() <= timedelta(days=30)
    # Not sent yet: that is stamped when the message really goes out.
    assert row.code_sent_at is None and row.code_used_at is None
    # Written down in a transaction of its own as soon as Shopify had it.
    assert ("code", row.id, code, redeem_id, row.code_expires_at) in shop.remembered


def test_codes_are_in_the_one_discount(db, shop):
    first, second = survey(db, "7001"), survey(db, "7002", wa_message_id="wamid.FIRST7002")
    _issue(db, first)
    _issue(db, second)
    adds = shop.names("FeedbackCodeAdd")
    assert [a["discountId"] for a in adds] == [shop.discount, shop.discount]
    assert len(shop.names("FeedbackDiscountCreate")) == 1
    assert first.code != second.code


def test_a_code_is_fb_and_six_characters_nobody_can_misread():
    seen = {feedback_codes.generate_code() for _ in range(300)}
    assert all(CODE_SHAPE.fullmatch(code) for code in seen)
    letters = "".join(code[3:] for code in seen)
    assert not set(letters) & set("0O1IL")
    assert len(seen) > 250  # drawn at random, not counted up


def test_a_code_another_survey_has_is_drawn_again(db, shop, monkeypatch):
    other = survey(db, "7002", wa_message_id="wamid.FIRST7002", code="FB-AAAAAA")
    draws = iter(["FB-AAAAAA", "FB-BBBBBB"])
    monkeypatch.setattr(feedback_codes, "generate_code", lambda: next(draws))
    row = survey(db)
    assert _issue(db, row) == "FB-BBBBBB" and other.code == "FB-AAAAAA"


def test_the_survey_table_refuses_the_same_code_twice(db):
    survey(db, "7001", code="FB-AAAAAA")
    with pytest.raises(Exception, match="unique|duplicate"):
        survey(db, "7002", wa_message_id="wamid.FIRST7002", code="FB-AAAAAA")


def test_a_code_shopify_says_is_taken_is_drawn_again(db, shop, monkeypatch):
    draws = iter(["FB-AAAAAA", "FB-BBBBBB"])
    monkeypatch.setattr(feedback_codes, "generate_code", lambda: next(draws))
    shop.reject_next_add = True
    row = survey(db)
    assert _issue(db, row) == "FB-BBBBBB"
    assert [entry["code"] for entry in shop.codes.values()] == ["FB-BBBBBB"]


def test_a_code_shopify_has_not_confirmed_is_not_stored_or_sent_and_is_retried(db, shop):
    shop.adds_done = False
    shop.finishes = False
    row = survey(db)
    with pytest.raises(ShopifyError):
        _issue(db, row)
    assert row.code is None and row.code_gid is None
    assert not [entry for entry in shop.remembered if entry[0] == "code"]
    assert len(shop.names("FeedbackCodeAddStatus")) == 1
    # Given up on at the last try: thanked without a code, nothing stored.
    assert _issue(db, row, final_attempt=True) is None
    assert row.code is None and "not finished" in row.last_error


def test_a_pending_code_is_adopted_on_the_retry_once_shopify_has_it(db, shop, monkeypatch):
    draws = iter(["FB-AAAAAA", "FB-BBBBBB"])
    monkeypatch.setattr(feedback_codes, "generate_code", lambda: next(draws))
    shop.adds_done = False
    shop.finishes = False
    row = survey(db)
    with pytest.raises(ShopifyError):
        _issue(db, row)
    # Shopify gets there in the end.
    shop.codes["gid://shopify/DiscountRedeemCode/900"] = {"code": "FB-AAAAAA", "uses": 0}
    adds = len(shop.names("FeedbackCodeAdd"))
    assert _issue(db, row) == "FB-AAAAAA"
    assert row.code_gid == "gid://shopify/DiscountRedeemCode/900"
    assert len(shop.names("FeedbackCodeAdd")) == adds  # not added a second time


def test_a_code_shopify_reports_failed_is_not_issued(db, shop, monkeypatch):
    shop.adds_done = False
    monkeypatch.setattr(
        shop, "_FeedbackCodeAddStatus",
        lambda v: {
            "discountRedeemCodeBulkCreation": {
                "id": v["id"], "done": True, "codesCount": 1, "importedCount": 0, "failedCount": 1,
                "codes": {"nodes": [{"code": "x", "errors": [refused("INVALID", "Bad code")], "discountRedeemCode": None}]},
            }
        },
    )
    row = survey(db)
    assert _issue(db, row) is None
    assert row.code is None and row.last_error.startswith("The reward code could not be issued")


def test_a_retry_after_a_timeout_reuses_the_same_code_and_adds_nothing(db, shop, monkeypatch):
    draws = iter(["FB-AAAAAA", "FB-BBBBBB"])
    monkeypatch.setattr(feedback_codes, "generate_code", lambda: next(draws))
    row = survey(db)
    shop.fail["FeedbackCodeAdd"] = [server_error()] * 10
    with pytest.raises(ShopifyError):
        _issue(db, row)
    assert ("drawn", row.id, "FB-AAAAAA") in shop.remembered and row.code is None
    # Shopify had in fact taken it before the call went wrong.
    shop.codes["gid://shopify/DiscountRedeemCode/901"] = {"code": "FB-AAAAAA", "uses": 0}
    shop.fail.clear()
    assert _issue(db, row) == "FB-AAAAAA"
    assert row.code_gid == "gid://shopify/DiscountRedeemCode/901"
    assert len(shop.codes) == 1  # no second code left in the discount


def test_a_retry_adds_the_remembered_code_when_shopify_never_took_it(db, shop, monkeypatch):
    monkeypatch.setattr(feedback_codes, "generate_code", lambda: "FB-AAAAAA")
    row = survey(db, code_drawn="FB-CCCCCC")
    assert _issue(db, row) == "FB-CCCCCC"
    assert [c["code"] for c in shop.codes.values()] == ["FB-CCCCCC"]


def test_the_drawn_code_is_really_written_down_before_shopify_is_asked(fresh_database):
    from app.db import SessionLocal
    from app.modules.inbox.models import FeedbackSurvey

    with SessionLocal() as own:
        row = survey(own)
        own.commit()
        survey_id = row.id
    feedback_codes._remember_drawn(survey_id, "FB-ZZZZZZ")
    with SessionLocal() as own:
        assert own.get(FeedbackSurvey, survey_id).code_drawn == "FB-ZZZZZZ"


def test_the_first_ever_discount_id_is_not_lost_when_the_settings_row_is_new(fresh_database):
    from app.db import SessionLocal
    from app.modules.inbox.models import FeedbackSettings

    with SessionLocal() as own:
        assert own.get(FeedbackSettings, 1) is None
    feedback_codes._remember_discount("gid://shopify/DiscountCodeNode/55")
    with SessionLocal() as own:
        assert own.get(FeedbackSettings, 1).discount_gid == "gid://shopify/DiscountCodeNode/55"
    feedback_codes._remember_discount("gid://shopify/DiscountCodeNode/56")
    with SessionLocal() as own:
        assert own.get(FeedbackSettings, 1).discount_gid == "gid://shopify/DiscountCodeNode/56"


def test_a_code_shopify_finishes_a_moment_later_gets_its_id(db, shop):
    shop.adds_done = False
    row = survey(db)
    code = _issue(db, row)
    assert code and row.code_gid in shop.codes


def test_a_code_the_discount_does_not_accept_is_not_issued(db, shop, monkeypatch):
    row = survey(db)
    monkeypatch.setattr(
        shop, "_FeedbackCodeAdd",
        lambda v: {"discountRedeemCodeBulkAdd": {"bulkCreation": None, "userErrors": [refused("INVALID")]}},
    )
    assert _issue(db, row) is None
    assert row.code is None and row.last_error.startswith("The reward code could not be issued")


# ── Nobody waits on Shopify ───────────────────────────────────────────────────


def test_no_code_when_the_second_app_is_not_connected(db):
    row = survey(db)
    assert _issue(db, row) is None
    assert row.code is None
    assert feedback_codes.NOT_CONNECTED in row.last_error
    assert row.last_error.startswith("The reward code could not be issued")


def test_no_code_when_the_permission_is_missing(db, shop):
    shop.scopes = "write_orders"
    row = survey(db)
    assert _issue(db, row) is None
    assert feedback_codes.NO_PERMISSION in row.last_error
    assert shop.calls == []  # refused before anything was asked of the store


def test_a_missing_permission_shopify_only_reports_when_asked_is_a_no_too(db, shop):
    shop.fail["FeedbackDiscountCheck"] = []
    row = survey(db)
    shop.fail["FeedbackDiscountCreate"] = [
        httpx.Response(200, json={"errors": [{"message": "no", "extensions": {"code": "ACCESS_DENIED"}}]})
    ]
    assert _issue(db, row) is None
    assert row.last_error.startswith("The reward code could not be issued")


def test_a_shopify_error_that_may_pass_is_raised_so_the_job_tries_again(db, shop):
    shop.fail["FeedbackDiscountCreate"] = [server_error()] * 5
    row = survey(db)
    with pytest.raises(ShopifyError):
        _issue(db, row)
    assert row.code is None and row.last_error is None  # nothing to show yet


def test_on_the_last_try_a_shopify_error_means_no_code_and_a_reason(db, shop):
    shop.fail["FeedbackDiscountCreate"] = [server_error()] * 5
    row = survey(db)
    assert _issue(db, row, final_attempt=True) is None
    assert row.last_error.startswith("The reward code could not be issued: Shopify did not answer")


def test_the_final_try_is_read_from_the_jobs_own_count(db):
    enqueue(db, JobKind.INBOX_FEEDBACK_REPLY, {"message_id": 5}, dedupe_key=f"{JobKind.INBOX_FEEDBACK_REPLY}:5")
    job = db.scalar(select(BackgroundJob).where(BackgroundJob.kind == JobKind.INBOX_FEEDBACK_REPLY))
    job.status = JobStatus.RUNNING
    for failed, final in ((0, False), (1, False), (2, True), (3, True)):
        job.attempts = failed
        db.flush()
        assert feedback_replies._final_code_attempt(db, 5) is final
    # No job to be found (run by hand): nobody is coming back to try again.
    assert feedback_replies._final_code_attempt(db, 99) is True


# ── The closing words ─────────────────────────────────────────────────────────


def _closing(db, rating, code=None, review_url=None):
    cfg = feedback.get_settings(db)
    cfg.review_url = review_url
    return feedback_replies.closing_text(SimpleNamespace(rating=rating), cfg, code)


CODE_LINE = (
    "As a thank you, here is 20% off your next order:\nFB-ABC234\n"
    "It is yours only, works once, and is valid for 30 days."
)
THANKS = {
    "loved": "Thank you! We're so glad you loved it.",
    "okay": "Thank you. Your honest answer helps us get better.",
    "unhappy": "Thank you. We're glad we could put it right.",
}
INVITATION = "If there is anything we could do better, just reply here."
REVIEW = (
    "Would you share it in a short review? It takes a minute and helps other customers "
    "choose:\nhttps://reviews.example/hba"
)


def test_a_loved_customer_is_thanked_given_her_code_and_the_review_link_and_not_also_invited_to_write(db):
    assert _closing(db, "loved", "FB-ABC234", "https://reviews.example/hba") == "\n\n".join(
        [THANKS["loved"], CODE_LINE, REVIEW]
    )


def test_a_loved_customer_without_a_review_link_is_not_sent_an_empty_one_and_is_invited_to_write(db):
    assert _closing(db, "loved", "FB-ABC234") == "\n\n".join([THANKS["loved"], CODE_LINE, INVITATION])
    assert _closing(db, "loved", "FB-ABC234", "   ") == "\n\n".join(
        [THANKS["loved"], CODE_LINE, INVITATION]
    )


def test_a_loved_customer_without_a_code_loses_only_the_code_line(db):
    assert _closing(db, "loved", None, "https://reviews.example/hba") == "\n\n".join(
        [THANKS["loved"], REVIEW]
    )
    assert _closing(db, "loved") == "\n\n".join([THANKS["loved"], INVITATION])


def test_an_okay_customer_gets_her_code_and_the_invitation_but_never_the_review_link(db):
    assert _closing(db, "okay", "FB-ABC234", "https://reviews.example/hba") == "\n\n".join(
        [THANKS["okay"], CODE_LINE, INVITATION]
    )
    assert _closing(db, "okay") == "\n\n".join([THANKS["okay"], INVITATION])


def test_an_unhappy_customer_whose_issue_was_solved_gets_thanks_and_her_code_only(db):
    assert _closing(db, "unhappy", "FB-ABC234", "https://reviews.example/hba") == (
        f"{THANKS['unhappy']}\n\n{CODE_LINE}"
    )
    assert _closing(db, "unhappy") == THANKS["unhappy"]


def test_the_reward_the_words_promise_is_the_one_shopify_holds(db):
    cfg = feedback.get_settings(db)
    said = feedback_messages.text(
        cfg, "code_line", code="X", percent=feedback.DISCOUNT_PERCENT, days=feedback.CODE_DAYS
    )
    assert f"{feedback.DISCOUNT_PERCENT}%" in said and f"{feedback.CODE_DAYS} days" in said
    assert feedback_codes.DISCOUNT_TITLE == f"Feedback {feedback.DISCOUNT_PERCENT}%"
    assert feedback_codes.CODE_VALID_FOR == timedelta(days=feedback.CODE_DAYS)


# ── Through the reply job ─────────────────────────────────────────────────────


@pytest.fixture()
def world(db, may_send):
    chat = conversation(db, wrote_ago=timedelta(days=2))
    row = survey(db, conversation_id=chat.id)
    asked: list = []
    return SimpleNamespace(row=row, chat=chat, asked=asked, client=meta(asked))


def _reason_job(db, world, rating="loved", reason="quality"):
    """Her rating and reason are taken; the job that sends what follows is
    returned as its message id, not yet run."""
    apply(db, template_tap(f"fb_{rating}_7001", "x", "wamid.T1", ago=timedelta(seconds=50)))
    for _, _, payload in jobs(db, JobKind.INBOX_FEEDBACK_REPLY):
        feedback_replies.reply(db, payload["message_id"], world.client)
    asked_before = len(world.asked)
    apply(
        db,
        interactive_tap("list_reply", f"fbr_{reason}_{world.row.id}", "x", "wamid.T2", ago=timedelta(seconds=40)),
    )
    message_id = jobs(db, JobKind.INBOX_FEEDBACK_REPLY)[-1][2]["message_id"]
    return message_id, asked_before


def test_the_closing_message_carries_her_code_and_stamps_when_it_was_sent(db, world, shop):
    feedback.get_settings(db).review_url = "https://reviews.example/hba"
    message_id, before = _reason_job(db, world)
    feedback_replies.reply(db, message_id, world.client)
    [closing] = world.asked[before:]
    row = world.row
    assert CODE_SHAPE.search(closing["text"]["body"]) and row.code in closing["text"]["body"]
    assert "helps other customers choose:\nhttps://reviews.example/hba" in closing["text"]["body"]
    assert closing["text"]["body"] == feedback_replies.closing_text(row, feedback.get_settings(db), row.code)
    assert row.code_sent_at is not None and row.last_error is None


def test_a_second_run_of_the_job_sends_nothing_and_issues_nothing(db, world, shop):
    message_id, before = _reason_job(db, world)
    feedback_replies.reply(db, message_id, world.client)
    code, adds = world.row.code, len(shop.names("FeedbackCodeAdd"))
    assert feedback_replies.reply(db, message_id, world.client) is None
    assert len(world.asked) == before + 1 and len(shop.names("FeedbackCodeAdd")) == adds
    assert world.row.code == code


def test_without_the_app_connected_she_is_thanked_all_the_same_exactly_once(db, world):
    message_id, before = _reason_job(db, world)
    feedback_replies.reply(db, message_id, world.client)
    [closing] = world.asked[before:]
    assert closing["text"]["body"] == f"Thank you, Nour! We're so glad you loved it.\n\n{INVITATION}"
    row = world.row
    assert row.code is None and row.code_sent_at is None
    assert row.last_error.startswith("The reward code could not be issued")
    assert feedback_replies.reply(db, message_id, world.client) is None
    assert len(world.asked) == before + 1


def test_without_the_permission_she_is_thanked_without_a_code(db, world, shop):
    shop.scopes = "write_orders"
    message_id, before = _reason_job(db, world)
    feedback_replies.reply(db, message_id, world.client)
    assert len(world.asked) == before + 1 and world.row.code is None
    assert feedback_codes.NO_PERMISSION in world.row.last_error


def test_a_shopify_error_is_tried_again_before_she_is_thanked_without_a_code(db, world, shop):
    shop.fail["FeedbackDiscountCreate"] = [server_error()] * 20
    message_id, before = _reason_job(db, world)
    # The job's first tries: nothing is sent, the error reaches the worker.
    for _ in range(2):
        with pytest.raises(ShopifyError):
            feedback_replies.reply(db, message_id, world.client)
        assert len(world.asked) == before and world.row.code_sent_at is None
    # The last try: she is thanked, without a code, once.
    feedback_replies.reply(db, message_id, world.client, final_attempt=True)
    [closing] = world.asked[before:]
    assert closing["text"]["body"] == f"Thank you, Nour! We're so glad you loved it.\n\n{INVITATION}"
    assert "Shopify did not answer" in world.row.last_error
    assert feedback_replies.reply(db, message_id, world.client, final_attempt=True) is None
    assert len(world.asked) == before + 1


def test_a_retry_that_gets_through_sends_the_code(db, world, shop):
    shop.fail["FeedbackDiscountCreate"] = [server_error()] * 5  # the whole first try
    message_id, before = _reason_job(db, world)
    with pytest.raises(ShopifyError):
        feedback_replies.reply(db, message_id, world.client)
    feedback_replies.reply(db, message_id, world.client)
    [closing] = world.asked[before:]
    assert CODE_SHAPE.search(closing["text"]["body"]) and world.row.code_sent_at is not None


def test_a_code_whatsapp_refused_to_carry_is_not_marked_sent(db, world, shop):
    message_id, before = _reason_job(db, world)
    feedback_replies.reply(db, message_id, meta([], refuse=(400, 132001)))
    row = world.row
    assert row.code and row.code_sent_at is None
    assert row.last_error.startswith("A follow-up could not be sent")


def test_the_unhappy_customers_code_comes_after_her_answer_to_would_you_order_again(db, world, shop):
    row = world.row
    row.rating, row.reason, row.step = "unhappy", "quality", "reorder"
    row.solved_asked_at = row.resolved_at = utcnow()
    row.solved = True
    apply(db, interactive_tap("button_reply", f"fbo_maybe_{row.id}", "Maybe", "wamid.T9"))
    message_id = jobs(db, JobKind.INBOX_FEEDBACK_REPLY)[-1][2]["message_id"]
    feedback_replies.reply(db, message_id, world.client)
    body = world.asked[-1]["text"]["body"]
    assert body == (
        "Thank you, Nour. We're glad we could put it right.\n\n"
        f"As a thank you, here is 20% off your next order:\n{row.code}\n"
        "It is yours only, works once, and is valid for 30 days."
    )
    assert row.code_sent_at is not None


# ── Used or not ───────────────────────────────────────────────────────────────


def _with_code(db, order_id, code, *, sent_ago=timedelta(days=2), **changes):
    return survey(
        db, order_id, wa_message_id=f"wamid.FIRST{order_id}", code=code,
        code_sent_at=utcnow() - sent_ago if sent_ago is not None else None,
        code_expires_at=utcnow() + timedelta(days=28), **changes,
    )


def _spent(db, order_id, codes, *, ago):
    return order(
        db, order_id, delivered_ago=timedelta(days=9),
        placed_at=utcnow() - ago, discount_codes=codes, order_number=f"#{order_id}",
    )


def test_a_code_is_used_when_an_order_placed_after_it_was_sent_carries_it(db):
    row = _with_code(db, "7001", "FB-ABC234")
    spent = _spent(db, "8001", ["FB-ABC234"], ago=timedelta(days=1))
    assert feedback_codes.mark_used(db) == 1
    db.refresh(row)
    assert row.code_used_at == spent.placed_at and row.code_order_name == "#8001"


def test_the_code_is_matched_without_regard_to_case(db):
    row = _with_code(db, "7001", "FB-ABC234")
    _spent(db, "8001", ["fb-abc234", "OTHER10"], ago=timedelta(days=1))
    assert feedback_codes.mark_used(db) == 1
    db.refresh(row)
    assert row.code_used_at is not None


def test_an_order_placed_before_the_code_was_sent_is_not_its_use(db):
    row = _with_code(db, "7001", "FB-ABC234", sent_ago=timedelta(hours=2))
    _spent(db, "8001", ["FB-ABC234"], ago=timedelta(days=1))
    assert feedback_codes.mark_used(db) == 0
    db.refresh(row)
    assert row.code_used_at is None


def test_a_code_never_sent_is_never_marked_used(db):
    row = _with_code(db, "7001", "FB-ABC234", sent_ago=None)
    _spent(db, "8001", ["FB-ABC234"], ago=timedelta(hours=1))
    assert feedback_codes.mark_used(db) == 0
    db.refresh(row)
    assert row.code_used_at is None


def test_the_first_order_to_use_a_code_is_the_one_recorded_and_it_stays(db):
    row = _with_code(db, "7001", "FB-ABC234")
    first = _spent(db, "8001", ["FB-ABC234"], ago=timedelta(days=1))
    _spent(db, "8002", ["FB-ABC234"], ago=timedelta(hours=1))
    assert feedback_codes.mark_used(db) == 1
    db.refresh(row)
    assert row.code_order_name == "#8001" and row.code_used_at == first.placed_at
    assert feedback_codes.mark_used(db) == 0  # settled: not looked at again


def test_every_code_is_marked_in_one_query(db):
    rows = [_with_code(db, str(7000 + n), f"FB-AAAA{n}2") for n in range(1, 4)]
    for n in range(1, 4):
        _spent(db, str(8000 + n), [f"FB-AAAA{n}2"], ago=timedelta(hours=n))
    statements: list[str] = []
    listener = lambda conn, cursor, statement, *rest: statements.append(statement)  # noqa: E731
    event.listen(db.get_bind(), "before_cursor_execute", listener)
    try:
        assert feedback_codes.mark_used(db) == 3
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    assert len(statements) == 1 and "UPDATE feedback_survey" in statements[0]
    for row in rows:
        db.refresh(row)
        assert row.code_used_at is not None


def test_the_sweep_marks_used_codes_and_needs_no_shopify(db, feature_on):
    started(db)
    row = _with_code(db, "7001", "FB-ABC234")
    _spent(db, "8001", ["FB-ABC234"], ago=timedelta(hours=3))
    asked: list = []
    assert feedback.sweep(db, client=shopify({}, asked)) == 0
    db.refresh(row)
    assert row.code_used_at is not None and asked == []


# ── Thirty days ───────────────────────────────────────────────────────────────


def _out_there(db, shop, order_id, code, *, expired=True, gid=True, **changes):
    """A survey whose code is in Shopify's discount, expired or not."""
    shop.discount = shop.discount or "gid://shopify/DiscountCodeNode/1"
    redeem_id = f"gid://shopify/DiscountRedeemCode/{order_id}"
    shop.codes[redeem_id] = {"code": code, "uses": 0}
    feedback.get_settings(db).discount_gid = shop.discount
    return _with_code(
        db, order_id, code, code_gid=redeem_id if gid else None,
        **{"sent_ago": timedelta(days=31)}, **changes,
    ), redeem_id


def expire(db, **kwargs):
    """The session does not flush by itself: what a test set up is written first."""
    db.flush()
    return feedback_codes.expire(db, **kwargs)


def _expire_on(row, *, expired):
    row.code_expires_at = utcnow() - timedelta(days=1) if expired else utcnow() + timedelta(days=3)


def test_an_unused_code_past_its_thirty_days_is_removed_from_shopify(db, shop, feature_on):
    row, redeem_id = _out_there(db, shop, "7001", "FB-ABC234")
    _expire_on(row, expired=True)
    # Shopify deletes in the background: asked for, not yet marked.
    assert expire(db) == 0
    assert redeem_id not in shop.codes and row.code_removed_at is None
    [removal] = shop.names("FeedbackCodesRemove")
    assert removal == {"discountId": shop.discount, "ids": [redeem_id]}
    # The next run finds it gone and only then records it.
    assert expire(db) == 1 and row.code_removed_at is not None
    assert len(shop.names("FeedbackCodesRemove")) == 1


def test_a_code_whose_delete_is_still_running_is_asked_again_harmlessly(db, shop, monkeypatch):
    row, redeem_id = _out_there(db, shop, "7001", "FB-ABC234")
    _expire_on(row, expired=True)
    monkeypatch.setattr(
        shop, "_FeedbackCodesRemove",
        lambda v: {"discountCodeRedeemCodeBulkDelete": {"job": {"id": "j"}, "userErrors": []}},
    )
    assert expire(db) == 0 and expire(db) == 0
    assert row.code_removed_at is None and redeem_id in shop.codes
    assert len(shop.names("FeedbackCodesRemove")) == 2


def test_a_code_still_inside_its_thirty_days_is_left_alone(db, shop):
    row, redeem_id = _out_there(db, shop, "7001", "FB-ABC234")
    _expire_on(row, expired=False)
    assert expire(db) == 0
    assert redeem_id in shop.codes and row.code_removed_at is None
    assert shop.calls == []


def test_a_used_code_is_never_removed(db, shop):
    row, redeem_id = _out_there(db, shop, "7001", "FB-ABC234")
    _expire_on(row, expired=True)
    row.code_used_at = utcnow() - timedelta(days=10)
    assert expire(db) == 0
    assert redeem_id in shop.codes and row.code_removed_at is None and shop.calls == []


def test_a_code_an_indexed_order_used_is_found_used_before_anything_is_removed(db, shop):
    row, redeem_id = _out_there(db, shop, "7001", "FB-ABC234")
    _expire_on(row, expired=True)
    _spent(db, "8001", ["fb-abc234"], ago=timedelta(days=5))
    assert expire(db) == 0
    db.refresh(row)
    assert redeem_id in shop.codes and row.code_used_at is not None


def test_a_code_shopify_says_was_used_is_left_for_the_orders_to_catch_up(db, shop):
    row, redeem_id = _out_there(db, shop, "7001", "FB-ABC234")
    _expire_on(row, expired=True)
    shop.codes[redeem_id]["uses"] = 1  # redeemed; the order is not indexed yet
    assert expire(db) == 0
    assert redeem_id in shop.codes and row.code_removed_at is None
    assert shop.names("FeedbackCodesRemove") == []


def test_a_code_already_removed_is_not_removed_again(db, shop):
    row, _ = _out_there(db, shop, "7001", "FB-ABC234")
    _expire_on(row, expired=True)
    row.code_removed_at = utcnow() - timedelta(days=2)
    assert expire(db) == 0 and shop.calls == []


def test_a_code_shopify_no_longer_has_counts_as_removed(db, shop):
    row, redeem_id = _out_there(db, shop, "7001", "FB-ABC234")
    _expire_on(row, expired=True)
    del shop.codes[redeem_id]
    assert expire(db) == 1
    assert row.code_removed_at is not None and shop.names("FeedbackCodesRemove") == []


def test_a_code_whose_id_was_never_learned_is_found_by_its_text(db, shop):
    row, redeem_id = _out_there(db, shop, "7001", "FB-ABC234", gid=False)
    _expire_on(row, expired=True)
    assert expire(db) == 0 and redeem_id not in shop.codes
    assert expire(db) == 1 and row.code_removed_at is not None


def test_codes_are_removed_in_batches(db, shop):
    rows = []
    for number in range(5):
        row, _ = _out_there(db, shop, str(7001 + number), f"FB-BBBB{number}2")
        _expire_on(row, expired=True)
        rows.append(row)
    assert expire(db, batch_size=2) == 0
    sizes = [len(call["ids"]) for call in shop.names("FeedbackCodesRemove")]
    assert sizes == [2, 2, 1] and shop.codes == {}
    assert expire(db, batch_size=2) == 5
    assert all(row.code_removed_at is not None for row in rows)


def test_only_the_expired_unused_ones_among_many_are_removed(db, shop):
    old, old_id = _out_there(db, shop, "7001", "FB-AAAA22")
    fresh, fresh_id = _out_there(db, shop, "7002", "FB-AAAA33")
    used, used_id = _out_there(db, shop, "7003", "FB-AAAA44")
    _expire_on(old, expired=True)
    _expire_on(fresh, expired=False)
    _expire_on(used, expired=True)
    used.code_used_at = utcnow() - timedelta(days=9)
    assert expire(db) == 0
    assert set(shop.codes) == {fresh_id, used_id}
    assert expire(db) == 1 and old.code_removed_at is not None


def test_a_shopify_refusal_removes_nothing_and_marks_nothing(db, shop, monkeypatch):
    row, redeem_id = _out_there(db, shop, "7001", "FB-ABC234")
    _expire_on(row, expired=True)
    monkeypatch.setattr(
        shop, "_FeedbackCodesRemove",
        lambda v: {"discountCodeRedeemCodeBulkDelete": {"job": None, "userErrors": [refused("INVALID")]}},
    )
    with pytest.raises(ShopifyError):
        expire(db)
    assert row.code_removed_at is None


def test_the_expiry_job_does_nothing_with_the_flag_off(db, shop, monkeypatch):
    row, redeem_id = _out_there(db, shop, "7001", "FB-ABC234")
    _expire_on(row, expired=True)
    monkeypatch.setattr("app.config.settings.inbox_feedback_enabled", False)
    db.flush()
    feedback_codes._handle_expire(db, {})
    assert shop.calls == [] and redeem_id in shop.codes and row.code_removed_at is None


def test_the_expiry_job_removes_expired_codes_with_the_flag_on(db, shop, feature_on):
    row, redeem_id = _out_there(db, shop, "7001", "FB-ABC234")
    _expire_on(row, expired=True)
    db.flush()
    feedback_codes._handle_expire(db, {})
    assert redeem_id not in shop.codes and row.code_removed_at is None
    feedback_codes._handle_expire(db, {})
    assert row.code_removed_at is not None


def test_the_expiry_job_needs_the_permission_and_says_so(db, shop, feature_on):
    row, _ = _out_there(db, shop, "7001", "FB-ABC234")
    _expire_on(row, expired=True)
    shop.scopes = "write_orders"
    with pytest.raises(PermanentFailure, match="write_discounts"):
        expire(db)


def test_the_expiry_job_is_daily_and_runs_in_the_inbox_lane():
    assert SCHEDULE[JobKind.INBOX_FEEDBACK_EXPIRE_CODES] == (timedelta(days=1), {})
    assert JobKind.INBOX_FEEDBACK_EXPIRE_CODES in INBOX_WORK
    from app.worker import HANDLERS

    assert JobKind.INBOX_FEEDBACK_EXPIRE_CODES in HANDLERS


def test_the_reply_job_passes_its_own_try_count_on(db, world, shop, feature_on, monkeypatch):
    """First tries raise for the worker to retry; the third thanks her without a code."""
    shop.fail["FeedbackDiscountCreate"] = [server_error()] * 40
    message_id, before = _reason_job(db, world)
    job = db.scalar(
        select(BackgroundJob).where(
            BackgroundJob.kind == JobKind.INBOX_FEEDBACK_REPLY,
            BackgroundJob.dedupe_key == f"{JobKind.INBOX_FEEDBACK_REPLY}:{message_id}",
        )
    )
    job.status = JobStatus.RUNNING
    # The handler builds its own Meta client: give it ours.
    monkeypatch.setattr(feedback_replies.outbound, "_client", lambda _db: world.client)
    for failed in (0, 1):
        job.attempts = failed
        db.flush()
        with pytest.raises(ShopifyError):
            feedback_replies._handle_reply(db, {"message_id": message_id})
        assert len(world.asked) == before
    job.attempts = 2
    db.flush()
    feedback_replies._handle_reply(db, {"message_id": message_id})
    assert len(world.asked) == before + 1 and world.row.code is None
    assert "Shopify did not answer" in world.row.last_error
