"""Attaching the orders a code already had when it was registered.

§9.2 permits it explicitly: *"a previously unattributed order may be attached
when its code is registered for the first time. This assigns an orphan; it does
not move an order."* Phase 3 deferred it here, because attaching an order means
writing `attributed_order`, and that table did not exist yet.

It matters more than it sounds. Models come to HBA with codes **already live**
and already selling — ADR 0022 is built on that. Without this, everything a code
earned before somebody typed it into the platform belongs to nobody, for ever,
and nothing says so.

## Attaching, never moving

Every order is put through the same `attribute_order` as a live one, which
refuses to reassign anything that already has an owner and reports it instead.
So an order another model has already been paid for cannot be quietly taken from
them by a mistyped registration — the job reports and carries on rather than
failing on a row it was never entitled to touch.

## It never blocks registration

§10.3: *"affiliate creation never blocks on it."* Registering a code queues this
and returns. Shopify is not called at all — every order is already in
`order_index` (§10.2 exists precisely so this question is answerable locally),
so the work is a query and some arithmetic.

## Bounded, and honest about the bound

A run processes at most ``MAX_ORDERS_PER_RUN`` orders and **queues itself again**
if more remain. A code with two thousand orders would otherwise hold a worker
lease for minutes and lose the lot when it expired (ADR 0021). The continuation
is queued from inside the same transaction that recorded the progress, so a
crash re-runs the batch rather than skipping it.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.affiliates import AffiliateProfile
from app.models.attributed_orders import AttributedOrder
from app.models.orders import OrderIndex
from app.services.commission.attribute import attribute_order
from app.services.jobs import JobKind, enqueue
from app.worker import register_handler

logger = logging.getLogger(__name__)

#: Enough that most codes finish in one run, small enough that a lease never
#: expires mid-batch. HBA's whole shop is about 30k orders a year, and the
#: busiest single code is a small fraction of that.
MAX_ORDERS_PER_RUN = 500


def orders_awaiting_attachment(
    db: Session, code: str, start_month: str, end_month: str | None, *, limit: int
) -> list[OrderIndex]:
    """Indexed orders using this code, in months they own, with no owner yet.

    The `end_month` bound is what stops a backfill reaching into months the code
    belonged to somebody else. A code that changed hands has periods either
    side, and each registration backfills only its own.
    """
    query = (
        select(OrderIndex)
        .outerjoin(
            AttributedOrder,
            AttributedOrder.shopify_order_id == OrderIndex.shopify_order_id,
        )
        .where(AttributedOrder.shopify_order_id.is_(None))
        .where(OrderIndex.discount_codes.any(code))
        .where(OrderIndex.business_month >= start_month)
    )
    if end_month is not None:
        query = query.where(OrderIndex.business_month <= end_month)

    return list(
        db.scalars(query.order_by(OrderIndex.business_month, OrderIndex.shopify_order_id).limit(limit))
    )


def queue_backfill(
    db: Session, affiliate: AffiliateProfile, code: str, start_month: str,
    end_month: str | None = None,
) -> None:
    """Ask for a code's history to be attached, later.

    Deduplicated per code and period: registering, re-checking and correcting a
    code in quick succession should do the work once.
    """
    enqueue(
        db,
        JobKind.BACKFILL_CODE,
        {
            "affiliate_id": affiliate.id,
            "code": code,
            "start_month": start_month,
            "end_month": end_month,
        },
        dedupe_key=f"backfill:{code}:{start_month}:{end_month or 'open'}",
    )


def backfill_code(
    db: Session,
    code: str,
    start_month: str,
    end_month: str | None = None,
    *,
    limit: int | None = None,
) -> tuple[int, bool]:
    """Attach what this code already earned. Returns ``(attached, more_remain)``.

    ``limit`` resolves at call time rather than as a default argument. A
    default would bind ``MAX_ORDERS_PER_RUN`` at import, making the constant
    look configurable while being nothing of the sort - found by a test that
    changed it and watched nothing happen.
    """
    batch = MAX_ORDERS_PER_RUN if limit is None else limit
    orders = orders_awaiting_attachment(db, code, start_month, end_month, limit=batch)
    attached = 0

    for order in orders:
        # The same path a live order takes. An order that already has an owner
        # is refused there and reported, not overwritten here.
        if attribute_order(db, order) is not None:
            attached += 1

    return attached, len(orders) == batch


@register_handler(JobKind.BACKFILL_CODE)
def _handle_backfill(db: Session, payload: dict) -> None:
    code = str(payload.get("code") or "").strip().upper()
    start_month = str(payload.get("start_month") or "").strip()
    end_month = payload.get("end_month")

    if not code or not start_month:
        from app.services.jobs import PermanentFailure

        raise PermanentFailure(
            "A backfill needs a code and a start month; retrying will not "
            f"supply them (code={code!r} start_month={start_month!r})"
        )

    attached, more = backfill_code(db, code, start_month, end_month)
    logger.info(
        "backfill attached %s order(s) for %s from %s%s",
        attached,
        code,
        start_month,
        " (more to come)" if more else "",
    )

    if more:
        # Queued inside the transaction that recorded this batch, so a crash
        # re-runs the batch rather than losing the continuation.
        enqueue(
            db,
            JobKind.BACKFILL_CODE,
            dict(payload),
            dedupe_key=f"backfill:{code}:{start_month}:{end_month or 'open'}:more",
        )
