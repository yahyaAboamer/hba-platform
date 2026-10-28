"""The silent run, checked against n8n (ADR 0059; the plan's phase 2).

While the confirmation engine only records what it *would* send, n8n is
still the one sending. This compares the two: the orders n8n messaged, read
from its own record, against the orders the platform would have messaged.
Phase 2 is done when they agree for seven days, or every difference has a
reason written down.

Run by hand, from the server, with n8n's order ids on standard input::

    python -m app.modules.inbox.services.shadow --since 2026-10-12 < sent-order-ids.txt

It prints counts and order numbers. **No name, phone or message** - an order
number is all a difference needs to be looked up.
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.inbox.models import OrderConfirmation

#: The platform has no record of the order at all: never indexed in time, or
#: older than the engine looks.
NOT_SEEN = "not_seen"


def compare(
    db: Session,
    sent_order_ids: Iterable[str],
    *,
    since: datetime,
    until: datetime | None = None,
) -> dict:
    """What n8n sent against what the platform would have, for orders placed
    in the window.

    ``sent_order_ids`` is n8n's record for the same window. An order n8n sent
    that we would not is the dangerous direction - at the switch it would get
    no message - so each carries the state we gave it and why.
    """
    query = select(OrderConfirmation).where(OrderConfirmation.placed_at >= since)
    if until is not None:
        query = query.where(OrderConfirmation.placed_at < until)
    ours = {row.shopify_order_id: row for row in db.scalars(query)}

    sent = {str(order_id).strip() for order_id in sent_order_ids if str(order_id).strip()}
    would = {order_id for order_id, row in ours.items() if row.state == "would_send"}

    def theirs_only(order_id: str) -> dict:
        row = ours.get(order_id)
        return {
            "order_id": order_id,
            "order": row.order_name if row else None,
            "ours": row.state if row else NOT_SEEN,
            "why": row.last_error if row else None,
        }

    return {
        "since": since.isoformat(),
        "until": until.isoformat() if until else None,
        "n8n_sent": len(sent),
        "we_would_send": len(would),
        "agree": len(sent & would),
        "only_n8n": sorted((theirs_only(order_id) for order_id in sent - would), key=lambda d: d["order_id"]),
        "only_us": sorted(
            ({"order_id": order_id, "order": ours[order_id].order_name} for order_id in would - sent),
            key=lambda d: d["order_id"],
        ),
        "our_states": dict(sorted(Counter(row.state for row in ours.values()).items())),
    }


def _day(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--since", required=True, type=_day, help="orders placed from, e.g. 2026-10-12")
    parser.add_argument("--until", type=_day, help="and before, e.g. 2026-10-19")
    arguments = parser.parse_args(argv)

    from app.db import SessionLocal

    with SessionLocal() as db:
        result = compare(db, sys.stdin.read().split(), since=arguments.since, until=arguments.until)
    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    # Disagreement is the thing being looked for; say so in the exit code.
    return 1 if result["only_n8n"] or result["only_us"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
