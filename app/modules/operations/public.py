"""What other departments may use from Operations (ADR 0065).

The only part of this department another one may import: the import check
(pyproject.toml, `[tool.importlinter]`) refuses its api, models and services.
Empty on the day of the move; the crossings that existed then are listed in
that check, and each one that is untangled comes through here.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.operations.services.bosta import order_numbers_on_bosta
from app.modules.operations.services.freshness import describe
from app.modules.operations.today import look as today_look

__all__ = ["bosta_read_at", "order_numbers_on_bosta", "source_state", "today_look"]


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
