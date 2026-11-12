"""The reward for a finished feedback survey: one Shopify discount, a code each
(ADR 0083, point 5).

**One discount, many codes.** The platform keeps a single discount, *Feedback
20%*: 20% off the whole order, all customers, one use per code, once per
customer, no end date. Each customer who finishes gets a code of her own
inside it (``FB-`` and six letters and digits), good for 30 days. A discount
holds many codes and its usage limit counts per code, so nothing is cluttered
and a code cannot be shared twice.

**Written through the second Shopify app**, the one that writes order tags
(``tags.tags_client``) - never the connection that reads money, which stays
read-only (ADR 0015). That app must be allowed ``write_discounts``;
``codes_ready`` says whether it is.

**The thank-you never waits on Shopify.** The reward is a surprise, so when a
code cannot be issued - the app not connected, the permission missing, Shopify
down after the job's retries - the closing message goes out without a code
and the survey says so in ``last_error``. ``issue_code`` raises on a Shopify
error that may pass, so the reply job tries again first; it gives up on the
code only on the job's last try (``final_attempt``), never on the message.

**Crash-safe.** Shopify has no "undo" the platform could run after a crash,
so what Shopify has accepted is written down at once, in a transaction of its
own, before anything else can fail: the discount's id (``ensure_discount``)
and a survey's code (``issue_code``). A retried job finds them and issues
nothing twice. Two jobs racing for the first code wait for each other on a
lock, so only one creates the discount.

**Used or not** is read from the orders already indexed (``mark_used``), in
one query, no Shopify call. **After 30 days** an unused code is removed from
Shopify (``expire``, daily); a used one never is.
"""

import logging
import secrets
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.core.businesstime import utcnow
from app.modules.inbox.models import FeedbackSettings, FeedbackSurvey
from app.modules.inbox.services import connection, feedback, tags
from app.shared.services.jobs import JobKind, PermanentFailure
from app.shared.services.shopify.client import (
    ShopifyClient,
    ShopifyError,
    ShopifyMissingScope,
    ShopifyNotConfigured,
)
from app.worker import register_handler

logger = logging.getLogger(__name__)

# ── What the discount and its codes look like ─────────────────────────────────

DISCOUNT_TITLE = f"Feedback {feedback.DISCOUNT_PERCENT}%"
CODE_PREFIX = "FB-"
CODE_LENGTH = 6
#: Capitals and digits that cannot be misread when typed from a message: no
#: 0 or O, no 1, I or L.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
#: How long a code lasts from the moment it is issued.
CODE_VALID_FOR = timedelta(days=feedback.CODE_DAYS)
#: A freshly drawn code that is already taken (here or in Shopify) is drawn
#: again, this many times.
DRAW_TRIES = 5
#: The discount's required first code is never given to anyone, so it is
#: long enough that nobody could guess it.
SETUP_CODE_LENGTH = 14
#: One advisory lock number for "the discount is being made" (an arbitrary
#: constant: it only has to be the same everywhere).
DISCOUNT_LOCK = 8_301_083_001

#: The reply job gives up on a code on this attempt: three tries is about a
#: minute and a half, after which the thank-you is worth more than the code.
CODE_ATTEMPTS = 3

#: Removals go to Shopify this many codes at a time, and one daily run takes
#: at most this many batches (a day's expiries are a handful).
REMOVE_BATCH = 100
REMOVE_BATCHES = 10

# Why a code was not issued (``last_error``; Settings and the sheet show it).
NOT_ISSUED = "The reward code could not be issued: {why}"
NOT_CONNECTED = (
    "The second Shopify app is not connected (Settings → Integrations), so no reward "
    "codes can be made."
)
NO_PERMISSION = (
    "The second Shopify app may not manage discounts. Add the “Write discounts” "
    f"permission ({connection.DISCOUNTS_SCOPE}) to it in Shopify and reconnect it."
)
SHOPIFY_DOWN = "Shopify did not answer: {why}"

# ── Shopify ───────────────────────────────────────────────────────────────────

