"""Reading delivery, returns and refunds out of a Shopify order.

Every field here was confirmed against HBA's live shop before it was used
(Task 2a, `GET /api/operations/order-facts`). Three findings shaped what
follows, and each is worth stating because none of them was obvious.

## The order-level status cannot answer "was it delivered?"

`displayFulfillmentStatus` - which the platform already stored - has exactly two
values across 529 real orders: `fulfilled` (455) and `unfulfilled` (74). It says
the parcel *left*, nothing more.

In a sample of 50 orders it called fulfilled, only **35 had actually been
delivered**. Ten were mid-attempt, three out for delivery, one in transit, and
one had failed outright. Paying on `fulfilled` would have paid commission on
fifteen parcels the customer did not have - which is §9.1's defect rebuilt.

Delivery lives one level down, on the fulfilments.

## A refund is not always a refund

One order in the sample carried refund line items worth **E£998** and a total
refunded of **zero**. That is an exchange: E-stebdal records the returned goods,
and no money goes back because the customer swapped for something else.

Subtracting the line items would have cut E£998 from a base where the customer
paid in full and kept goods of equal value - underpaying the model on the exact
case ADR 0011's freeze exists to protect. So both numbers are stored, and Task 3
decides. **`refunded_merchandise` alone is not a reduction.**

## Return or exchange? The platform never has to decide

E-stebdal opens the same Shopify return for both - the returned product shows
"return in progress" either way - and only an exchange adds a replacement
product. So at the moment it opens, the two are genuinely indistinguishable.

**They do not need to be distinguished.** Both freeze the base, and both make
the order unresolved, so neither is paid while it is open. By the time it
resolves, one fact separates them and it is a fact rather than a judgement:

    an exchange returns goods and no money
    a return returns goods and money

`derive_refunds` reports both figures, so the question "did money actually go
back?" is answered from data. Nothing has to classify anything.

## An unrecognised status must be loud

New status values appear when a courier integration changes. An unknown one is
treated as pending - it never earns and never voids on a guess - and reported as
an anomaly, so it is noticed rather than silently parked for ever.
"""

from datetime import datetime

from app.core.signals import Anomaly, report

#: The customer has the goods. `PICKED_UP` counts: collected in person is
#: delivered, whatever the courier calls it.
DELIVERED_STATUSES = frozenset({"DELIVERED", "PICKED_UP"})

#: The parcel will not arrive. Only these two - an *attempted* delivery is not
#: a failed one, because Bosta retries and most of those parcels land.
FAILED_STATUSES = frozenset({"FAILURE", "NOT_DELIVERED"})

#: Everything still moving. Listed rather than inferred so that a status which
#: is in none of the three sets is recognised as new and reported.
#:
#: ATTEMPTED_DELIVERY, OUT_FOR_DELIVERY and NOT_DELIVERED all contain the word
#: "deliver". Matching on the substring reads a parcel still on the van as money
#: earned - see docs/limits.md. **Match the set, never the substring.**
IN_FLIGHT_STATUSES = frozenset(
    {
        "ATTEMPTED_DELIVERY",
        "CANCELED",
        "CONFIRMED",
        "DELAYED",
        "FULFILLED",
        "IN_TRANSIT",
        "LABEL_PRINTED",
        "LABEL_PURCHASED",
        "LABEL_VOIDED",
        "MARKED_AS_FULFILLED",
        "OUT_FOR_DELIVERY",
        "READY_FOR_PICKUP",
        "SUBMITTED",
    }
)

#: What an order's delivery amounts to, once every fulfilment is considered.
DELIVERED = "delivered"
FAILED = "failed"
IN_FLIGHT = "in_flight"

#: The one value that means nothing has happened.
NO_RETURN = "NO_RETURN"

#: **Something happened.** Once it has, the commission base is frozen for good
#: (ADR 0011) - including after the return finishes, because the subtotal
#: E-stebdal leaves behind is exactly the inflated number the freeze exists to
#: keep out.
RETURN_ACTIVITY_STATUSES = frozenset(
    {"REQUESTED", "IN_PROGRESS", "INSPECTION_COMPLETE", "RETURNED", "RETURN_FAILED"}
)

