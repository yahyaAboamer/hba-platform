"""Asking Shopify what it will actually tell us about delivery and returns.

Phase 4 pays a model when her order is **delivered** (ADR 0012), reads delivery
from Shopify rather than from Bosta (ADR 0023), and freezes the commission base
the moment a return or exchange begins (ADR 0011). All three depend on fields
this platform has never requested.

Guessing at them is not free. GraphQL rejects an entire document when one field
is wrong, so adding a mistaken field to the query that indexes every order would
stop order ingestion outright - loudly, but stopped. This module asks first, on
its own query, and leaves the working one alone until the answer is known.

**Several shapes are tried per fact.** Shopify moves fields between list and
connection form across API versions, so ``refunds { ... }`` and
``refunds(first: 10) { ... }`` are both plausible and only one compiles. Trying
each and reporting the winner turns a round-trip of guessing into one answer.

Nothing here writes. It reads a sample and counts what came back.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from app.services.shopify.client import ShopifyClient, ShopifyError
from app.services.shopify.normalise import _timestamp, money_to_piastres

#: Enough orders to see a pattern, few enough to stay well inside Shopify's
#: cost-based limit with nested fulfilments and refunds on every node.
DEFAULT_SAMPLE = 50
MAX_SAMPLE = 250

#: Fulfilment display statuses meaning the customer actually has the goods.
#: PICKED_UP counts: collected in person is delivered, whatever the courier
#: calls it.
DELIVERED_STATUSES = frozenset({"DELIVERED", "PICKED_UP"})

#: Statuses that contain the word "deliver" and are **not** deliveries. Listed
#: explicitly because the obvious substring test reads all three as success -
#: a parcel still on the van, a failed attempt, and an outright refusal would
#: each have been reported as money earned. Found by a test, not in production.
NOT_DELIVERIES = frozenset(
    {"OUT_FOR_DELIVERY", "ATTEMPTED_DELIVERY", "NOT_DELIVERED", "FAILURE"}
)


@dataclass(frozen=True)
class FactProbe:
    """One fact, and the field shapes that might carry it."""

    name: str

    #: What this is actually trying to find out, in words a person can check.
    question: str

    #: Tried in order. The first that compiles wins.
    candidates: tuple[str, ...]

    #: Shopify order-search filter narrowing the sample to orders that could
    #: plausibly show the fact. Asking whether delivery is ever reported is
    #: meaningless over orders that have not shipped yet.
    search: str | None = None


@dataclass
class ProbeResult:
    name: str
    question: str
    available: bool
    field_expression: str | None = None
    sampled: int = 0
    rejected: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    error: str | None = None


PROBES: tuple[FactProbe, ...] = (
    FactProbe(
        name="delivery",
        question="Does Shopify report that a parcel was delivered, and what does it call it?",
        # Only orders that have shipped. A sample of orders placed yesterday
        # would show no deliveries and prove nothing.
        search="fulfillment_status:fulfilled",
        candidates=(
            "fulfillments(first: 10) { displayStatus status deliveredAt inTransitAt updatedAt }",
            "fulfillments(first: 10) { displayStatus status updatedAt }",
            "fulfillments { displayStatus status deliveredAt inTransitAt updatedAt }",
            "fulfillments { displayStatus }",
        ),
    ),
    FactProbe(
        name="return_status",
        question="Does Shopify say whether a return or exchange is open on an order?",
        candidates=("returnStatus",),
    ),
    FactProbe(
        name="refund_total",
        question="Can we see the total refunded on an order?",
        candidates=(
            "refunds(first: 10) { id createdAt totalRefundedSet { shopMoney { amount currencyCode } } }",
            "refunds { id createdAt totalRefundedSet { shopMoney { amount currencyCode } } }",
        ),
    ),
    FactProbe(
        name="refund_merchandise",
        question=(
            "Can we separate refunded merchandise from refunded shipping and tax? "
            "Section 9.3 reduces the base by merchandise only."
        ),
        candidates=(
            "refunds(first: 10) { id refundLineItems(first: 50) { nodes { subtotalSet { shopMoney { amount currencyCode } } } } }",
            "refunds { id refundLineItems(first: 50) { nodes { subtotalSet { shopMoney { amount currencyCode } } } } }",
        ),
    ),
)


def _document(fields: str, *, filtered: bool) -> str:
    search_arg = ", query: $query" if filtered else ""
    search_var = ", $query: String" if filtered else ""
    return f"""