DISCOUNT_CHECK = """
query FeedbackDiscountCheck($id: ID!) {
  discountNode(id: $id) { id }
}
"""
DISCOUNT_CREATE = """
mutation FeedbackDiscountCreate($input: DiscountCodeBasicInput!) {
  discountCodeBasicCreate(basicCodeDiscount: $input) {
    codeDiscountNode { id }
    userErrors { code field message }
  }
}
"""
_CREATION = """
    id
    done
    codesCount
    importedCount
    failedCount
    codes(first: 1) {
      nodes { code errors { code message } discountRedeemCode { id } }
    }
"""
CODE_ADD = (
    """
mutation FeedbackCodeAdd($discountId: ID!, $codes: [DiscountRedeemCodeInput!]!) {
  discountRedeemCodeBulkAdd(discountId: $discountId, codes: $codes) {
    bulkCreation {"""
    + _CREATION
    + """    }
    userErrors { code field message }
  }
}
"""
)
CODE_ADD_STATUS = (
    """
query FeedbackCodeAddStatus($id: ID!) {
  discountRedeemCodeBulkCreation(id: $id) {"""
    + _CREATION
    + """  }
}
"""
)
#: Existence and use of codes we know the id of. A code Shopify no longer has
#: comes back as null.
CODES_BY_ID = """
query FeedbackCodesById($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on DiscountRedeemCode { id code asyncUsageCount }
  }
}
"""
#: One code, found by its text inside the discount, for one whose id was not
#: known when it was issued (Shopify adds codes in the background).
CODE_BY_CODE = """
query FeedbackCodeByCode($id: ID!, $code: String!) {
  discountNode(id: $id) {
    discount {
      ... on DiscountCodeBasic {
        codes(first: 5, query: $code) { nodes { id code asyncUsageCount } }
      }
    }
  }
}
"""
CODES_REMOVE = """
mutation FeedbackCodesRemove($discountId: ID!, $ids: [ID!]!) {
  discountCodeRedeemCodeBulkDelete(discountId: $discountId, ids: $ids) {
    job { id }
    userErrors { code field message }
  }
}
"""

#: A userError that says the code is already there: draw another.
_TAKEN = frozenset({"TAKEN", "DUPLICATE", "IMPLICIT_DUPLICATE"})


class CodeRefused(ShopifyError):
    """Shopify understood and said no. Asking again will not change it."""


def _errors(payload: dict | None) -> list[dict]:
    return [e for e in ((payload or {}).get("userErrors") or []) if isinstance(e, dict)]


def _say(errors: list[dict]) -> str:
    return "; ".join(str(e.get("message")) for e in errors)[:200]


def _refuse_or_retry(what: str, errors: list[dict]) -> ShopifyError:
    """What to raise for Shopify's userErrors: an internal error of Shopify's
    may pass, anything else is a no."""
    why = f"Shopify refused {what}: {_say(errors)}"
    if any(e.get("code") == "INTERNAL_ERROR" for e in errors):
        return ShopifyError(why)
    return CodeRefused(why)


def generate_code() -> str:
    """``FB-`` and six characters from ``CODE_ALPHABET``. Not checked for
    being taken: ``_fresh_code`` does that."""
    return CODE_PREFIX + "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _fresh_code(db: Session) -> str:
    """A code no survey has or has drawn. (Shopify has the last word: see
    ``_add_code``.)"""
    for _ in range(DRAW_TRIES):
        code = generate_code()
        if not db.scalar(
            select(FeedbackSurvey.id)
            .where(
                (func.upper(FeedbackSurvey.code) == code)
                | (func.upper(FeedbackSurvey.code_drawn) == code)
            )
            .limit(1)
        ):
            return code
    raise ShopifyError("Could not draw a reward code nobody has.")  # 31^6 makes this a sign of something wrong


# ── Is it set up? ─────────────────────────────────────────────────────────────


def codes_ready(db: Session) -> tuple[bool, str | None]:
    """Whether reward codes can be issued, and if not, why in plain words.

    The second Shopify app must be connected and its token must hold
    ``write_discounts``. The scopes are what Shopify reports when the app's
    credentials are exchanged for a token, so this makes one call to Shopify;
    nothing is saved. For Settings, beside the switch that turns the feature on.
    """
    try:
        client = tags.tags_client(db)
        client.require_scope(connection.DISCOUNTS_SCOPE)
    except PermanentFailure:
        return False, NOT_CONNECTED
    except ShopifyMissingScope:
        return False, NO_PERMISSION
    except ShopifyNotConfigured:
        return False, NOT_CONNECTED
    except ShopifyError as exc:
        return False, SHOPIFY_DOWN.format(why=exc)
    return True, None


