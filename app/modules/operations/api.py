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
every source's state at once, for the frame's sidebar. Khazenly (ADR 0071)
reads the same Shopify table, from a file a person uploads; it has its own
router and permission (ADR 0072), at the end of this file.
"""

import base64
from datetime import date, datetime

from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.shared.api.deps import require_any_permission, require_permission
from app.core.permissions import Permission
from app.db import get_session
from app.shared.models.identity import UserAccount
from app.shared.services.audit import record_audit
from app.modules.operations.services import bosta, connections, estebdal, khazenly, returns, shopify
from app.modules.operations.services.freshness import SOURCES, State, describe, has_numbers

#: The one guard, kept by name so a test can find it on every route.
GUARD = require_permission(Permission.ORDER_OPS_VIEW)

router = APIRouter(prefix="/api/order-ops", tags=["order-ops"], dependencies=[Depends(GUARD)])

#: The frame's own reads about Operations (ADR 0068), under `/api/operations`
#: beside the sidebar's other numbers. The same guard, on the router itself.
frame_router = APIRouter(
    prefix="/api/operations", tags=["order-ops"], dependencies=[Depends(GUARD)]
)

#: Operations → Khazenly (ADR 0071, 0072), held by customer service as well.
#: Its history is read by customer service and by every Operations level
#: (ADR 0079: viewers see every tab); building the file is `khazenly.use`
#: alone, on the route itself.
KHAZENLY_GUARD = require_permission(Permission.KHAZENLY_USE)
KHAZENLY_READ = require_any_permission(Permission.KHAZENLY_USE, Permission.ORDER_OPS_VIEW)

khazenly_router = APIRouter(
    prefix="/api/khazenly", tags=["khazenly"], dependencies=[Depends(KHAZENLY_READ)]
)

#: Operations → Returns (ADR 0079): seen with the dashboard (`GUARD`),
#: changed only by staff, the manager and the admin.
RETURNS_GUARD = require_permission(Permission.RETURNS_EDIT)


def freshness(db: Session, source: str) -> dict:
    """The ``freshness`` block every response about ``source`` carries."""
    return describe(db, source)


#: Shared with Today (``app.modules.operations.today``).
_has_numbers = has_numbers


@frame_router.get("/freshness")
def every_sources_freshness(db: Session = Depends(get_session)) -> dict:
    """Each source's state, in ``SOURCES`` order, for the sidebar's red dot.

    ``failed_at`` is when the latest failed read was tried, not when the
    failures began: each attempt rewrites it, so the sidebar says how long
    since ``updated_at``, the last clean read. Null unless the state is
    ``failed``.
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
                "failed_at": described["checked_at"] if failed else None,
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


# ── Returns (ADR 0079) ────────────────────────────────────────────────────────


class RefundAdd(BaseModel):
    #: One Khazenly number, or several pasted together.
    numbers: list[str]
    kind: str
    amount: str | None = None
    method: str | None = None
    refund_to: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None


class RefundEdit(BaseModel):
    kind: str | None = None
    amount: str | None = None
    method: str | None = None
    refund_to: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None


class RefundPaid(BaseModel):
    paid_on: str | None = None
    amount: str | None = None
    method: str | None = None
    refund_to: str | None = None


class RefundUnpaid(BaseModel):
    reason: str = ""


def _refused(exc: returns.Refused) -> HTTPException:
    return HTTPException(409 if isinstance(exc, returns.Locked) else 422, str(exc))


def _row(db: Session, refund_id: int) -> dict:
    return {"refund": returns.one(db, refund_id)}


@router.get("/returns")
def returns_tab(db: Session = Depends(get_session)) -> dict:
    """Every unpaid refund and the latest paid, grouped by the next act."""
    return returns.tab(db)


@router.post("/returns")
def add_refunds(
    body: RefundAdd,
    actor: UserAccount = Depends(RETURNS_GUARD),
    db: Session = Depends(get_session),
) -> dict:
    """Add one refund, or several pasted Khazenly numbers. Each is read from
    Khazenly first; the ones refused say why, and the rest are added."""
    details = body.model_dump(exclude={"numbers", "kind"}, exclude_unset=True)
    try:
        result = returns.add(db, body.numbers, body.kind, actor, details)
    except returns.Refused as exc:
        db.rollback()
        raise _refused(exc) from None
    db.commit()
    return result


@router.patch("/returns/{refund_id}")
def edit_refund(
    refund_id: int,
    body: RefundEdit,
    actor: UserAccount = Depends(RETURNS_GUARD),
    db: Session = Depends(get_session),
) -> dict:
    try:
        returns.edit(db, refund_id, body.model_dump(exclude_unset=True), actor)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except returns.Refused as exc:
        db.rollback()
        raise _refused(exc) from None
    db.commit()
    return _row(db, refund_id)


