"""Fetching orders from Shopify and indexing them.

A webhook tells us *which* order changed. It is never the source of what that
order is - that comes from asking Shopify, here. A webhook body can be a
replay, and Shopify's own payload can lag its API.

Every operation is an upsert keyed by Shopify's order id, so running twice is
indistinguishable from running once. That is required, not incidental: a lease
can expire and hand the same job to a second worker.
"""

from sqlalchemy.orm import Session

from app.config import settings
from app.core.signals import Anomaly, report
from app.models.orders import OrderIndex
from app.services.jobs import JobKind, PermanentFailure
from app.services.shopify.client import (
    ShopifyClient,
    ShopifyMissingScope,
    ShopifyNotConfigured,
)
from app.services.shopify.normalise import normalise_order, upsert_order_index
from app.services.shopify.queries import SINGLE_ORDER
from app.worker import register_handler

SYNC_ORDER = JobKind.SYNC_ORDER

#: Shopify failures that no amount of retrying will fix. A credential is
#: supplied by a person and a scope is granted by a person; waiting does
#: neither.
PERMANENT = (ShopifyNotConfigured, ShopifyMissingScope)


def build_client() -> ShopifyClient:
    """A client from configuration.

    Forwards the client id and secret as well as the static token. HBA's app is
    a Dev Dashboard app with no permanent token (ADR 0015), so a builder that
    only passed ``access_token`` would work in every test and fail against the
    real shop.
    """
    return ShopifyClient(
        shop_domain=settings.shopify_shop_domain,
        client_id=settings.shopify_client_id,
        client_secret=settings.shopify_client_secret,
        access_token=settings.shopify_access_token,
        api_version=settings.shopify_api_version,
        timeout_seconds=settings.shopify_timeout_seconds,
    )


def order_gid(order_id: str | int) -> str:
    """Shopify's GraphQL API addresses orders by global id, not legacy id."""
    text_id = str(order_id).strip()
    return text_id if text_id.startswith("gid://") else f"gid://shopify/Order/{text_id}"


def sync_one_order(
    db: Session, order_id: str, client: ShopifyClient | None = None
) -> OrderIndex | None:
    """Fetch one order and write it to the index.

    Returns ``None`` when Shopify has no such order. That is not an error - an
    order can be deleted between a webhook firing and the job running - and
    raising would retry forever against something that will never come back.
    """
    try:
        # build_client() raises when configuration is missing, so it belongs
        # inside the guard - otherwise an unconfigured platform retries every
        # order five times before saying what is wrong.
        client = client or build_client()
        data = client.execute(SINGLE_ORDER, {"id": order_gid(order_id)})
    except PERMANENT as exc:
        raise PermanentFailure(f"Cannot sync order {order_id}: {exc}") from exc

    node = data.get("order")
    if not node:
        # Not an error, and not nothing: this is the answer when someone asks
        # why an order they can see in Shopify is not on the dashboard.
        report(Anomaly.ORDER_NOT_FOUND, order_id=str(order_id))
        return None

    return upsert_order_index(db, normalise_order(node))


@register_handler(SYNC_ORDER)
def _handle_sync_order(db: Session, payload: dict) -> None:
    order_id = str(payload.get("order_id") or "").strip()
    if not order_id:
        raise PermanentFailure(
            f"{SYNC_ORDER} requires an order_id; got payload keys "
            f"{sorted(payload)!r}"
        )
    sync_one_order(db, order_id)
