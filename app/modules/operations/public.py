"""What other departments may use from Operations (ADR 0065).

The only part of this department another one may import: the import check
(pyproject.toml, `[tool.importlinter]`) refuses its api, models and services.
Empty on the day of the move; the crossings that existed then are listed in
that check, and each one that is untangled comes through here.
"""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.operations.models import OpsEstebdalReturn, OpsRefund

from app.modules.operations.services.bosta import order_numbers_on_bosta
from app.modules.operations.services.freshness import describe
from app.modules.operations.today import look as today_look

__all__ = [
    "bosta_read_at",
    "order_numbers_on_bosta",
    "order_numbers_with_return_work",
    "source_state",
    "today_look",
]


def bosta_read_at(db: Session) -> datetime | None:
    """When Bosta was last read cleanly: what the order week's *With Bosta*
    row is as of."""
    updated = describe(db, "bosta")["updated_at"]
    return datetime.fromisoformat(updated) if updated else None


def source_state(db: Session, source: str) -> dict:
    """How one of Shopify, Bosta and E-stebdal was last read, for Settings →
    Integrations (Batch 2.3): the same ``describe`` every Operations screen
    carries, so the two never disagree.

    ``state`` is one of fresh, stale, failed, not_connected and never;
    ``read_at`` the last clean read; ``error`` the recorded reason the latest
    read failed - already a sentence, never a traceback (``polling``).
    """
    described = describe(db, source)
    read_at = described["updated_at"]
    return {
        "state": described["state"],
        "read_at": datetime.fromisoformat(read_at) if read_at else None,
        "error": described["error"],
    }


def order_numbers_with_return_work(db: Session, order_numbers: Iterable[str]) -> set[str]:
    """Which of these orders have a return waiting for review on E-stebdal, or
    a refund still owed (a refund not yet marked paid).

    The post-delivery feedback question is not asked of such an order
    (ADR 0083). Numbers are compared without a leading ``#``, and the answer
    uses the numbers as they were given. Nothing is written or kept.
    """
    given = {str(number): str(number).lstrip("#").strip() for number in order_numbers if number}
    wanted = {bare for bare in given.values() if bare}
    if not wanted:
        return set()
    waiting = set(
        db.scalars(
            select(func.ltrim(OpsEstebdalReturn.order_number, "#")).where(
                func.ltrim(OpsEstebdalReturn.order_number, "#").in_(wanted)
            )
        )
    )
    owed = set(
        db.scalars(
            select(func.ltrim(OpsRefund.order_number, "#")).where(
                func.ltrim(OpsRefund.order_number, "#").in_(wanted),
                OpsRefund.paid_on.is_(None),
            )
        )
    )
    busy = waiting | owed
    return {number for number, bare in given.items() if bare in busy}