@router.post("/returns/{refund_id}/paid")
def mark_refund_paid(
    refund_id: int,
    body: RefundPaid,
    actor: UserAccount = Depends(RETURNS_GUARD),
    db: Session = Depends(get_session),
) -> dict:
    """Record that the refund was sent. Nothing is sent from here."""
    try:
        returns.mark_paid(db, refund_id, body.model_dump(exclude_unset=True), actor)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except returns.Refused as exc:
        db.rollback()
        raise _refused(exc) from None
    db.commit()
    return _row(db, refund_id)


@router.post("/returns/{refund_id}/unpaid")
def undo_refund_paid(
    refund_id: int,
    body: RefundUnpaid,
    actor: UserAccount = Depends(RETURNS_GUARD),
    db: Session = Depends(get_session),
) -> dict:
    try:
        returns.undo_paid(db, refund_id, body.reason, actor)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except returns.Refused as exc:
        db.rollback()
        raise _refused(exc) from None
    db.commit()
    return _row(db, refund_id)


@router.post("/returns/{refund_id}/check")
def recheck_refund(
    refund_id: int,
    _actor: UserAccount = Depends(RETURNS_GUARD),
    db: Session = Depends(get_session),
) -> dict:
    """Ask Khazenly again now, rather than wait for the next read."""
    try:
        returns.recheck(db, refund_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except returns.Refused as exc:
        db.rollback()
        raise _refused(exc) from None
    db.commit()
    return _row(db, refund_id)


@router.delete("/returns/{refund_id}")
def delete_refund(
    refund_id: int,
    actor: UserAccount = Depends(RETURNS_GUARD),
    db: Session = Depends(get_session),
) -> dict:
    """Remove a refund added by mistake. Never a paid one."""
    try:
        returns.delete(db, refund_id, actor)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except returns.Refused as exc:
        db.rollback()
        raise _refused(exc) from None
    db.commit()
    return {"deleted": refund_id}


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



# ── Khazenly (ADR 0071, 0072) ─────────────────────────────────────────────────


@khazenly_router.get("")
def khazenly_tab(db: Session = Depends(get_session)) -> dict:
    """How fresh Shopify's tags are, and the runs so far, newest first."""
    return {"freshness": freshness(db, "shopify"), "runs": khazenly.history(db)}


@khazenly_router.get("/runs/{run_id}")
def khazenly_run(run_id: int, db: Session = Depends(get_session)) -> dict:
    """One run with its orders, as its summary showed them."""
    found = khazenly.run_summary(db, run_id)
    if found is None:
        raise HTTPException(404, "There is no such run.")
    return found


@khazenly_router.post("")
def khazenly_confirmations(
    file: UploadFile = File(...),
    actor: UserAccount = Depends(KHAZENLY_GUARD),
    db: Session = Depends(get_session),
) -> dict:
    """Khazenly's bulk-confirm file for the confirmed orders in its export.

    Read in memory and never stored: the export carries customer names. The
    answer names orders by number only, and the file comes back in it, so
    nothing waits on the server to be downloaded. The summary is kept as a
    run for the history (ADR 0072). **Only while Shopify's tags are fresh** -
    an export matched against old tags is never a file (ADR 0071, decision 4).
    """
    described = freshness(db, "shopify")
    if described["state"] != State.FRESH:
        raise HTTPException(
            409,
            "Shopify's tags aren't up to date, so no file was built. "
            "Try again once the tab shows Shopify updated in the last few minutes.",
        )
    content = file.file.read(khazenly.MAX_UPLOAD_BYTES + 1)
    try:
        built = khazenly.build(db, file.filename or "", content)
    except khazenly.ExportRefused as exc:
        raise HTTPException(422, str(exc)) from None

    run = khazenly.keep(
        db,
        built,
        built_by=actor.id,
        shopify_read_at=datetime.fromisoformat(described["updated_at"]) if described["updated_at"] else None,
    )
    record_audit(
        db,
        action="order_ops.khazenly_file_built",
        subject="khazenly",
        actor_id=actor.id,
        actor_email=actor.email,
        # Counts only: the orders are in the run, the names nowhere.
        after={
            "rows_read": built.summary["rows_read"],
            "confirmed": built.summary["confirmed"],
            "file": built.file is not None,
            "run": run.id,
        },
    )
    db.commit()
    return {
        "freshness": described,
        "run_id": run.id,
        **built.summary,
        "file": None
        if built.file is None
        else {"name": built.file_name, "content_base64": base64.b64encode(built.file).decode()},
    }
