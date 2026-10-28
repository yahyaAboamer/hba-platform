"""Inbound webhooks.

The handler does as little as possible: verify, record, enqueue, return 200.
Shopify retries any webhook that does not answer promptly, so slow work here
turns into duplicate deliveries.

This is the only public, unauthenticated endpoint on the service. Everything it
does *before* verifying the signature is attack surface, so it does nothing
before verifying except check the size.
"""

import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.core.signals import Anomaly, report
from app.db import get_session
from app.modules.inbox.models import MetaWebhookEvent
from app.modules.inbox.services import connection as inbox_connection
from app.modules.inbox.services.meta import verify_signature
from app.shared.services.jobs import JobKind, enqueue, record_event
from app.shared.services.shopify.webhooks import (
    MAX_BODY_BYTES,
    ORDER_TOPICS,
    delivery_id,
    order_id_from,
    verify_shopify_hmac,
)

router = APIRouter(prefix="/api/webhooks")

SYNC_ORDER = JobKind.SYNC_ORDER


async def _read_capped(request: Request, limit: int = MAX_BODY_BYTES) -> bytes:
    """The body, refused the moment it passes the cap.

    `request.body()` reads everything before anything can be measured, and a
    chunked request declares no Content-Length for the check above to see - so
    an unauthenticated caller could make this hold any amount in memory
    (security audit, October 2026).
    """
    received = bytearray()
    async for chunk in request.stream():
        received += chunk
        if len(received) > limit:
            raise HTTPException(413, "Body too large")
    return bytes(received)


# ── Meta (WhatsApp) ───────────────────────────────────────────────────────────

#: Meta batches many updates into one callback, and says a callback can reach
#: 3 MB. Larger than that is not Meta.
META_MAX_BODY_BYTES = 3_000_000

#: The longest challenge echoed back. Meta's is a short number.
MAX_CHALLENGE = 200


@router.get("/meta", include_in_schema=False)
def meta_verify(request: Request, db: Session = Depends(get_session)) -> PlainTextResponse:
    """Meta's one-time check when the callback address is set.

    It sends the check word saved in Settings and a challenge; answering with
    the challenge proves this server holds the same word. A wrong word, or no
    WhatsApp connection at all, is refused the same way.
    """
    query = request.query_params
    connection = inbox_connection.whatsapp(db)
    offered = query.get("hub.verify_token") or ""
    challenge = query.get("hub.challenge") or ""
    if (
        connection is None
        or query.get("hub.mode") != "subscribe"
        or not offered
        or not hmac.compare_digest(offered.encode(), connection.verify_token.encode())
        or not challenge
        or len(challenge) > MAX_CHALLENGE
    ):
        report(
            Anomaly.WEBHOOK_REJECTED,
            topic="meta:verify",
            secret_configured=connection is not None,
            body_bytes=0,
        )
        raise HTTPException(403, "Not verified")
    return PlainTextResponse(challenge)


@router.post("/meta", include_in_schema=False)
async def meta_webhook(request: Request, db: Session = Depends(get_session)) -> dict:
    """A callback from Meta: verify, write it down, queue the work, answer.

    **Stored before anything acts on it** (ADR 0059, point 13). A customer's
    message exists nowhere else until it has been applied, so the callback
    is kept whole, by the SHA-256 of the exact bytes Meta sent. A callback
    Meta repeats is acknowledged and neither stored nor queued again.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > META_MAX_BODY_BYTES:
        raise HTTPException(413, "Body too large")
    raw_body = await _read_capped(request, META_MAX_BODY_BYTES)

    connection = inbox_connection.whatsapp(db)
    if connection is None or not verify_signature(
        raw_body, request.headers.get("X-Hub-Signature-256"), connection.app_secret
    ):
        # Nothing is recorded for an unverified request, and nothing from
        # its body is reported: it is unverified input.
        report(
            Anomaly.WEBHOOK_REJECTED,
            topic="meta",
            secret_configured=connection is not None,
            body_bytes=len(raw_body),
        )
        raise HTTPException(401, "Invalid signature")

    try:
        payload = json.loads(raw_body)
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        # Signed by Meta but not a callback we can read. Acknowledge, so Meta
        # does not retry it for days, and say so.
        report(Anomaly.WEBHOOK_UNUSABLE, topic="meta", reason="body is not a JSON object")
        return {"status": "ignored"}

    event_id = db.execute(
        insert(MetaWebhookEvent)
        .values(digest=hashlib.sha256(raw_body).hexdigest(), payload=payload)
        .on_conflict_do_nothing(index_elements=["digest"])
        .returning(MetaWebhookEvent.id)
    ).scalar()
    if event_id is None:
        db.commit()
        return {"status": "duplicate"}

    enqueue(
        db,
        JobKind.INBOX_APPLY_EVENT,
        {"event_id": event_id},
        dedupe_key=f"{JobKind.INBOX_APPLY_EVENT}:{event_id}",
    )
    db.commit()
    return {"status": "accepted"}


@router.post("/shopify", include_in_schema=False)
async def shopify_webhook(request: Request, db: Session = Depends(get_session)) -> dict:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(413, "Body too large")

    raw_body = await _read_capped(request)

    # Attacker-controlled until the signature verifies, and it is reported on
    # rejection - so it is capped before it can be used to bloat the logs.
    topic = request.headers.get("X-Shopify-Topic", "")[:80]

    if not verify_shopify_hmac(
        raw_body,
        request.headers.get("X-Shopify-Hmac-Sha256"),
        settings.shopify_webhook_secret,
    ):
        # Nothing is recorded for an unverified request: integration_event is
        # append-only and cannot be pruned, so anyone able to write to it could
        # fill the database permanently.
        #
        # Nothing from the body is reported either - it is unverified input.
        report(
            Anomaly.WEBHOOK_REJECTED,
            topic=topic,
            secret_configured=bool(settings.shopify_webhook_secret),
            body_bytes=len(raw_body),
        )
        raise HTTPException(401, "Invalid signature")

    try:
        payload = json.loads(raw_body)
    except ValueError:
        # Signed by Shopify but not parseable. Record that it arrived - the
        # receipt is the evidence - and do nothing further with it.
        payload = None

    order_id = order_id_from(topic, payload)

    _event, newly_recorded = record_event(
        db,
        source="shopify",
        external_id=delivery_id(raw_body, request.headers.get("X-Shopify-Webhook-Id")),
        topic=topic,
        payload=payload if isinstance(payload, dict) else None,
        entity_id=order_id,
    )

    if not newly_recorded:
        # A redelivery. Acknowledge so Shopify stops retrying, but do not queue
        # the work again.
        db.commit()
        return {"status": "duplicate"}

    if topic in ORDER_TOPICS:
        if order_id:
            # Shopify sends create, updated and paid for one order within
            # seconds. Each is its own receipt; all three are one piece of work.
            enqueue(
                db,
                SYNC_ORDER,
                {"order_id": order_id, "reason": topic},
                dedupe_key=f"{SYNC_ORDER}:{order_id}",
            )
        else:
            # An order topic whose payload does not name an order means the
            # shape is not what we assume - a Shopify change, or a topic
            # subscribed to by mistake.
            report(
                Anomaly.WEBHOOK_UNUSABLE,
                topic=topic,
                reason="no order id in payload",
            )

    db.commit()
    return {"status": "accepted"}