# ── The one discount ──────────────────────────────────────────────────────────


def _remember_discount(gid: str) -> None:
    """Write the discount's id down, in a transaction of its own and committed
    now, so a job that fails afterwards cannot make us forget a discount
    Shopify already has (and make a second one next time)."""
    from app.db import SessionLocal

    with SessionLocal() as own:
        # An upsert: the settings row may exist only uncommitted, in the
        # caller's transaction (``get_settings`` makes it the first time), and
        # a plain UPDATE would then find nothing and silently lose the id.
        own.execute(
            insert(FeedbackSettings)
            .values(id=1, discount_gid=gid, updated_at=utcnow())
            .on_conflict_do_update(
                index_elements=["id"], set_={"discount_gid": gid, "updated_at": utcnow()}
            )
        )
        own.commit()


def _discount_exists(client: ShopifyClient, gid: str) -> bool:
    data = client.execute(DISCOUNT_CHECK, {"id": gid})
    return bool((data or {}).get("discountNode"))


def _create_discount(client: ShopifyClient, now: datetime) -> str:
    setup_code = CODE_PREFIX + "".join(secrets.choice(CODE_ALPHABET) for _ in range(SETUP_CODE_LENGTH))
    data = client.execute(
        DISCOUNT_CREATE,
        {
            "input": {
                "title": DISCOUNT_TITLE,
                # Shopify wants a first code to make a code discount. This one
                # is never given to anyone.
                "code": setup_code,
                "startsAt": now.isoformat(),
                "context": {"all": "ALL"},
                "customerGets": {
                    "value": {"percentage": feedback.DISCOUNT_PERCENT / 100},
                    "items": {"all": True},
                },
                # One use per code, and one per customer.
                "usageLimit": 1,
                "appliesOncePerCustomer": True,
            }
        },
    )
    payload = (data or {}).get("discountCodeBasicCreate") or {}
    if _errors(payload):
        raise _refuse_or_retry("the feedback discount", _errors(payload))
    gid = ((payload.get("codeDiscountNode")) or {}).get("id")
    if not gid:
        raise ShopifyError("Shopify did not return the feedback discount's id.")
    return str(gid)


def ensure_discount(
    db: Session,
    client: ShopifyClient,
    *,
    now: datetime | None = None,
    remember: Callable[[str], None] | None = None,
) -> str:
    """Shopify's id for the one *Feedback 20%* discount: the stored one if
    Shopify still has it, otherwise a new one, made once and stored.

    A discount deleted by hand is made again. Two jobs asking at once wait
    for each other on a lock held to the end of the transaction, so the
    second finds the first's discount instead of making another.
    """
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": DISCOUNT_LOCK})
    feedback.get_settings(db)
    cfg = db.execute(
        select(FeedbackSettings)
        .where(FeedbackSettings.id == 1)
        .execution_options(populate_existing=True)
    ).scalar_one()
    if cfg.discount_gid and _discount_exists(client, cfg.discount_gid):
        return cfg.discount_gid
    if cfg.discount_gid:
        logger.warning("the feedback discount is gone from Shopify; making it again")
    gid = _create_discount(client, now or utcnow())
    (remember or _remember_discount)(gid)
    cfg.discount_gid = gid
    cfg.updated_at = utcnow()
    db.flush()
    return gid


# ── A code each ───────────────────────────────────────────────────────────────


def _remember_code(
    survey_id: int, code: str, gid: str | None, expires_at: datetime
) -> None:
    """Write a survey's code down, in a transaction of its own and committed
    now, so a retried job reuses it instead of issuing a second."""
    from app.db import SessionLocal

    with SessionLocal() as own:
        own.execute(
            update(FeedbackSurvey)
            .where(FeedbackSurvey.id == survey_id, FeedbackSurvey.code.is_(None))
            .values(code=code, code_gid=gid, code_expires_at=expires_at, updated_at=utcnow())
        )
        own.commit()


def _remember_drawn(survey_id: int, code: str) -> None:
    """Write the code drawn for a survey down, in a transaction of its own and
    committed now, *before* Shopify is asked to add it: if the call times out
    after Shopify took it, the retry reuses this text instead of drawing (and
    leaving behind) another."""
    from app.db import SessionLocal

    with SessionLocal() as own:
        own.execute(
            update(FeedbackSurvey)
            .where(FeedbackSurvey.id == survey_id, FeedbackSurvey.code.is_(None))
            .values(code_drawn=code, updated_at=utcnow())
        )
        own.commit()


