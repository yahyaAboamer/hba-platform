"""Inbound webhooks.

The handler does as little as possible: verify, record, enqueue, return 200.
Shopify retries any webhook that does not answer promptly, so slow work here
turns into duplicate deliveries.

This is the only public, unauthenticated endpoint on the service. Everything it
does *before* verifying the signature is attack surface, so it does nothing
before verifying except check the size.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.core.signals import Anomaly, report
from app.db import get_session
from app.services.jobs import JobKind, enqueue, record_event
from app.services.shopify.webhooks import (
    MAX_BODY_BYTES,
    ORDER_TOPICS,
    delivery_id,
    order_id_from,
    verify_shopify_hmac,
)

router = APIRouter(prefix="/api/webhooks")

SYNC_ORDER = JobKind.SYNC_ORDER


@router.post("/shopify", include_in_schema=False)
async def shopify_webhook(request: Request, db: Session = Depends(get_session)) -> dict:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(413, "Body too large")

    raw_body = await request.body()
    if len(raw_body) > MAX_BODY_BYTES:
        raise HTTPException(413, "Body too large")

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
