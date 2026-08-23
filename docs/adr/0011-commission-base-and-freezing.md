# 0011. Commission base is cash kept, frozen when a return or exchange begins

**Status:** Accepted
**Date:** 2026-08-22

## Context

HBA uses E-stebdal for returns and exchanges. When a customer requests an
exchange, E-stebdal edits the order **inside Shopify**: it adds the replacement
item and marks the returned one, without removing either until an administrator
closes the return by hand.

Order #29115 is the worked example. The customer paid **E£1,157**, of which
E£95 was shipping. Mid-exchange, Shopify reports:

| | |
|---|---|
| Subtotal | **3 items, E£1,675** |
| Actually collected | **E£1,157** |
| Financial status | `partially_paid` |

The old dashboard read that subtotal and calculated commission on roughly
E£1,557 instead of E£1,062 - about **47% too much on a single order**. It also
handled `partially_paid` nowhere, so a mid-exchange order passed through as
normal.

## Decision

**Commission base = total the customer pays, minus shipping, minus tax**, after
all discounts. For #29115 that is `1,157 - 95 = E£1,062`.

The base updates while the order is pending with no return or exchange activity,
so genuine pre-shipment edits are reflected, and **freezes permanently the
moment any return or exchange begins**. Because the frozen value is never
re-read from Shopify, the exchange inflation cannot reach the calculation.

Refunds and exchanges are treated differently, which an earlier draft
conflated:

| Event | Effect on base |
|---|---|
| Exchange with no net refund | **Unchanged** - this is what freezing protects |
| Partial refund, month still draft | **Reduced** by the refunded merchandise |
| Partial refund after approval | **Absorbed** by HBA (see 0012) |
| Full refund or cancellation | Order **voids** |

## Consequences

Freezing defeats a specific Shopify artefact. It was never meant to pay
commission on merchandise the customer returned and was refunded for - an
earlier draft of this rule did exactly that, and an external review caught it.

Attribution tolerates any number of non-affiliate codes on the same order. The
base is what the customer actually paid, so additional discounts reduce it
naturally without special handling.

## Alternatives considered

**Read Shopify's current subtotal.** What the old system did.

**Recompute from the final settled state.** More accurate in principle, and it
depends on an administrator remembering to close each return in E-stebdal -
which is manual, and therefore sometimes late by weeks.