query FactProbe($first: Int!{search_var}) {{
  orders(first: $first, sortKey: UPDATED_AT, reverse: true{search_arg}) {{
    nodes {{
      legacyResourceId
      {fields}
    }}
  }}
}}
"""


# ── Counting what came back ────────────────────────────────────────────────────


def _summarise_delivery(nodes: list[dict]) -> dict:
    statuses: Counter = Counter()
    with_fulfilment = 0
    with_delivered_timestamp = 0

    for node in nodes:
        fulfilments = node.get("fulfillments") or []
        if fulfilments:
            with_fulfilment += 1
        for fulfilment in fulfilments:
            display = fulfilment.get("displayStatus")
            statuses[str(display).upper() if display else "(null)"] += 1
            if _timestamp(fulfilment.get("deliveredAt")):
                with_delivered_timestamp += 1

    return {
        "orders_with_a_fulfilment": with_fulfilment,
        "fulfilment_display_statuses": dict(statuses.most_common()),
        "fulfilments_carrying_a_delivered_timestamp": with_delivered_timestamp,
    }


def _summarise_return_status(nodes: list[dict]) -> dict:
    statuses: Counter = Counter()
    for node in nodes:
        value = node.get("returnStatus")
        statuses[str(value).upper() if value else "(null)"] += 1
    return {"return_statuses": dict(statuses.most_common())}


def _refund_list(node: dict) -> list[dict]:
    """Tolerate either shape - a plain list, or a connection with nodes."""
    refunds = node.get("refunds")
    if isinstance(refunds, dict):
        return list(refunds.get("nodes") or [])
    return list(refunds or [])


def _summarise_refund_total(nodes: list[dict]) -> dict:
    orders_with_refunds = 0
    total_piastres = 0
    for node in nodes:
        refunds = _refund_list(node)
        if refunds:
            orders_with_refunds += 1
        for refund in refunds:
            money = ((refund.get("totalRefundedSet") or {}).get("shopMoney")) or {}
            total_piastres += money_to_piastres(money.get("amount"))
    return {
        "orders_with_at_least_one_refund": orders_with_refunds,
        "total_refunded_piastres_in_sample": total_piastres,
    }


def _summarise_refund_merchandise(nodes: list[dict]) -> dict:
    orders_with_line_items = 0
    merchandise_piastres = 0
    for node in nodes:
        found = False
        for refund in _refund_list(node):
            line_items = (refund.get("refundLineItems") or {}).get("nodes") or []
            for line in line_items:
                found = True
                money = ((line.get("subtotalSet") or {}).get("shopMoney")) or {}
                merchandise_piastres += money_to_piastres(money.get("amount"))
        if found:
            orders_with_line_items += 1
    return {
        "orders_with_refunded_line_items": orders_with_line_items,
        "refunded_merchandise_piastres_in_sample": merchandise_piastres,
    }


SUMMARISERS: dict[str, Callable[[list[dict]], dict]] = {
    "delivery": _summarise_delivery,
    "return_status": _summarise_return_status,
    "refund_total": _summarise_refund_total,
    "refund_merchandise": _summarise_refund_merchandise,
}


# ── Running the probes ─────────────────────────────────────────────────────────


def run_probe(
    client: ShopifyClient, probe: FactProbe, *, sample_size: int
) -> ProbeResult:
    """Try each candidate shape until one compiles."""
    result = ProbeResult(name=probe.name, question=probe.question, available=False)

    for expression in probe.candidates:
        variables: dict = {"first": sample_size}
        if probe.search:
            variables["query"] = probe.search

        try:
            data = client.execute(
                _document(expression, filtered=bool(probe.search)), variables
            )
        except ShopifyError as exc:
            # Every rejection is kept, not just the last. If all four shapes
            # fail, the four messages together say why far better than one.
            result.rejected.append({"fields": expression, "shopify_said": str(exc)})
            continue

        nodes = list(((data.get("orders") or {}).get("nodes")) or [])
        result.available = True
        result.field_expression = expression
        result.sampled = len(nodes)
        result.summary = SUMMARISERS[probe.name](nodes)
        return result

    result.error = "Shopify rejected every candidate shape for this fact"
    return result


def delivery_verdict(results: list[ProbeResult]) -> dict:
    """The answer the maintainer actually came for.

    Three outcomes, and they need different actions:

    ``present``  - delivery is reported. Task 4 proceeds as ADR 0012 specifies.
    ``absent``   - the field exists but no shipped order has ever reached it.
                   Nobody would ever be paid. **Stop.**
    ``unreadable`` - Shopify refused the fields. Nothing can be concluded.
    """
    delivery = next((item for item in results if item.name == "delivery"), None)

    if delivery is None or not delivery.available:
        return {
            "signal": "unreadable",
            "explanation": (
                "Shopify would not return fulfilment detail, so whether delivery "
                "is reported is still unknown. Read the rejected shapes below - "
                "the message usually names the field or the missing scope."
            ),
        }

    if not delivery.sampled:
        return {
            "signal": "unreadable",
            "explanation": (
                "No fulfilled orders came back, so there is nothing to judge "
                "from. This is not evidence that delivery is unreported."
            ),
        }

    statuses = delivery.summary.get("fulfilment_display_statuses") or {}
    delivered = sum(
        count for name, count in statuses.items() if name in DELIVERED_STATUSES
    )
    timestamps = delivery.summary.get("fulfilments_carrying_a_delivered_timestamp", 0)

    if delivered or timestamps:
        return {
            "signal": "present",
            "explanation": (
                f"{delivered} fulfilment(s) in a sample of {delivery.sampled} shipped "
                f"orders report delivery, and {timestamps} carry a delivered "
                "timestamp. Earning on delivery is implementable as ADR 0012 "
                "specifies."
            ),
        }

    return {
        "signal": "absent",
        "explanation": (
            f"Not one of {delivery.sampled} shipped orders has ever reached a "
            "delivered status. If this is accurate, every order would stay "
            "pending for ever and no affiliate would ever be paid. Do not treat "
            "FULFILLED as delivered without deciding to accept the refusal "
            "losses that ADR 0012 exists to avoid - that is a business decision."
        ),
    }


def probe_order_facts(
    client: ShopifyClient, *, sample_size: int = DEFAULT_SAMPLE
) -> dict:
    """Ask Shopify every open question this phase depends on, and report."""
    size = max(1, min(int(sample_size), MAX_SAMPLE))
    results = [run_probe(client, probe, sample_size=size) for probe in PROBES]

    return {
        "sample_size": size,
        "delivery": delivery_verdict(results),
        "facts": [
            {
                "name": item.name,
                "question": item.question,
                "available": item.available,
                "fields_that_worked": item.field_expression,
                "orders_sampled": item.sampled,
                "summary": item.summary,
                "rejected": item.rejected,
                "error": item.error,
            }
            for item in results
        ],
    }