def _read_creation(node: dict | None, code: str) -> tuple[str, str | None]:
    """``(what, redeem code id)``: ``what`` is ``added``, ``pending`` (Shopify
    has not finished adding it) or ``taken`` (it is already in the discount)."""
    node = node or {}
    if not node.get("done"):
        return "pending", None
    nodes = ((node.get("codes") or {}).get("nodes")) or []
    if node.get("failedCount"):
        errors = [e for item in nodes for e in (item.get("errors") or [])]
        if any(e.get("code") in _TAKEN for e in errors):
            return "taken", None
        raise _refuse_or_retry(f"code {code}", errors or [{"message": "it did not add the code"}])
    gid = next(
        (((item.get("discountRedeemCode") or {}).get("id")) for item in nodes), None
    )
    return "added", str(gid) if gid else None


def _add_code(client: ShopifyClient, discount_gid: str, code: str) -> tuple[str, str | None]:
    """Add one code to the discount. Returns what ``_read_creation`` does.

    Shopify adds codes in the background, so this asks once more how it went
    if the answer to the mutation says it is not done. A code still not
    confirmed after that **raises** (a retryable error): a code Shopify has
    not confirmed is never stored as hers or sent. The retry finds the code
    by its text (``_issue``), so nothing is added twice.
    """
    data = client.execute(CODE_ADD, {"discountId": discount_gid, "codes": [{"code": code}]})
    payload = (data or {}).get("discountRedeemCodeBulkAdd") or {}
    errors = _errors(payload)
    if errors:
        if any(e.get("code") in _TAKEN for e in errors):
            return "taken", None
        raise _refuse_or_retry(f"code {code}", errors)
    creation = payload.get("bulkCreation") or {}
    state, gid = _read_creation(creation, code)
    if state == "pending" and creation.get("id"):
        status = client.execute(CODE_ADD_STATUS, {"id": creation["id"]})
        state, gid = _read_creation((status or {}).get("discountRedeemCodeBulkCreation"), code)
    if state == "pending":
        raise ShopifyError(f"Shopify has not finished adding code {code} yet.")
    return state, gid


def _find_code(client: ShopifyClient, discount_gid: str, code: str) -> dict | None:
    """The code as the discount has it now (``id``, use count), by its text,
    or None."""
    data = client.execute(CODE_BY_CODE, {"id": discount_gid, "code": code})
    nodes = (
        (((data or {}).get("discountNode") or {}).get("discount") or {}).get("codes") or {}
    ).get("nodes") or []
    return next(
        (n for n in nodes if str(n.get("code") or "").upper() == str(code).upper()), None
    )


def _issue(
    db: Session,
    survey: FeedbackSurvey,
    client: ShopifyClient,
    remember: Callable[..., None],
    now: datetime,
    remember_drawn: Callable[[int, str], None] | None = None,
) -> str:
    """Draw (or, on a retry, reuse) the survey's code, make sure Shopify has
    it, and only then store it as hers.

    The drawn text is written down first, so a retry after a timeout asks the
    discount for that very text and adopts it if Shopify did take it. A code
    Shopify has not confirmed raises (the job retries) and is never stored.
    """
    discount_gid = ensure_discount(db, client, now=now)
    note = remember_drawn or _remember_drawn
    for _ in range(DRAW_TRIES):
        code = survey.code_drawn
        retry = bool(code)
        if not code:
            code = _fresh_code(db)
            note(survey.id, code)
            # Not marked as changed: the row is already written, and a dirty
            # row would hold a lock the own-session writes then wait on.
            set_committed_value(survey, "code_drawn", code)
        gid: str | None = None
        found = _find_code(client, discount_gid, code) if retry else None
        if found:
            state, gid = "added", str(found["id"])
        else:
            state, gid = _add_code(client, discount_gid, code)
            if state == "taken" and retry:
                found = _find_code(client, discount_gid, code)
                if found:
                    state, gid = "added", str(found["id"])
        if state == "taken":
            # Someone else's: draw another.
            set_committed_value(survey, "code_drawn", None)
            continue
        expires_at = now + CODE_VALID_FOR
        remember(survey.id, code, gid, expires_at)
        survey.code, survey.code_gid, survey.code_expires_at = code, gid, expires_at
        survey.updated_at = now
        db.flush()
        return code
    raise ShopifyError("Shopify said every reward code we drew was already taken.")


