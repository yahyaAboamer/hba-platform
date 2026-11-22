"""Marking a settled refund received in E-stebdal (ADR 0090).

A refund row that is **paid** and **back** (Khazenly said *Return
Completed*) is due. Its E-stebdal request is found from the row's Shopify
order number, and the one *Approved* request is marked received. E-stebdal
then moves it to *Processing*, where the owner's team closes it, and only a
closed request takes the sale out of E-stebdal's and Shopify's reports.

**Paid never waits for this.** The outcome is kept on the row
(``estebdal_*``) and a row that is not done is tried again on a later run,
or at once by a person's *Try again*. Nothing here raises because of
E-stebdal.

**Nothing is guessed.** Two *Approved* requests on one order wait for a
person to choose one. The POST is sent once: an answer lost on the way back
shows on the next read as the request already *Processing*, which counts
as done.

``ESTEBDAL_MARK_RECEIVED`` decides whether anything is sent at all: ``off``
(the default, and staging's: there is only one real E-stebdal), ``manual``
(a person's click only) or ``auto`` (also the background run).
"""

import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.businesstime import utcnow
from app.modules.operations.models import OpsRefund
from app.modules.operations.services import estebdal
from app.modules.operations.services.polling import NotConnected, SourceUnavailable
from app.modules.operations.services.returns import Refused, _get
from app.shared.models.identity import UserAccount
from app.shared.services.audit import record_audit
from app.shared.services.jobs import JobKind
from app.worker import register_handler

logger = logging.getLogger(__name__)

APPROVED = "Approved"
#: Not yet approved: tried again later.
NOT_YET = ("Needs Review", "Pending Payment")
#: Already received there, by somebody or by an answer that was lost.
ALREADY = ("Processing", "Closed")

#: A row not done is tried again after this long by the background run.
TRY_EVERY = timedelta(minutes=15)
#: The most rows one run takes, and its bounds, as the Khazenly read's:
#: well inside the operations lane's 5-minute lease.
BATCH = 50
BUDGET = timedelta(minutes=2)
GIVE_UP_AFTER = 3

OFF = "Sending to E-stebdal is off on this server."
NOT_DUE = "Only a refund that is paid and back can be marked received in E-stebdal."
NOT_A_CHOICE = "That request isn't approved in E-stebdal any more. Try again to see the current ones."


def mode() -> str:
    return settings.estebdal_mark_received


def is_due(row: OpsRefund) -> bool:
    return row.paid_on is not None and row.received_at is not None and row.estebdal_state != "done"


def _client_for(db: Session) -> estebdal.EstebdalClient:
    from app.modules.operations.services.connections import api_key

    return estebdal.EstebdalClient(api_key(db, "estebdal"))


def _note(row: OpsRefund, state: str, note: str | None, now: datetime, choices: list | None = None) -> None:
    row.estebdal_state = state
    row.estebdal_note = note[:200] if note else None
    row.estebdal_choices = choices or []
    row.estebdal_tried_at = now


def _done(row: OpsRefund, request: str, note: str | None, now: datetime) -> None:
    _note(row, "done", note, now)
    row.estebdal_request = request[:40]
    row.estebdal_done_at = now


