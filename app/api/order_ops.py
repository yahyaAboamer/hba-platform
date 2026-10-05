"""Operations: what is waiting in Shopify, Bosta and E-stebdal (ADR 0057).

Every route here is behind ``order_ops.view``, held by the operations manager
and the admin and by nobody else. The guard is on the router itself rather
than repeated per route, so a route added later cannot be added without it.

Every route reads only the platform's own tables, filled every 5 minutes by
``app.services.order_ops.polling``; nothing here calls Shopify, Bosta or
E-stebdal while a page waits. Each response carries ``freshness`` for the
source it is about, so a number is never shown without the time it was read,
and a source that could not be read never shows as 0.

The tabs' routes arrive with their tabs: Shopify, E-stebdal, Bosta.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.permissions import Permission
from app.services.order_ops.freshness import describe

#: The one guard, kept by name so a test can find it on every route.
GUARD = require_permission(Permission.ORDER_OPS_VIEW)

router = APIRouter(prefix="/api/order-ops", tags=["order-ops"], dependencies=[Depends(GUARD)])


def freshness(db: Session, source: str) -> dict:
    """The ``freshness`` block every response about ``source`` carries."""
    return describe(db, source)
