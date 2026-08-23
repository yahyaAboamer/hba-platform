"""Shopify webhook signature verification and payload reading.

Shopify signs the raw request body with the app secret and sends the result
base64-encoded in ``X-Shopify-Hmac-Sha256``. The signature covers the exact
bytes sent, so verification must use the **raw body**: re-serialising parsed
JSON changes whitespace and key order, and the signature will not match.
"""

import base64
import binascii
import hashlib
import hmac
from typing import Any

#: Topics worth acting on. Anything else is acknowledged and recorded, but
#: generates no work. Kept deliberately short: orders/updated fires for most
#: changes, including payment, so subscribing to more topics would mostly
#: produce deliveries that deduplicate into the same sync.
ORDER_TOPICS = frozenset(
    {
        "orders/create",
        "orders/updated",
        "orders/cancelled",
        "orders/fulfilled",
        "orders/partially_fulfilled",
        "refunds/create",
    }
)

#: A Shopify order payload is a few kilobytes. This is the only unauthenticated
#: endpoint on the service, so a body anywhere near a megabyte is not Shopify -
#: and reading it into memory on a small dyno is a free denial of service.
MAX_BODY_BYTES = 1_000_000

#: integration_event.external_id and .entity_id are bounded. A value longer
#: than the column is not a value we can store, and letting it reach the insert
#: turns a strange payload into a 500 - so it is caught here instead.
MAX_DELIVERY_ID = 200
MAX_ENTITY_ID = 64


def verify_shopify_hmac(raw_body: bytes, header_value: str | None, secret: str) -> bool:
    """Constant-time signature check. Fails closed on anything unexpected.

    An unset secret returns False rather than skipping verification: a missing
    credential must never turn into "accept everything".
    """
    if not secret or not header_value:
        return False
    try:
        provided = base64.b64decode(header_value, validate=True)
    except (binascii.Error, ValueError, TypeError):
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    return hmac.compare_digest(provided, expected)


def delivery_id(raw_body: bytes, header_value: str | None) -> str:
    """The idempotency key for a delivery.

    Shopify's own ``X-Shopify-Webhook-Id`` when present. Absent it - or longer
    than the column can hold - a hash of the body, so two identical deliveries
    still deduplicate, which is the safe direction to fail in.

    Truncating an over-long id would be worse than replacing it: two different
    ids could truncate to the same value, and the second delivery would be
    silently discarded as a duplicate.
    """
    if header_value and len(header_value) <= MAX_DELIVERY_ID:
        return header_value
    return hashlib.sha256(raw_body).hexdigest()


def order_id_from(topic: str, payload: Any) -> str | None:
    """Which order a payload is about, or None if it does not say.

    **A refund payload's ``id`` is the refund's id, not the order's** - the
    order is in ``order_id``. Reading ``id`` for a refund would queue a sync
    against a number that is not an order id, which either finds nothing or
    finds an unrelated order and attributes a stranger's money to the wrong
    affiliate.
    """
    if not isinstance(payload, dict):
        return None
    field = "order_id" if topic.startswith("refunds/") else "id"
    value = str(payload.get(field) or "").strip()
    if not value or len(value) > MAX_ENTITY_ID:
        # A Shopify order id is a short number. Anything longer is not one, and
        # reporting it as unusable is more useful than a 500 from the insert.
        return None
    return value
