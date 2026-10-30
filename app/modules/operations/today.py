"""What Operations says is waiting, for Today (Phase 2, batch 2.2).

Only for somebody holding ``order_ops.view``. Every figure comes from what the
Operations tabs themselves read: each source's state from ``freshness``, and
the confirmed orders that never reached Bosta from the Shopify tab's own card.
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.businesstime import at_words, clock_words
from app.core.permissions import Permission
from app.modules.operations.services import shopify
from app.modules.operations.services.freshness import SOURCES, State, describe, has_numbers
from app.shared.services.today import SINCE, ELAPSED, Item, Look

DEPARTMENT = "operations"

#: A confirmed order not on Bosta a day after it was placed is late.
NOT_SENT_LATE_AFTER = timedelta(hours=24)


def _at(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _failed_source(source: dict, now: datetime) -> Item:
    label = source["label"]
    updated = _at(source["updated_at"])
    checked = _at(source["checked_at"])
    what = (
        f"{label} has not been read since {clock_words(updated, now)}"
        if updated
        else f"{label} could not be read"
    )
    detail = (
        f"Its last try failed {at_words(checked, now)}. Its screen shows the last good read."
        if checked
        else "Its last try failed. Its screen shows the last good read."
    )
    return Item(
        key=f"operations.source_failed.{source['source']}",
        department=DEPARTMENT,
        what=what,
        detail=detail,
        go_label=f"Open {label}",
        go_to=f"/operations/{source['source']}",
        broken=True,
        late=True,
        since=updated or checked,
        when=ELAPSED,
    )


def look(db: Session, permissions: frozenset[str], now: datetime) -> Look:
    """Operations' items, and the sidebar's failed sources."""
    found = Look()
    if Permission.ORDER_OPS_VIEW not in permissions:
        return found

    described = {source: describe(db, source, now) for source in SOURCES}
    for source in SOURCES:
        state = described[source]
        if state["state"] == State.FAILED:
            found.failures[source] = state["updated_at"]
            found.items.append(_failed_source(state, now))

    # The Shopify tab's own card, only while the tab has numbers to show.
    if has_numbers(described["shopify"]):
        card = next(
            card for card in shopify.tab(db, None, now)["cards"] if card["key"] == "bosta_sync_failed"
        )
        if card["count"]:
            oldest = min(datetime.fromisoformat(order["placed_at"]) for order in card["orders"])
            n = card["count"]
            found.items.append(
                Item(
                    key="operations.bosta_sync_failed",
                    department=DEPARTMENT,
                    what=(
                        "1 confirmed order never reached Bosta"
                        if n == 1
                        else f"{n} confirmed orders never reached Bosta"
                    ),
                    detail="They will not be picked up until they are sent again",
                    go_label="Open",
                    # The tab opens a card by a click, not by its address, so
                    # this opens the tab (no new screen behaviour in 2.2).
                    go_to="/operations/shopify",
                    late=now - oldest > NOT_SENT_LATE_AFTER,
                    since=oldest,
                    when=SINCE,
                )
            )
    return found
