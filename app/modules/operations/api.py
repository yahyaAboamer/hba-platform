"""Operations: what is waiting in Shopify, Bosta and E-stebdal (ADR 0057).

Every route here is behind ``order_ops.view``, held by the operations manager
and the admin and by nobody else. The guard is on the router itself rather
than repeated per route, so a route added later cannot be added without it.

Every route reads only the platform's own tables, filled every 5 minutes by
``app.modules.operations.services.polling``; nothing here calls Shopify, Bosta or
E-stebdal while a page waits. Each response carries ``freshness`` for the
source it is about, so a number is never shown without the time it was read,
and a source that could not be read never shows as 0.

One route per tab - Shopify, E-stebdal, Bosta - and Bosta's success rate; and
every source's state at once, for the frame's sidebar.
"""

from datetime import date

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.shared.api.deps import require_permission
from app.core.permissions import Permission
from app.db import get_session
from app.shared.models.identity import UserAccount
from app.modules.operations.services import bosta, connections, estebdal, shopify
from app.modules.operations.services.freshness import SOURCES, State, describe

#: The one guard, kept by name so a test can find it on every route.
GUARD = require_permission(Permission.ORDER_OPS_VIEW)

router = APIRouter(prefix="/api/order-ops", tags=["order-ops"], dependencies=[Depends(GUARD)])

#: The frame's own reads about Operations (ADR 0068), under `/api/operations`
#: beside the sidebar's other numbers. The same guard, on the router itself.
frame_router = APIRouter(
    prefix="/api/operations", tags=["order-ops"], dependencies=[Depends(GUARD)]
)


def freshness(db: Session, source: str) -> dict:
    """The ``freshness`` block every response about ``source`` carries."""
    return describe(db, source)


def _has_numbers(described: dict) -> bool:
    """Whether a clean read's numbers exist to show. A source with no key
    shows none, however old its last numbers are."""
    return described["updated_at"] is not None and described["state"] != State.NOT_CONNECTED


@frame_router.get("/freshness")
def every_sources_freshness(db: Session = Depends(get_session)) -> dict:
    """Each source's state, in ``SOURCES`` order, for the sidebar's red dot.

    ``failing_since`` is when the latest failed read was tried: a run of
    failures is not recorded, as each one rewrites the attempt's time. Null
    unless the state is ``failed``.
    """
    sources = []
    for source in SOURCES:
        described = describe(db, source)
        failed = described["state"] == State.FAILED
        sources.append(
            {
                "source": described["source"],
                "label": described["label"],
                "state": described["state"],
                "updated_at": described["updated_at"],
                "failing_since": described["checked_at"] if failed else None,
            }
        )
    return {"sources": sources}


@router.get("/shopify")
def shopify_tab(db: Session = Depends(get_session)) -> dict:
    """S1-S7 and the orders behind each, from the last clean read.

    ``cards`` is null when there are no numbers to show - never read, not
    connected, or failed before any clean read - so nothing renders a 0 for
    a number nobody has.
    """
    from app.shared.services.shopify.connection import effective

    described = freshness(db, "shopify")
    body: dict = {"freshness": described, "total": None, "cards": None}
    if _has_numbers(described):
        body.update(shopify.tab(db, effective(db).shop_domain))
    return body


@router.get("/estebdal")
def estebdal_tab(db: Session = Depends(get_session)) -> dict:
    """E1, Needs review, and the requests behind it, from the last clean read.

    ``cards`` is null when there are no numbers to show, as on Shopify.
    """
    from app.shared.services.shopify.connection import effective

    described = freshness(db, "estebdal")
    body: dict = {"freshness": described, "total": None, "cards": None}
    if _has_numbers(described):
        body.update(estebdal.tab(db, effective(db).shop_domain))
    return body


@router.get("/bosta")
def bosta_tab(db: Session = Depends(get_session)) -> dict:
    """B1, B2, B5 and B6 with their orders, and the last 7 days of pickups.

    ``cards`` and ``pickups`` are null when there are no numbers to show.
    The pickups say whether the mirror's history is whole yet.
    """
    described = freshness(db, "bosta")
    body: dict = {"freshness": described, "cards": None, "pickups": None}
    if _has_numbers(described):
        body.update(bosta.tab(db))
    return body


@router.get("/bosta/success-rate")
def bosta_success_rate(
    start: date = Query(alias="from"),
    end: date = Query(alias="to"),
    db: Session = Depends(get_session),
) -> dict:
    """B4 for orders created on Bosta from ``from`` to ``to`` (Cairo dates).

    422 for a range that cannot be asked; ``available: false`` while the
    mirror has not read that far back yet, or has not read Bosta at all.
    """
    described = freshness(db, "bosta")
    try:
        rate = bosta.success_rate(db, start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if not _has_numbers(described):
        rate = {"from": rate["from"], "to": rate["to"], "available": False, "read_back_to": None}
    return {"freshness": described, **rate}


@router.get("/whatsapp")
def whatsapp_tab(
    card: Literal["failed", "no_whatsapp", "never_messaged", "answers_not_recorded", "waiting"]
    | None = None,
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_session),
) -> dict:
    """Order confirmations that went wrong (ADR 0059, point 18).

    Read-only like every other tab here, and with no customer details: an
    order number, when it was placed and why. The fix is made in the Inbox.
    """
    from app.modules.inbox.services import health

    return health.summary(db, card=card, days=days)


# ── The keys, for Settings ────────────────────────────────────────────────────

#: Changing a key is an admin's: ``settings.manage`` on top of the router's
#: own guard, which an admin holds as well. The operations manager sees the
#: dashboard and never its keys.
SETTINGS_GUARD = require_permission(Permission.SETTINGS_MANAGE)

Provider = Literal["bosta", "estebdal"]


class KeyBody(BaseModel):
    #: No length rule here: a validation error would echo the value back.
    #: ``connections.save`` checks it and refuses in its own words.
    key: str = ""


@router.get("/connections/{provider}")
def key_state(
    provider: Provider,
    _actor: UserAccount = Depends(SETTINGS_GUARD),
    db: Session = Depends(get_session),
) -> dict:
    """The key in use, for Settings: where it comes from and its last four
    characters. **Never the key.**"""
    return connections.describe(db, provider)


@router.put("/connections/{provider}")
def save_key(
    provider: Provider,
    body: KeyBody,
    actor: UserAccount = Depends(SETTINGS_GUARD),
    db: Session = Depends(get_session),
) -> dict:
    """Save a new key - only if it answers its provider.

    A refusal leaves the key in use exactly as it was, and says why in words
    safe to show; the key is never echoed back, logged or audited.
    """
    try:
        described = connections.save(
            db, provider, body.key, actor_id=actor.id, actor_email=actor.email
        )
    except connections.KeyNotSaved as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from None
    db.commit()
    return described

