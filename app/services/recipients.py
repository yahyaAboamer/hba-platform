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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.core.signals import Anomaly, report
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
    #
    # `+20 010…` is the country code *and* the leading zero - wrong, and how
    # about forty of the shop's orders are written (ADR 0060). It is still the
    # number it plainly is, so the zero is kept once rather than twice.
    if digits.startswith("00200") and len(digits) == 15:
        digits = "0" + digits[5:]
    elif digits.startswith("200") and len(digits) == 13:
        digits = "0" + digits[3:]
    elif digits.startswith("0020") and len(digits) == 14:
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
#: Staff looked at an unmatched gift and said it went to somebody who is not a
#: model (ADR 0060). Still unmatched; it only leaves the gift list.
NOT_A_MODEL = "not_a_model"

#: On a **matched** row: staff said whose it was (ADR 0060), rather than the
#: phone on her profile. The number on it is one of hers from then on.
ASSIGNED = "assigned"


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

    roster = list(
        db.scalars(
            select(AffiliateProfile)
            .where(AffiliateProfile.account_kind != AccountKind.HOUSE)
            # **Archived models take no new parcels.** Somebody who left is
            # not receiving HBA's gifts, and her phone lingering on the roster
            # would otherwise turn a parcel to whoever has that number now
            # into an ambiguity nobody can clear. Parcels already matched to
            # her stay hers - that is `record_shipment`'s rule, not this one.
            .where(AffiliateProfile.archived_at.is_(None))
        )
    )
    # A number staff confirmed is one of hers (ADR 0060): a gift they assigned
    # to her is the record of it, so the next parcel to it needs nobody.
    remembered = set(
        db.scalars(
            select(ModelShipment.affiliate_id)
            .where(ModelShipment.match_reason == ASSIGNED)
            .where(ModelShipment.recipient_token == token)
        )
    )
    candidates = [
        row
        for row in roster
        # Compared normalised on both sides. A model who typed her phone with a
        # +20 and an order carrying it without one are the same person, and
        # comparing the stored strings would say otherwise.
        if normalise_phone(row.shipping_phone or row.phone) == token
        or row.id in remembered
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

    # Staff said this went to somebody who is not a model. A rescan keeps that
    # answer, unless the number now does belong to one (ADR 0060).
    if (
        existing is not None
        and existing.match_reason == NOT_A_MODEL
        and outcome["affiliate_id"] is None
    ):
        outcome = {**outcome, "reason": NOT_A_MODEL}

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


def rematch_for(db: Session, affiliate: AffiliateProfile) -> int:
    """Give a model the parcels that were waiting for her phone. Returns how many.

    W05: *a model joining the platform later can acquire links to earlier
    orders.* The rule was written and nothing ever ran it - Mazen was added on
    26 September and his six gift parcels, stored unmatched on 10 September
    with his number on them, stayed unmatched.

    **No Shopify call.** An unmatched parcel keeps the normalised phone it was
    sent to (`recipient_token`), so a new or changed phone is compared against
    the parcels already on file. Called when a model is added and whenever her
    phone changes.

    Decided through `match_recipient`, so the same rules hold: a phone two
    models share is recorded as ambiguous and attaches to neither, and an
    archived model takes nothing. Only unmatched parcels are touched - a
    confirmed match is never re-decided.
    """
    token = normalise_phone(affiliate.shipping_phone or affiliate.phone)
    if token is None:
        return 0

    rows = list(
        db.scalars(
            select(ModelShipment)
            .where(ModelShipment.affiliate_id.is_(None))
            .where(ModelShipment.recipient_token == token)
        )
    )
    if not rows:
        return 0

    outcome = match_recipient(db, token)
    now = utcnow()
    for row in rows:
        if outcome["affiliate_id"] is None and row.match_reason == NOT_A_MODEL:
            continue
        row.affiliate_id = outcome["affiliate_id"]
        row.match_reason = outcome["reason"]
        row.matched_at = now if outcome["affiliate_id"] else None
        row.updated_at = now
        if outcome["affiliate_id"] is not None:
            enqueue(
                db,
                JobKind.SYNC_LINE_ITEMS,
                {"order_id": row.shopify_order_id},
                dedupe_key=f"{JobKind.SYNC_LINE_ITEMS}:{row.shopify_order_id}",
            )
    db.flush()
    return len(rows) if outcome["affiliate_id"] is not None else 0


def unmatched(db: Session, limit: int = 200) -> dict:
    """Parcels that need a person, and a count of the ones that do not.

    W12's bounded staff path.

    ## Why this shows only ambiguities

    The first version listed `no_match` too, and on the real shop that is
    **every customer order there has ever been** - fourteen thousand rows on
    staging, burying the thirty-six that actually needed somebody. The design
    note written at the time said a backlog of rows that were never HBA's
    parcels is worse than no list; the query did not match the note.

    A parcel that matches no model is not a problem. It is a customer, which is
    what almost every order is. The only genuinely stuck state is **two models
    sharing one phone**, because then a real parcel to a real model cannot be
    attached to either.

    So: ambiguities are listed with the models involved, and everything else is
    a number in a summary - visible, countable, and not a to-do list.
    """
    counts = {
        reason: count
        for reason, count in db.execute(
            select(ModelShipment.match_reason, func.count())
            .where(ModelShipment.affiliate_id.is_(None))
            .group_by(ModelShipment.match_reason)
        )
    }

    rows = list(
        db.scalars(
            select(ModelShipment)
            .where(ModelShipment.affiliate_id.is_(None))
            .where(ModelShipment.match_reason == AMBIGUOUS)
            .order_by(ModelShipment.id.desc())
            .limit(limit)
        )
    )

    # Who is colliding, by token. One pass over the roster rather than one
    # query per parcel - thirty-six parcels usually share two or three numbers.
    models = list(
        db.scalars(
            select(AffiliateProfile).where(
                AffiliateProfile.account_kind != AccountKind.HOUSE
            )
        )
    )
    by_token: dict[str, list[str]] = {}
    for model in models:
        token = normalise_phone(model.shipping_phone or model.phone)
        if token:
            by_token.setdefault(token, []).append(model.name)

    return {
        "parcels": [
            {
                "shopify_order_id": row.shopify_order_id,
                "reason": row.match_reason,
                "classification": row.classification,
                # A model's own number, not a customer's - that is what makes
                # it safe to show here and what makes it useful.
                "phone": row.recipient_token,
                "models": sorted(by_token.get(row.recipient_token or "", [])),
            }
            for row in rows
        ],
        "summary": {
            "needs_you": counts.get(AMBIGUOUS, 0),
            # Not a backlog. Almost every order in the shop is a customer's.
            "customers": counts.get(NO_MATCH, 0),
            "unusable_phone": counts.get(UNUSABLE_PHONE, 0),
            "no_phone": counts.get(NO_PHONE, 0),
            "matched": db.scalar(
                select(func.count())
                .select_from(ModelShipment)
                .where(ModelShipment.affiliate_id.is_not(None))
            )
            or 0,
        },
    }


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
    field: str = "created_at",
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
                # `created_at` for the history walk; the sweep passes
                # `updated_at`, the window it just re-indexed.
                "query": f"{field}:>={since}",
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
                # **Only for matched parcels.** Reading every line of every
                # order in the shop to build twenty wardrobes is the wrong
                # trade, and the great majority of orders are customers.
                #
                # Its own job rather than a call here: the scan should not slow
                # to Shopify's pace per parcel, and a line-item read that fails
                # must not cost the page of matches around it.
                enqueue(
                    db,
                    JobKind.SYNC_LINE_ITEMS,
                    {"order_id": order.shopify_order_id},
                    dedupe_key=(
                        f"{JobKind.SYNC_LINE_ITEMS}:{order.shopify_order_id}"
                    ),
                )

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
    # `created_at` walks history; the sweep queues `updated_at`, the window it
    # has just re-indexed.
    field = "updated_at" if payload.get("field") == "updated_at" else "created_at"

    try:
        client = build_client()
        client.require_scope("read_orders")
        result = scan_recipients(db, client, since=since, cursor=cursor, field=field)
    except PERMANENT as exc:
        raise PermanentFailure(str(exc)) from exc

    if result["done"]:
        return

    enqueue(
        db,
        JobKind.SCAN_RECIPIENTS,
        {"since": since, "cursor": result["cursor"], "field": field},
        dedupe_key=f"{JobKind.SCAN_RECIPIENTS}:{result['cursor']}",
    )


def match_one_order(db, client, order) -> "ModelShipment | None":
    """Check one order against the roster, and read it if it is a model's.

    **The live half of W05.** The bulk scan walks history; this is the parcel
    that shipped this morning, arriving through the same webhook that already
    indexes the order.

    Two Shopify calls at most, and the second only when the first one matched:
    the great majority of the shop's orders are customers, and reading every
    line of every one to build twenty wardrobes is the wrong trade.
    """
    from app.services.shopify.queries import ORDER_RECIPIENT

    gid = order.shopify_order_gid or f"gid://shopify/Order/{order.shopify_order_id}"
    payload = client.execute(ORDER_RECIPIENT, {"id": gid})
    node = ((payload or {}).get("order")) or {}
    phone = ((node.get("shippingAddress") or {}) or {}).get("phone")

    shipment = record_shipment(db, order, phone=phone)

    if shipment.affiliate_id is not None:
        enqueue(
            db,
            JobKind.SYNC_LINE_ITEMS,
            {"order_id": order.shopify_order_id},
            dedupe_key=f"{JobKind.SYNC_LINE_ITEMS}:{order.shopify_order_id}",
        )

    return shipment


@register_handler(JobKind.MATCH_ORDER)
def _handle_match_order(db, payload: dict) -> None:
    """One order, matched. Queued after the order itself is indexed."""
    from app.models.orders import OrderIndex
    from app.services.shopify.sync import PERMANENT, build_client

    order_id = str(payload.get("order_id") or "").strip()
    if not order_id:
        raise PermanentFailure(
            f"{JobKind.MATCH_ORDER} requires an order_id; got {sorted(payload)!r}"
        )

    order = db.get(OrderIndex, order_id)
    if order is None:
        # Indexed and then deleted, or the jobs ran out of order. Not an error
        # worth retrying forever against something that may never come back.
        return

    try:
        client = build_client()
        client.require_scope("read_orders")
        match_one_order(db, client, order)
    except PERMANENT as exc:
        raise PermanentFailure(str(exc)) from exc

    db.commit()


@register_handler(JobKind.SYNC_LINE_ITEMS)
def _handle_sync_line_items(db, payload: dict) -> None:
    """Read what was inside one parcel.

    Queued only for an order already matched to a model. A wardrobe without
    this is a list of parcels with nothing in them, which is what every
    wardrobe was until this existed.
    """
    from app.services.shopify.catalogue import sync_order_line_items
    from app.services.shopify.sync import PERMANENT, build_client

    order_id = str(payload.get("order_id") or "").strip()
    if not order_id:
        raise PermanentFailure(
            f"{JobKind.SYNC_LINE_ITEMS} requires an order_id; got {sorted(payload)!r}"
        )

    try:
        client = build_client()
        result = sync_order_line_items(
            db, client, f"gid://shopify/Order/{order_id}"
        )
    except PERMANENT as exc:
        raise PermanentFailure(str(exc)) from exc

    if result.get("truncated"):
        # An order with more than a hundred lines is not something HBA ships,
        # and silently keeping the first hundred would make a wardrobe wrong
        # in a way nothing could see.
        report(Anomaly.LINE_ITEMS_TRUNCATED, order_id=order_id)

    db.commit()


#: How many orders one sweep queues. Each is one Shopify read, paced by the
#: client's throttle handling; 500 an hour clears 7,000 in under a day without
#: spending the shop's whole rate limit on it.
FILL_BATCH = 500


def orders_missing_line_items(db, *, limit: int = FILL_BATCH) -> list[str]:
    """Orders whose products a screen needs and were never read, newest first.

    Two kinds of order need their products: one **attributed** to a model (her
    orders and best sellers) and one **matched as her parcel** (her wardrobe).
    The second was missing until 28 September, so a parcel matched by anything
    other than a live match was a wardrobe entry with nothing in it.

    *Never read* is no line at all, or lines read before a later question was
    asked: options (`selected_options IS NULL`, ADR 0050), whether the line
    was an exchange item (`after_delivery IS NULL`, ADR 0051), or whether an
    order edit removed it (`ordered_quantity IS NULL`, #21585). A deleted
    variant is stored as `[]`, so it is not asked about again. Newest first,
    because the month a model is looking at is the one that should fill first.

    An order Shopify no longer has returns no lines and is asked about again
    next hour; that is one read an hour for a thing that should not exist, and
    bounded by the batch.
    """
    from sqlalchemy import exists, or_

    from app.models.attributed_orders import AttributedOrder
    from app.models.catalogue import OrderLineItem
    from app.models.orders import OrderIndex

    wanted = or_(
        exists().where(AttributedOrder.shopify_order_id == OrderIndex.shopify_order_id),
        exists().where(
            (ModelShipment.shopify_order_id == OrderIndex.shopify_order_id)
            & ModelShipment.affiliate_id.is_not(None)
        ),
    )
    no_lines = ~exists().where(
        OrderLineItem.shopify_order_id == OrderIndex.shopify_order_id
    )
    unread = exists().where(
        (OrderLineItem.shopify_order_id == OrderIndex.shopify_order_id)
        & (
            OrderLineItem.selected_options.is_(None)
            | OrderLineItem.after_delivery.is_(None)
            | OrderLineItem.ordered_quantity.is_(None)
        )
    )
    return list(
        db.scalars(
            select(OrderIndex.shopify_order_id)
            .where(wanted)
            .where(no_lines | unread)
            .order_by(OrderIndex.placed_at.desc())
            .limit(limit)
        )
    )


@register_handler(JobKind.FILL_LINE_ITEMS)
def _handle_fill_line_items(db, payload: dict) -> None:
    """Queue the product read for a batch of orders that are missing it.

    Only queues; the reads are `SYNC_LINE_ITEMS` jobs, one per order, deduped
    on the same key every other caller uses - so an order already queued by
    the webhook or by attribution is not read twice.
    """
    limit = int(payload.get("limit") or FILL_BATCH)
    for order_id in orders_missing_line_items(db, limit=limit):
        enqueue(
            db,
            JobKind.SYNC_LINE_ITEMS,
            {"order_id": order_id},
            dedupe_key=f"{JobKind.SYNC_LINE_ITEMS}:{order_id}",
        )
