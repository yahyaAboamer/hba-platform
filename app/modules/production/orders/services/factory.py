"""The factory's own login (ADR 0084, batch 6b; build plan
``docs/plans/2026-11-16-production-factory-login-build.md``).

Two sides:

* **HBA's** (``/api/prod``, ``production.suppliers``): invite a supplier's
  login by email, send a fresh link, switch it off. Switching off suspends the
  account through the staff suspension service, so every session ends and the
  very next request is refused.
* **The factory's** (``/api/factory``, ``current_factory``): its own open
  orders, one order, the cut it reports and moving its delivery date.

**What the factory is shown is built here from a whitelist of fields**, never
from ``orders.view``: no key ending ``_piastres``, no money in words, no other
supplier's id or name, no ratings, no note written by HBA and no HBA person's
name (HBA people are "HBA"). The only text that is not the factory's own is
the reason a delivery date moved, which the approved screen shows.

Every write here only stages; the route commits on success and rolls back on
a refusal (the module's pattern).
"""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.businesstime import business_date, utcnow
from app.core.permissions import FACTORY_ROLE
from app.modules.production.models import ProductionSupplier
from app.modules.production.orders.models import (
    SIZES,
    ProdCutReport,
    ProdFactoryAccess,
    ProdOrder,
    ProdOrderDateChange,
)
from app.modules.production.orders.services import account
from app.modules.production.orders.services import orders as order_service
from app.modules.production.orders.services.orders import (
    Locked,
    NotFound,
    Refused,
    _day,
    _facts,
    _facts_for,
    _iso,
    _pieces,
    _plural,
    _text,
)
from app.shared.models.identity import AuthSession, Invitation, UserAccount
from app.shared.services.audit import record_audit

#: How long a closed order stays readable to its factory.
CLOSED_DAYS = 30

#: The longest note a factory may send with its cut.
MAX_NOTE = 500


class NotYours(LookupError):
    """Not this factory's order, a cancelled one, or no order at all: 403,
    always in the same words, so a status code never says which."""


NOT_YOURS = "This order is not one of yours."


# ── HBA's side: the login on the supplier's page ──────────────────────────────


def _subject(supplier_id: str) -> str:
    return f"production:supplier:{supplier_id}"


def _audit(db: Session, supplier: ProductionSupplier, actor: UserAccount, what: str, summary: str, **extra) -> None:
    record_audit(
        db,
        action=f"production.factory_login_{what}",
        subject=_subject(supplier.id),
        actor_id=actor.id,
        actor_email=actor.email,
        after={"summary": summary[:500], **extra},
    )


def _locked_supplier(db: Session, supplier_id: str) -> ProductionSupplier:
    supplier = account.lock_supplier(db, supplier_id) if supplier_id else None
    if supplier is None or supplier.deleted_at is not None:
        raise NotFound("There is no such supplier.")
    return supplier


