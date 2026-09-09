"""Which parcels went to which model.

Rule W03, and it is a different question from every other question this
platform asks about an order. **Attribution** asks who *sold* it — a discount
code on the order. **Matching** asks who it was *sent to*.

The two are unrelated and must never be conflated: a model can sell a hundred
orders she never touched, and receive a parcel bought under nobody's code.

## Why the shipping phone, and why that is safe here

D11, from the owner, 10 September 2026:

> Her address is the one that we use to put inside the order details.

**HBA types it.** The shipping address on a parcel sent to a model is HBA's own
copy of her address, entered by whoever created the order in Shopify. So the
platform is the source and Shopify holds the copy, and matching compares a
stored phone against a phone HBA's own staff typed from that record.

W03's instruction not to match on the *customer* phone or email is the same
rule read from the other side: the customer on such an order is often Mena, and
the customer identity says who paid rather than who received.

## The restricted path

`BACKEND_CONTRACTS.md` asks for the recipient phone to live in a separate
restricted path, never in the commission index. That boundary is structural
here:

- `order_index` and `attributed_order` are untouched and still hold no personal
  data at all. `test_order_index.py` and `test_shopify_catalogue.py` both check
  it by reading columns rather than rows.
- The **raw phone is never stored.** What is stored is a normalised token — the
  digits, in one canonical form — on a row whose only purpose is matching.

A normalised Egyptian mobile is not anonymous and this file does not pretend it
is: eleven digits with a known prefix is guessable, and `BACKEND_CONTRACTS`
says so outright — *do not claim an unkeyed phone hash anonymizes predictable
phone numbers.* The protection is that the column is confined to this path and
this path is permission-gated, not that the value is unreadable.

## What is deliberately not decided here

Whether a matched parcel was a **gift** or a **personal purchase** (W04) is a
question about money, not about identity, and it is answered from the order's
original net rather than from anything on this page.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.services.jobs import JobKind, PermanentFailure, enqueue
from app.worker import register_handler
from app.models.affiliates import AccountKind, AffiliateProfile
from app.models.shipments import Classification, ModelShipment

#: The same rule the payout screens use, from `services/payouts.py`. Egyptian
#: mobiles are eleven digits starting 010, 011, 012 or 015.
_EGYPTIAN_MOBILE = re.compile(r"^01[0125]\d{8}$")


def normalise_phone(value: str | None) -> str | None:
    """One canonical form, or `None` when it is not a usable mobile.

    Tolerant about how it is written and strict about what it is. All of these
    are the same number and the first four are how people actually type it:

        +20 106 123 4567
        0020-106-123-4567
        (010) 6123 4567
        ٠١٠٦١٢٣٤٥٦٧          ← Arabic-Indic digits
        01061234567

    **`None` rather than a best guess.** A number that is not an Egyptian
    mobile — a landline, a foreign number, a typo — must not become a matching
    token, because two unusable numbers that normalise to the same wrong thing
    would match two different people to each other. Unmatched is a state this
    platform can show and act on; wrongly matched is not.
    """
    if value is None:
        return None

    text = str(value)

    # Arabic-Indic and Eastern Arabic-Indic digits, which a phone typed on an
    # Arabic keyboard arrives as. Translating them is not decoration: the
    # digits are the same number and refusing them would refuse a real model.
    translated = []
    for character in text:
        code = ord(character)
        if 0x0660 <= code <= 0x0669:  # ٠-٩
            translated.append(chr(code - 0x0660 + ord("0")))
        elif 0x06F0 <= code <= 0x06F9:  # ۰-۹
            translated.append(chr(code - 0x06F0 + ord("0")))
        else:
            translated.append(character)
    digits = re.sub(r"\D", "", "".join(translated))

    if not digits:
        return None

    # International prefixes, longest first. `0020…` and `20…` both mean Egypt,
    # and stripping the shorter one first would leave a stray zero.
    if digits.startswith("0020") and len(digits) == 14:
        digits = "0" + digits[4:]
    elif digits.startswith("20") and len(digits) == 12:
        digits = "0" + digits[2:]
    elif len(digits) == 10 and digits.startswith("1"):
        # A number typed without its leading zero. Common, unambiguous for
        # Egyptian mobiles, and the alternative is refusing a real one.
        digits = "0" + digits

    return digits if _EGYPTIAN_MOBILE.match(digits) else None


#: Why a shipment could not be attached to one model. Strings because they
#: cross the wire and each is a sentence the interface turns into a reason.
NO_PHONE = "no_phone"
UNUSABLE_PHONE = "unusable_phone"
NO_MATCH = "no_match"
AMBIGUOUS = "ambiguous"


def match_recipient(db: Session, phone: str | None) -> dict:
    """Which model a shipping phone belongs to.

    Returns the model and how it was decided, or `None` with a reason. Never
    raises: an unmatched parcel is an ordinary state — a customer order, a
    friend of the business, a number nobody recorded — and the great majority
    of the shop's orders are exactly that.

    **Ambiguity is refused, not resolved.** Two models sharing a phone is a
    data problem somebody has to look at; picking one would attach a parcel to
    the wrong woman's wardrobe and nothing downstream would question it.
    W03 asks for it to be reported, and this is what reports it.

    **House accounts are excluded.** Nobody signs in as one and nothing is sent
    to one; a house code's phone matching a parcel would be a coincidence, not
    a delivery.
    """
    if not phone or not str(phone).strip():
        return {"affiliate_id": None, "reason": NO_PHONE, "token": None}

    token = normalise_phone(phone)
    if token is None:
        return {"affiliate_id": None, "reason": UNUSABLE_PHONE, "token": None}

    candidates = [
        row
        for row in db.scalars(
            select(AffiliateProfile).where(
                AffiliateProfile.account_kind != AccountKind.HOUSE
            )
        )
        # Compared normalised on both sides. A model who typed her phone with a
        # +20 and an order carrying it without one are the same person, and
        # comparing the stored strings would say otherwise.
        if normalise_phone(row.shipping_phone or row.phone) == token
    ]

    if not candidates:
        return {"affiliate_id": None, "reason": NO_MATCH, "token": token}

    if len(candidates) > 1:
        return {
            "affiliate_id": None,
            "reason": AMBIGUOUS,
            "token": token,
            "candidates": sorted(row.id for row in candidates),
        }

    return {"affiliate_id": candidates[0].id, "reason": None, "token": token}


# ── Recording what was decided ───────────────────────────────────────────────


def classify(original_net_piastres: int | None) -> str:
    """Gift, purchase, or unknown. W04.

    **From the order's original net, never its current one.** Shopify zeroes
    the current totals when an order is cancelled, so reading those would turn
    every cancelled purchase into a gift — a parcel she paid for, recorded as
    one HBA gave her, in her wardrobe, permanently.

    `None` stays `unknown` and is deliberately **not** treated as a gift. W04:
    *unknown original value remains unknown.* This decides whether something is
    hers, and a guess here is a guess about somebody's property.
    """
    if original_net_piastres is None:
        return Classification.UNKNOWN
    return Classification.GIFT if original_net_piastres <= 0 else Classification.PURCHASE


def original_net_of(order) -> int | None:
    """What the customer originally paid for the goods, in piastres.

    Merchandise only: shipping and tax are not the thing that was sent, and a
    gift with paid delivery is still a gift. The same shape as the commission
    base (§9.3), read from the *original* columns rather than the current ones.

    `None` where the order carries no original subtotal at all — an order first
    seen after a cancellation, which `F04` warns can lack an authoritative
    basis. Reported as unknown rather than inferred.
    """
    original = getattr(order, "original_subtotal_piastres", None)
    if original is None:
        return None
    return max(0, int(original))


def record_shipment(db: Session, order, *, phone: str | None) -> "ModelShipment":
    """Attach one order to a model, or record why it could not be.

    Idempotent by order: a webhook, a sweep and a backfill all reach this, and
    a second run must not create a second row. One parcel goes to one person.

    **A confirmed match is not re-decided.** W03 asks that verified historical
    links survive a phone change, and this is where that is kept: once a row
    names a model, a later pass leaves it alone. She may move, change her
    number, or leave the programme — none of that changes which parcel arrived
    at her door in March.

    An *unmatched* row is re-decided every time, because that is the state the
    business is trying to clear: a model whose address is recorded today should
    pick up the parcels that could not be attached yesterday, which is exactly
    W05's *a model joining the platform later can acquire links to earlier
    orders.*
    """
    existing = db.scalar(
        select(ModelShipment).where(
            ModelShipment.shopify_order_id == order.shopify_order_id
        )
    )

    if existing is not None and existing.affiliate_id is not None:
        return existing

    outcome = match_recipient(db, phone)
    net = original_net_of(order)

    values = {
        "affiliate_id": outcome["affiliate_id"],
        "recipient_token": outcome["token"],
        "match_reason": outcome["reason"],
        "matched_at": utcnow() if outcome["affiliate_id"] else None,
        "classification": classify(net),
        "original_net_piastres": net,
    }

    if existing is None:
        existing = ModelShipment(
            shopify_order_id=order.shopify_order_id, **values
        )
        db.add(existing)
    else:
        for key, value in values.items():
            setattr(existing, key, value)
        existing.updated_at = utcnow()

    db.flush()
    return existing


def unmatched(db: Session, limit: int = 200) -> list[dict]:
    """Parcels the platform looked at and could not attach.

    W12's bounded staff path. Deliberately a list of *reasons* rather than a
    queue of work: most of these are ordinary customer orders and always will
    be, and presenting them as a backlog would invite somebody to clear a
    thousand rows that were never HBA's parcels.
    """
    from app.models.shipments import ModelShipment

    rows = db.scalars(
        select(ModelShipment)
        .where(ModelShipment.affiliate_id.is_(None))
        .where(ModelShipment.match_reason.in_({AMBIGUOUS, NO_MATCH}))
        .order_by(ModelShipment.id.desc())
        .limit(limit)
    )
    return [
        {
            "shopify_order_id": row.shopify_order_id,
            "reason": row.match_reason,
            "classification": row.classification,
        }
        for row in rows
    ]


# ── Walking the history (W05) ────────────────────────────────────────────────

#: Orders per Shopify page.
SCAN_PAGE_SIZE = 100

#: Pages per job run. **Bounded on purpose.** A whole shop's history in one
#: handler would hold a lease for minutes and lose everything if it died at the
#: end; this does a slice, commits it, and hands the cursor to the next run.
PAGES_PER_RUN = 5


def scan_recipients(
    db,
    client,
    *,
    since: str,
    cursor: str | None = None,
    page_size: int = SCAN_PAGE_SIZE,
    pages_per_run: int = PAGES_PER_RUN,
) -> dict:
    """Match a slice of the shop's history, and say where to resume.

    **Resumable, because the alternative is all-or-nothing.** W05 asks for a
    backfill from January; that is thousands of orders, and a walk that must
    finish in one go is a walk that never finishes. Each run does a few pages,
    commits them, and returns the cursor the next run starts from.

    Only orders already in `order_index` are matched. An order the platform has
    never indexed is not one it can attach a parcel to, and quietly creating a
    stub for it here would put a row in the wardrobe path that commission
    knows nothing about.
    """
    from app.models.orders import OrderIndex
    from app.services.shopify.queries import ORDERS_RECIPIENT_PAGE

    matched = 0
    seen = 0
    unknown_order = 0
    pages = 0

    while pages < pages_per_run:
        pages += 1
        payload = client.execute(
            ORDERS_RECIPIENT_PAGE,
            {
                "first": page_size,
                "after": cursor,
                "query": f"created_at:>={since}",
            },
        )
        block = ((payload or {}).get("orders")) or {}

        for node in block.get("nodes") or []:
            seen += 1
            order_id = str(node.get("legacyResourceId") or "").strip()
            if not order_id:
                continue
            order = db.get(OrderIndex, order_id)
            if order is None:
                unknown_order += 1
                continue
            phone = ((node.get("shippingAddress") or {}) or {}).get("phone")
            shipment = record_shipment(db, order, phone=phone)
            if shipment.affiliate_id is not None:
                matched += 1

        db.commit()

        info = block.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            return {
                "seen": seen,
                "matched": matched,
                "unknown_order": unknown_order,
                "pages": pages,
                "cursor": None,
                "done": True,
            }
        next_cursor = info.get("endCursor")
        if not next_cursor or next_cursor == cursor:
            # A cursor that does not advance would loop. Stopping and saying
            # so beats spinning until the rate limiter notices.
            return {
                "seen": seen,
                "matched": matched,
                "unknown_order": unknown_order,
                "pages": pages,
                "cursor": None,
                "done": True,
            }
        cursor = next_cursor

    return {
        "seen": seen,
        "matched": matched,
        "unknown_order": unknown_order,
        "pages": pages,
        "cursor": cursor,
        "done": False,
    }


@register_handler(JobKind.SCAN_RECIPIENTS)
def _handle_scan_recipients(db, payload: dict) -> None:
    """One slice of the walk, then hand the cursor on.

    Re-enqueues itself while there is more, which is what makes a backfill of
    thousands of orders survivable: each run is short, each commit is kept, and
    a crash costs one slice rather than the whole history.

    The follow-on job carries the cursor in its dedupe key. Without that, a
    second slice would collide with the first under one key and silently never
    be queued - a backfill that stops after five pages and reports success.
    """
    from app.services.shopify.sync import PERMANENT, build_client

    since = str(payload.get("since") or "2026-01-01")
    cursor = payload.get("cursor")

    try:
        client = build_client()
        client.require_scope("read_orders")
        result = scan_recipients(db, client, since=since, cursor=cursor)
    except PERMANENT as exc:
        raise PermanentFailure(str(exc)) from exc

    if result["done"]:
        return

    enqueue(
        db,
        JobKind.SCAN_RECIPIENTS,
        {"since": since, "cursor": result["cursor"]},
        dedupe_key=f"{JobKind.SCAN_RECIPIENTS}:{result['cursor']}",
    )