def _without_code(survey: FeedbackSurvey, why: Exception | str) -> None:
    """She is thanked without a code, and the survey says why."""
    survey.last_error = NOT_ISSUED.format(why=why)[:300]
    survey.updated_at = utcnow()
    logger.warning("no reward code for feedback %s: %s", survey.id, why)


def issue_code(
    db: Session,
    survey: FeedbackSurvey,
    *,
    final_attempt: bool = False,
    now: datetime | None = None,
    remember: Callable[..., None] | None = None,
) -> str | None:
    """Her reward code: the one she already has, or a new one added to the
    discount. None if one cannot be issued, with the reason in ``last_error``.

    Safe to call twice for one survey - the second call returns the first's
    code and asks Shopify nothing. What cannot work (the app not connected,
    ``write_discounts`` missing, Shopify saying no) returns None at once. A
    Shopify error that may pass **raises**, so the job that called it is tried
    again; only with ``final_attempt`` is it given up on and None returned.
    """
    if survey.code:
        return survey.code
    try:
        client = tags.tags_client(db)
        client.require_scope(connection.DISCOUNTS_SCOPE)
        return _issue(db, survey, client, remember or _remember_code, now or utcnow())
    except PermanentFailure:
        _without_code(survey, NOT_CONNECTED)
    except ShopifyNotConfigured:
        _without_code(survey, NOT_CONNECTED)
    except ShopifyMissingScope:
        _without_code(survey, NO_PERMISSION)
    except CodeRefused as exc:
        _without_code(survey, exc)
    except ShopifyError as exc:
        if not final_attempt:
            raise
        _without_code(survey, SHOPIFY_DOWN.format(why=exc))
    return None


def code_sent(survey: FeedbackSurvey, at: datetime | None = None) -> None:
    """The message carrying her code went out."""
    if survey.code and survey.code_sent_at is None:
        survey.code_sent_at = at or utcnow()
        survey.updated_at = survey.code_sent_at


# ── Used or not ───────────────────────────────────────────────────────────────

#: Every sent, unused code that an order placed since it was sent carries, in
#: one statement. Case-insensitive, as Shopify treats codes. The earliest such
#: order is the one that used it.
_MARK_USED = text(
    """
    WITH open_codes AS (
        SELECT id, upper(code) AS ucode, code_sent_at
        FROM feedback_survey
        WHERE code IS NOT NULL
          AND code_sent_at IS NOT NULL
          AND code_used_at IS NULL
    ),
    -- Orders placed since the earliest open code was sent, their codes
    -- unnested and uppercased once each, not once per pair.
    order_codes AS (
        SELECT o.shopify_order_id, o.placed_at, o.order_number, upper(c.code) AS ucode
        FROM order_index AS o
        CROSS JOIN LATERAL unnest(o.discount_codes) AS c(code)
        WHERE o.placed_at >= (SELECT min(code_sent_at) FROM open_codes)
    ),
    first_use AS (
        SELECT DISTINCT ON (f.id) f.id AS survey_id, oc.placed_at, oc.order_number
        FROM open_codes AS f
        JOIN order_codes AS oc
          ON oc.ucode = f.ucode AND oc.placed_at >= f.code_sent_at
        ORDER BY f.id, oc.placed_at, oc.shopify_order_id
    )
    UPDATE feedback_survey AS s
    SET code_used_at = u.placed_at,
        code_order_name = left(u.order_number, 40),
        updated_at = now()
    FROM first_use AS u
    WHERE s.id = u.survey_id
    """
)


def mark_used(db: Session) -> int:
    """Record the codes that orders have used. Returns how many.

    Reads only what is already indexed - an order carrying the code, placed
    after the message that gave it - so it asks Shopify nothing.
    """
    return db.execute(_MARK_USED).rowcount or 0


# ── Thirty days ───────────────────────────────────────────────────────────────