def send(
    db: Session,
    row: OpsRefund,
    client: estebdal.EstebdalClient,
    *,
    choice: str | None = None,
    actor: UserAccount | None = None,
    now: datetime | None = None,
) -> bool:
    """Find this row's request and mark it received; keep the outcome on the
    row. Returns True when E-stebdal itself failed (did not answer, or
    refused the key), so the run can stop. Raises only ``Refused``, for a
    ``choice`` that is not approved."""
    now = now or utcnow()
    if not row.order_number:
        _note(row, "missing", "This refund has no Shopify order number, so its E-stebdal request can't be found.", now)
        return False
    try:
        requests = client.requests_for_order(row.order_number)
    except (SourceUnavailable, NotConnected) as exc:
        _note(row, "waiting", _unavailable(exc), now)
        return True

    approved = [r for r in requests if r["status"] == APPROVED]
    if choice is not None:
        approved = [r for r in approved if r["id"] == choice]
        if not approved:
            raise Refused(NOT_A_CHOICE)
    if len(approved) > 1:
        _note(
            row,
            "choose",
            f"Order {row.order_number} has {len(approved)} approved requests in E-stebdal. Choose the one for this refund.",
            now,
            choices=[{"id": r["id"], "number": r["number"]} for r in sorted(approved, key=lambda r: r["number"])],
        )
        return False
    if not approved:
        waiting = [r for r in requests if r["status"] in NOT_YET]
        already = [r for r in requests if r["status"] in ALREADY]
        if waiting:
            _note(row, "waiting", f"{waiting[0]['number']} is still waiting for review in E-stebdal.", now)
        elif already:
            _done(row, already[0]["number"], "Already received in E-stebdal.", now)
        elif requests:
            _note(row, "missing", f"The E-stebdal request for {row.order_number} was rejected or cancelled.", now)
        else:
            _note(row, "missing", f"There is no E-stebdal request for order {row.order_number}.", now)
        return False

    request = approved[0]
    notify = bool(row.estebdal_notify)
    try:
        answer = client.mark_received(request["id"], notify=notify)
    except estebdal.Rejected as exc:
        _note(row, "waiting", f"E-stebdal refused it: {exc}", now)
        return False
    except (SourceUnavailable, NotConnected) as exc:
        _note(row, "waiting", _unavailable(exc), now)
        return True
    _done(row, request["number"], "; ".join(answer["warnings"]) or None, now)
    record_audit(
        db,
        action="order_ops.refund_estebdal_received",
        subject=f"refund:{row.khazenly_number}",
        actor_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        after={
            "number": row.khazenly_number,
            "amount": str(row.amount) if row.amount is not None else None,
            "request": request["number"],
            "emailed": notify,
            "by_hand": actor is not None,
        },
    )
    return False


def _unavailable(exc: Exception) -> str:
    if isinstance(exc, NotConnected):
        return "E-stebdal isn't connected. Add its key in Settings → Integrations."
    if isinstance(exc, estebdal.KeyRefused):
        return "E-stebdal refused the key. It may not be allowed to write: use an all-access key."
    return f"{exc} It will be tried again."


def due_rows(db: Session, now: datetime) -> list[OpsRefund]:
    """Paid, back, not done, and not tried in the last ``TRY_EVERY``,
    least recently tried first."""
    return list(
        db.scalars(
            select(OpsRefund)
            .where(
                OpsRefund.paid_on.is_not(None),
                OpsRefund.received_at.is_not(None),
                OpsRefund.estebdal_state.is_distinct_from("done"),
                (OpsRefund.estebdal_tried_at.is_(None)) | (OpsRefund.estebdal_tried_at <= now - TRY_EVERY),
            )
            .order_by(OpsRefund.estebdal_tried_at.asc().nulls_first(), OpsRefund.id)
            .limit(BATCH)
            .with_for_update(skip_locked=True)
        )
    )


def send_due(
    db: Session,
    client: estebdal.EstebdalClient | None = None,
    budget_seconds: float | None = None,
    clock=time.monotonic,
) -> int:
    """The background run: every due row, bounded. Returns how many were
    tried. Does nothing unless the switch is ``auto``."""
    if mode() != "auto":
        return 0
    now = utcnow()
    rows = due_rows(db, now)
    if not rows:
        return 0
    try:
        client = client or _client_for(db)
    except NotConnected:
        for row in rows:
            _note(row, "waiting", _unavailable(NotConnected()), now)
        db.flush()
        return 0
    budget = BUDGET.total_seconds() if budget_seconds is None else budget_seconds
    started = clock()
    tried = 0
    failed_in_a_row = 0
    for row in rows:
        if tried and clock() - started >= budget:
            break
        if failed_in_a_row >= GIVE_UP_AFTER:
            break
        failed = send(db, row, client, now=utcnow())
        tried += 1
        failed_in_a_row = failed_in_a_row + 1 if failed else 0
    db.flush()
    logger.info("returns: marked %d of %d due refunds in E-stebdal", tried, len(rows))
    return tried


def by_hand(
    db: Session,
    refund_id: int,
    actor: UserAccount,
    choice: str | None = None,
    client: estebdal.EstebdalClient | None = None,
) -> OpsRefund:
    """A person's *Mark received in E-stebdal*, *Try again* or choice."""
    if mode() == "off":
        raise Refused(OFF)
    row = _get(db, refund_id)
    if not is_due(row):
        raise Refused(NOT_DUE)
    try:
        client = client or _client_for(db)
    except NotConnected:
        _note(row, "waiting", _unavailable(NotConnected()), utcnow())
        db.flush()
        return row
    send(db, row, client, choice=choice, actor=actor)
    db.flush()
    return row


@register_handler(JobKind.ORDER_OPS_ESTEBDAL_RECEIVED)
def _handle_send(db: Session, payload: dict) -> None:
    send_due(db)
