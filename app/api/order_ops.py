"""Operations: what is waiting in Shopify, Bosta and E-stebdal (ADR 0057).

Every route here is behind ``order_ops.view``, held by the operations manager
and the admin and by nobody else. The guard is on the router itself rather
than repeated per route, so a route added later cannot be added without it.

Every route reads only the platform's own tables, filled every 5 minutes by
``app.services.order_ops.polling``; nothing here calls Shopify, Bosta or
E-stebdal while a page waits. Each response carries ``freshness`` for the
source it is about, so a number is never shown without the time it was read,
and a source that could not be read never shows as 0.

The tabs' routes arrive with their tabs: Shopify now, E-stebdal and Bosta next.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.permissions import Permission
from app.db import get_session
from app.services.order_ops import shopify
from app.services.order_ops.freshness import State, describe

#: The one guard, kept by name so a test can find it on every route.
GUARD = require_permission(Permission.ORDER_OPS_VIEW)

router = APIRouter(prefix="/api/order-ops", tags=["order-ops"], dependencies=[Depends(GUARD)])


def freshness(db: Session, source: str) -> dict:
    """The ``freshness`` block every response about ``source`` carries."""
    return describe(db, source)


def _has_numbers(described: dict) -> bool:
    """Whether a clean read's numbers exist to show. A source with no key
    shows none, however old its last numbers are."""
    return described["updated_at"] is not None and described["state"] != State.NOT_CONNECTED


@router.get("/shopify")
def shopify_tab(db: Session = Depends(get_session)) -> dict:
    """S1-S7 and the orders behind each, from the last clean read.

    ``cards`` is null when there are no numbers to show - never read, not
    connected, or failed before any clean read - so nothing renders a 0 for
    a number nobody has.
    """
    from app.services.shopify.connection import effective

    described = freshness(db, "shopify")
    body: dict = {"freshness": described, "total": None, "cards": None}
    if _has_numbers(described):
        body.update(shopify.tab(db, effective(db).shop_domain))
    return body