#: **Still being decided.** Only these block an order from earning (§9.4).
#:
#: `RETURNED` and `RETURN_FAILED` are *resolved*, and keeping them here would
#: have parked every completed return in `pending` for ever - never paid, never
#: voided, with nothing reporting it. The two sets answer different questions
#: and an earlier version of this file used one set for both.
UNRESOLVED_RETURN_STATUSES = frozenset(
    {"REQUESTED", "IN_PROGRESS", "INSPECTION_COMPLETE"}
)


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def classify_fulfilment(display_status: str | None, *, order_id: str = "") -> str:
    """One fulfilment's status, reduced to delivered, failed, or still moving."""
    name = str(display_status or "").strip().upper()
    if not name:
        return IN_FLIGHT
    if name in DELIVERED_STATUSES:
        return DELIVERED
    if name in FAILED_STATUSES:
        return FAILED
    if name in IN_FLIGHT_STATUSES:
        return IN_FLIGHT

    # Neither earn nor void on a value nobody has classified. Pending is the
    # only safe default, and this line is what stops it being a silent one.
    report(Anomaly.UNKNOWN_FULFILMENT_STATUS, status=name, order=order_id)
    return IN_FLIGHT


def derive_delivery(
    fulfilments: list[dict] | None, *, order_id: str = ""
) -> tuple[str | None, datetime | None, str | None]:
    """Reduce an order's fulfilments to one answer.

    Returns ``(delivery_state, delivered_at, raw_status)``.

    **An order is delivered only when every fulfilment is.** A split shipment
    with one parcel arrived and one still travelling is not delivered - paying
    on it would pay for goods the customer has not received. A mixed
    delivered-and-failed order stays in flight rather than resolving itself
    either way; see docs/limits.md.

    ``delivered_at`` is the **latest** delivery, because that is when the
    customer had all of it.
    """
    rows = list(fulfilments or [])
    if not rows:
        return None, None, None

    states = [
        classify_fulfilment(row.get("displayStatus"), order_id=order_id) for row in rows
    ]
    # The most advanced individual status, kept for reporting. It is not what
    # decides anything - the reduction below is.
    raw = str(rows[0].get("displayStatus") or "").strip().upper() or None
    for row, state in zip(rows, states):
        if state == DELIVERED:
            raw = str(row.get("displayStatus") or "").strip().upper() or raw
            break

    if all(state == DELIVERED for state in states):
        stamps = [_timestamp(row.get("deliveredAt")) for row in rows]
        known = [stamp for stamp in stamps if stamp is not None]
        return DELIVERED, (max(known) if known else None), raw

    if all(state == FAILED for state in states):
        return FAILED, None, raw

    return IN_FLIGHT, None, raw


def derive_return(return_status: str | None) -> tuple[str | None, bool, bool]:
    """``(status, still being decided, anything ever happened)``.

    **Two questions, not one**, and conflating them is a bug this file already
    made once:

    *Freeze the base?* Any activity, ever - and permanently. Because the frozen
    value is never re-read, the exchange inflation that made #29115 read 47%
    high cannot reach the calculation.

    *Can this order earn yet?* Only while the return is **unresolved**. Once it
    finishes, the order resolves one way or the other. Treating a completed
    return as still open leaves the order pending for ever.
    """
    name = str(return_status or "").strip().upper() or None
    if name is None:
        return None, False, False
    return name, name in UNRESOLVED_RETURN_STATUSES, name in RETURN_ACTIVITY_STATUSES


def _amount(block: dict | None) -> str | None:
    return ((block or {}).get("shopMoney") or {}).get("amount")


def _refund_rows(order: dict) -> list[dict]:
    """Tolerate both shapes Shopify uses for `refunds` across API versions."""
    refunds = order.get("refunds")
    if isinstance(refunds, dict):
        return list(refunds.get("nodes") or [])
    return list(refunds or [])


def derive_refunds(order: dict) -> tuple[int, int]:
    """``(total refunded, refunded merchandise)`` in piastres.

    **Both, deliberately.** They disagree in the case that matters: an exchange
    shows merchandise returned with nothing refunded, and treating that as a
    reduction underpays the model on goods they sold and the customer kept the
    value of. Task 3 decides what to do with the pair; this only reports them.
    """
    from app.services.shopify.normalise import money_to_piastres

    total = 0
    merchandise = 0
    for refund in _refund_rows(order):
        total += money_to_piastres(_amount(refund.get("totalRefundedSet")))
        line_items = (refund.get("refundLineItems") or {}).get("nodes") or []
        for line in line_items:
            merchandise += money_to_piastres(_amount(line.get("subtotalSet")))
    return total, merchandise