def _due_for_removal(
    db: Session, now: datetime, skip: set[int], limit: int
) -> list[FeedbackSurvey]:
    query = select(FeedbackSurvey).where(
        FeedbackSurvey.code.is_not(None),
        FeedbackSurvey.code_expires_at <= now,
        FeedbackSurvey.code_used_at.is_(None),
        FeedbackSurvey.code_removed_at.is_(None),
    )
    if skip:
        query = query.where(FeedbackSurvey.id.not_in(skip))
    return list(
        db.scalars(query.order_by(FeedbackSurvey.code_expires_at, FeedbackSurvey.id).limit(limit))
    )


def _redeem_codes(
    client: ShopifyClient, discount_gid: str, batch: list[FeedbackSurvey]
) -> dict[int, dict | None]:
    """Each survey's code as Shopify has it now (``id`` and use count), or None
    if Shopify no longer has it."""
    found: dict[int, dict | None] = {}
    known = {row.code_gid: row for row in batch if row.code_gid}
    if known:
        data = client.execute(CODES_BY_ID, {"ids": list(known)})
        by_id = {
            str(node["id"]): node
            for node in ((data or {}).get("nodes") or [])
            if isinstance(node, dict) and node.get("id")
        }
        for gid, row in known.items():
            found[row.id] = by_id.get(gid)
    for row in batch:
        if row.id in found:
            continue
        # Its id was not known when it was issued: find it by its text.
        found[row.id] = _find_code(client, discount_gid, row.code)
    return found


def expire(
    db: Session,
    *,
    now: datetime | None = None,
    client: ShopifyClient | None = None,
    batch_size: int = REMOVE_BATCH,
    max_batches: int = REMOVE_BATCHES,
) -> int:
    """Take codes nobody used out of Shopify once their 30 days are up.
    Returns how many are now **confirmed gone** (a lookup no longer finds them).

    Shopify deletes in the background, so asking for a code's removal does not
    mark it removed: the next daily run looks it up, finds it gone, and only
    then records ``code_removed_at``. Asking again for a code already being
    deleted is harmless.

    **A used code is never removed**: the used-or-not pass runs first, and a
    code Shopify says has been used (its own count, which can be ahead of our
    index) is left for the pass to find. A code Shopify no longer has - or a
    whole discount deleted by hand - counts as removed.
    """
    now = now or utcnow()
    mark_used(db)
    cfg = feedback.get_settings(db)
    removed = 0
    skipped: set[int] = set()
    for _ in range(max_batches):
        batch = _due_for_removal(db, now, skipped, batch_size)
        if not batch:
            break
        if not cfg.discount_gid:
            # Codes with no discount to remove them from: nothing was issued.
            break
        client = client or _client(db)
        found = _redeem_codes(client, cfg.discount_gid, batch)
        gone, to_delete = [], []
        for row in batch:
            node = found.get(row.id)
            if node is None:
                gone.append(row)
            elif int(node.get("asyncUsageCount") or 0) > 0:
                skipped.add(row.id)
            else:
                to_delete.append((row, str(node["id"])))
        if to_delete:
            data = client.execute(
                CODES_REMOVE,
                {"discountId": cfg.discount_gid, "ids": [gid for _, gid in to_delete]},
            )
            errors = _errors((data or {}).get("discountCodeRedeemCodeBulkDelete"))
            if errors:
                raise _refuse_or_retry("removing expired codes", errors)
            # Asked for, not yet confirmed: tomorrow's lookup settles it.
            skipped.update(row.id for row, _ in to_delete)
        for row in gone:
            row.code_removed_at = now
            row.updated_at = now
        db.flush()
        removed += len(gone)
    return removed


def _client(db: Session) -> ShopifyClient:
    """The second app's client, able to manage discounts, or a permanent failure."""
    try:
        client = tags.tags_client(db)
        client.require_scope(connection.DISCOUNTS_SCOPE)
    except ShopifyMissingScope as exc:
        raise PermanentFailure(NO_PERMISSION) from exc
    except ShopifyNotConfigured as exc:
        raise PermanentFailure(NOT_CONNECTED) from exc
    return client


@register_handler(JobKind.INBOX_FEEDBACK_EXPIRE_CODES)
def _handle_expire(db: Session, payload: dict[str, Any]) -> None:
    if not feedback.enabled():
        return
    removed = expire(db)
    if removed:
        logger.info("%s feedback codes expired and were removed from Shopify", removed)