def _live(db: Session, supplier_id: str, *, lock: bool = False) -> ProdFactoryAccess | None:
    query = select(ProdFactoryAccess).where(
        ProdFactoryAccess.supplier_id == supplier_id, ProdFactoryAccess.switched_off_at.is_(None)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def _email(value: str) -> str:
    email = str(value or "").strip().lower()
    if not email or len(email) > 320 or "@" not in email:
        raise Refused("Give the factory's email address.")
    return email


#: One answer for every address that cannot be used, so an invitation never
#: tells whether an address has an account or a link waiting.
_UNUSABLE = "This address cannot be used for a factory login. Use another one."

#: How far the factory may move its date: not more than a month back, not
#: more than two years ahead (a typing slip, or a date the server cannot
#: count from).
DATE_BACK_DAYS = 30
DATE_AHEAD_DAYS = 730


def _free_address(db: Session, email: str) -> None:
    """Refuse an address that is already somebody's, in words that do not say
    whose: an account (staff or model), a link waiting for anybody, or
    another supplier's login."""
    if db.scalar(select(UserAccount.id).where(func.lower(UserAccount.email) == email).limit(1)) is not None:
        raise Refused(_UNUSABLE)
    waiting = db.scalar(
        select(Invitation.id)
        .where(
            func.lower(Invitation.email) == email,
            Invitation.accepted_at.is_(None),
            Invitation.expires_at > utcnow(),
        )
        .limit(1)
    )
    if waiting is not None:
        raise Refused(_UNUSABLE)
    taken = db.scalar(
        select(ProdFactoryAccess.id)
        .where(ProdFactoryAccess.email == email, ProdFactoryAccess.switched_off_at.is_(None))
        .limit(1)
    )
    if taken is not None:
        raise Refused("This email is already another factory's login.")


def _send(db: Session, email: str, name: str | None, actor: UserAccount) -> tuple[str, Invitation]:
    """The platform's ordinary invitation, with the role ``factory``."""
    from app.shared.services.invitations import create_invitation

    try:
        return create_invitation(db, email, FACTORY_ROLE, actor.id, name=name)
    except ValueError as exc:
        raise Refused(str(exc)) from None


def invite(db: Session, supplier_id: str, data: dict, actor: UserAccount) -> tuple[ProductionSupplier, str, Invitation]:
    """Invite the supplier's login. Refuses a supplier that already has a
    live one and an address already somebody's. Returns the raw token for the
    route to email (it is never stored)."""
    supplier = _locked_supplier(db, supplier_id)
    if _live(db, supplier.id, lock=True) is not None:
        raise Locked(f"{supplier.name} already has a factory login. Switch it off first to invite another.")
    email = _email(data.get("email"))
    name = _text(data.get("name"), limit=120, what="the name")
    _free_address(db, email)
    token, invitation = _send(db, email, name, actor)
    db.flush()
    db.add(ProdFactoryAccess(supplier_id=supplier.id, email=email, invitation_id=invitation.id, created_by=actor.id))
    db.flush()
    _audit(db, supplier, actor, "invited", f"Invited {email} to sign in as {supplier.name}", email=email)
    return supplier, token, invitation


def resend(db: Session, supplier_id: str, actor: UserAccount) -> tuple[ProductionSupplier, str, Invitation]:
    """A fresh link for a login not yet accepted; the old one stops working
    in the same transaction."""
    supplier = _locked_supplier(db, supplier_id)
    access = _live(db, supplier.id, lock=True)
    if access is None:
        raise Locked(f"{supplier.name} has no factory login switched on.")
    if access.user_account_id is not None:
        raise Locked("The factory has already signed up. There is no link to send again.")
    old = db.get(Invitation, access.invitation_id, with_for_update=True) if access.invitation_id else None
    name = old.name if old is not None else None
    if old is not None and old.accepted_at is None and old.expires_at > utcnow():
        old.expires_at = utcnow()
    token, invitation = _send(db, access.email, name, actor)
    db.flush()
    access.invitation_id = invitation.id
    _audit(db, supplier, actor, "resent", f"Sent {access.email} a new link to sign in as {supplier.name}", email=access.email)
    return supplier, token, invitation


#: The reason the suspension carries in the trail.
SWITCHED_OFF = "Factory login switched off from the supplier's page"


def switch_off(db: Session, supplier_id: str, actor: UserAccount) -> ProductionSupplier:
    """Switch the login off **now**: a link not yet used is withdrawn; an
    account is suspended (the staff suspension: status, roles, every session
    and remembered browser), so its very next request is refused."""
    from app.shared.services.auth import revoke_all_sessions
    from app.shared.services.staff import _revoke, revoke_invitation, suspend_staff

    supplier = _locked_supplier(db, supplier_id)
    access = _live(db, supplier.id, lock=True)
    if access is None:
        raise Locked(f"{supplier.name} has no factory login switched on.")
    if access.user_account_id is None:
        invitation = db.get(Invitation, access.invitation_id, with_for_update=True) if access.invitation_id else None
        if invitation is not None and invitation.accepted_at is None and invitation.withdrawn_at is None:
            revoke_invitation(db, invitation, actor_id=actor.id, actor_email=actor.email)
    else:
        user = db.get(UserAccount, access.user_account_id, with_for_update=True, populate_existing=True)
        if user is not None and user.status != "suspended":
            suspend_staff(db, user, reason=SWITCHED_OFF, actor_id=actor.id, actor_email=actor.email)
        elif user is not None:
            # Already suspended: make sure nothing of the login is left.
            from app.shared.models.identity import RoleAssignment

            _revoke(
                db,
                list(
                    db.scalars(
                        select(RoleAssignment).where(
                            RoleAssignment.user_account_id == user.id,
                            RoleAssignment.role == FACTORY_ROLE,
                            RoleAssignment.revoked_at.is_(None),
                        )
                    )
                ),
            )
            revoke_all_sessions(db, user.id)
    access.switched_off_at = utcnow()
    access.switched_off_by = actor.id
    db.flush()
    _audit(db, supplier, actor, "off", f"Switched off {access.email}'s login as {supplier.name}", email=access.email)
    return supplier


def login_view(db: Session, supplier_id: str) -> dict | None:
    """The supplier page's login card, for people holding
    ``production.suppliers`` only: the newest login, live or switched off;
    ``None`` when the supplier never had one."""
    access = db.scalar(
        select(ProdFactoryAccess)
        .where(ProdFactoryAccess.supplier_id == supplier_id)
        .order_by(ProdFactoryAccess.id.desc())
        .limit(1)
    )
    if access is None:
        return None
    if access.switched_off_at is not None:
        state = "off"
    elif access.user_account_id is None:
        state = "invited"
    else:
        state = "active"
    invitation = db.get(Invitation, access.invitation_id) if access.invitation_id else None
    seen = None
    if access.user_account_id is not None:
        seen = db.scalar(
            select(func.max(AuthSession.last_seen_at)).where(AuthSession.user_account_id == access.user_account_id)
        )
    return {
        "state": state,
        "email": access.email,
        "invited_at": _iso(invitation.created_at if invitation is not None else access.created_at),
        "last_seen_at": _iso(seen),
    }


# ── The factory's side ────────────────────────────────────────────────────────

#: What printing the screen says, without naming anybody else.
PRINTING_WORDS = {"factory": "at your factory", "outside": "at a print house", "none": "none"}


def _status_words(facts: order_service.Facts, report: ProdCutReport | None) -> str:
    """Where the order is, in the factory's words. Never a cost and never
    what HBA wrote."""
    order = facts.order
    if order.status == "closed":
        return "finished"
    stage = facts.current
    if stage is None:
        return "finished"
    key = stage.stage
    if key == "sample":
        return "HBA asked for changes to the sample" if order.sample_status == "changes" else "sample with HBA"
    if key == "materials":
        return "fabric not yet with you" if order.fabric_bought_by == "hba" else "getting the materials ready"
    if key == "fabric_check":
        return "HBA is checking the fabric"
    if key == "pattern_check":
        return "HBA is checking the pattern"
    if key == "cutting":
        return "waiting for HBA to confirm your cut" if report is not None else "tell us how many you cut"
    if key == "making":
        return "being made"
    if key == "final_inspection":
        return "HBA is inspecting"
    if key == "warehouse":
        return "being delivered"
    return "delivered"


def _latest_reports(db: Session, order_ids: list[int]) -> dict[int, ProdCutReport]:
    """The newest report each order's factory sent that was not replaced,
    confirmed or still waiting."""
    if not order_ids:
        return {}
    found: dict[int, ProdCutReport] = {}
    for row in db.scalars(
        select(ProdCutReport)
        .where(ProdCutReport.order_id.in_(order_ids), ProdCutReport.replaced_at.is_(None))
        .order_by(ProdCutReport.id)
    ):
        found[row.order_id] = row
    return found


def _confirmed(facts: order_service.Facts, size: str | None = None) -> int | None:
    """The cut as the QC manager recorded it: only once cutting is done."""
    if not facts.done("cutting"):
        return None
    if size is None:
        return facts.total("cut")
    row = facts.sizes.get(size)
    return (row.cut or 0) if row is not None else None


def _reported(report: ProdCutReport | None, size: str | None = None) -> int | None:
    if report is None:
        return None
    sizes = report.sizes or {}
    if size is None:
        return sum(int(v) for v in sizes.values())
    return int(sizes[size]) if size in sizes else None


def _summary(facts: order_service.Facts, report: ProdCutReport | None, waiting: bool) -> dict:
    order = facts.order
    moved = order.delivery_date != order.target_date
    return {
        "id": order.id,
        "code": order.code,
        "style_name": order.style_name,
        "colour": order.colour,
        "printing": PRINTING_WORDS[order.printing],
        "planned_total": facts.total("planned"),
        "cut": {"reported_total": _reported(report), "confirmed_total": _confirmed(facts)},
        "status_words": _status_words(facts, report if waiting else None),
        "delivery_date": _day(order.delivery_date),
        "moved": moved,
        #: The date HBA first planned, when it has moved: the screen's
        #: "moved from 20 Nov".
        "moved_from": _day(order.target_date) if moved else None,
    }


def my_orders(db: Session, supplier: ProductionSupplier) -> dict:
    """The factory's open orders, newest delivery date last."""
    orders = list(
        db.scalars(
            select(ProdOrder)
            .where(ProdOrder.factory_id == supplier.id, ProdOrder.status == "open")
            .order_by(ProdOrder.delivery_date, ProdOrder.id)
        )
    )
    ids = [o.id for o in orders]
    facts = _facts_for(db, orders)
    latest = _latest_reports(db, ids)
    waiting = order_service.waiting_cut_reports(db, ids)
    return {
        "factory": {"name": supplier.name},
        "orders": [_summary(facts[o.id], latest.get(o.id), o.id in waiting) for o in orders],
    }


def _readable(order: ProdOrder | None, supplier: ProductionSupplier) -> ProdOrder:
    """This factory's order, open or closed in the last 30 days; anything
    else - another supplier's, cancelled, older, none at all - is refused
    alike."""
    if order is None or order.factory_id != supplier.id:
        raise NotYours(NOT_YOURS)
    if order.status == "open":
        return order
    if order.status == "closed" and order.settled_at is not None and order.settled_at >= utcnow() - timedelta(days=CLOSED_DAYS):
        return order
    raise NotYours(NOT_YOURS)


def _own(db: Session, supplier: ProductionSupplier, order_id: int, *, lock: bool = False) -> ProdOrder:
    order = db.get(ProdOrder, order_id, with_for_update=lock or None, populate_existing=lock or None)
    return _readable(order, supplier)


def my_order(db: Session, supplier: ProductionSupplier, order_id: int) -> dict:
    order = _own(db, supplier, order_id)
    facts = _facts(db, order)
    report = _latest_reports(db, [order.id]).get(order.id)
    waiting = order_service.waiting_cut_reports(db, [order.id]).get(order.id)
    open_ = order.status == "open"
    changes = list(
        db.scalars(
            select(ProdOrderDateChange)
            .where(ProdOrderDateChange.order_id == order.id)
            .order_by(ProdOrderDateChange.created_at, ProdOrderDateChange.id)
        )
    )
    return {
        **_summary(facts, report, waiting is not None),
        "sizes": [
            {
                "size": size,
                "planned": facts.sizes[size].planned,
                "reported": _reported(report, size),
                "confirmed": _confirmed(facts, size),
            }
            for size in SIZES
            if size in facts.sizes
        ],
        #: The report waiting for HBA's QC manager; none once confirmed (the
        #: confirmed figures are then in ``cut`` and ``sizes``).
        "report": None
        if waiting is None
        else {"reported_on": _day(business_date(waiting.reported_at)), "note": waiting.note},
        "can_report_cut": open_ and facts.stages["cutting"].status == "todo",
        "can_move_date": open_,
        "dates": [
            {
                "on": _day(business_date(change.created_at)),
                "date": _day(change.new_date),
                "by": "You" if change.set_by == "factory" else "HBA",
                "reason": change.reason,
            }
            for change in changes
        ],
    }


def report_cut(db: Session, supplier: ProductionSupplier, order_id: int, data: dict, actor: UserAccount) -> ProdOrder:
    """What the factory cut, per size, for the QC manager to confirm. While
    the order is open and cutting is not recorded; a report not yet confirmed
    is replaced, never edited."""
    order = _own(db, supplier, order_id, lock=True)
    if order.status != "open":
        raise Locked(f"{order.code} is finished. Nothing on it can change now.")
    facts = _facts(db, order)
    if facts.stages["cutting"].status != "todo":
        raise Locked("HBA has already recorded the cut on this order.")
    raw = data.get("sizes") or {}
    if not isinstance(raw, dict):
        raise Refused("Give the pieces cut for each size.")
    sizes: dict[str, int] = {}
    for size, count in raw.items():
        if size not in facts.sizes:
            raise Refused(f"{size} is not a size on this order.")
        sizes[size] = _pieces(count)
    for size in facts.sizes:
        sizes.setdefault(size, 0)
    total = sum(sizes.values())
    if total <= 0:
        raise Refused("Give the number cut for at least one size.")
    note = _text(data.get("note"), limit=MAX_NOTE, what="the note")

    waiting = order_service.waiting_cut_reports(db, [order.id], lock=True).get(order.id)
    now = utcnow()
    if waiting is not None:
        waiting.replaced_at = now
        db.flush()
    db.add(
        ProdCutReport(
            order_id=order.id,
            sizes={size: sizes[size] for size in SIZES if size in sizes},
            note=note,
            reported_by=actor.id,
            reported_at=now,
        )
    )
    db.flush()
    record_audit(
        db,
        action="production.order_cut_reported",
        subject=f"production:order:{order.id}",
        actor_id=actor.id,
        actor_email=actor.email,
        after={
            "summary": f"The factory reported {_plural(total, 'piece')} cut on {order.code}"
            + (" (corrected)" if waiting is not None else ""),
            "order": order.code,
        },
    )
    return order


def move_date(
    db: Session, supplier: ProductionSupplier, order_id: int, new: date, reason: str, actor: UserAccount
) -> ProdOrder:
    """The factory moves its delivery date, with a reason: batch 1's date
    move, set by the factory. Open orders only."""
    order = _own(db, supplier, order_id, lock=True)
    if order.status != "open":
        raise Locked(f"{order.code} is finished. Its date cannot move now.")
    on = order_service.today()
    if not on - timedelta(days=DATE_BACK_DAYS) <= new <= on + timedelta(days=DATE_AHEAD_DAYS):
        raise Refused("Give a date within the next two years.")
    return order_service.change_delivery_date(db, order.id, new, "factory", reason, actor)

