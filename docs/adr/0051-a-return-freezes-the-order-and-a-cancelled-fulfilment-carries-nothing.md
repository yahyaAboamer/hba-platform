# 0051 — A return freezes the order, and a cancelled fulfilment carries nothing

**Status:** accepted — owner, 28 September 2026
**Date:** 2026-09-28
**Amends:** 0025 (delivery is final) — how it is *applied*, not what it says
**Related:** `app/services/shopify/fulfilment.py` (`derive_delivery`,
`paid_by_delivery`); `app/services/shopify/queries.py` (`ORDER_FIELDS`,
`ORDER_LINE_ITEMS`); `app/services/commission/attribute.py`,
`app/services/commission/base.py`; `app/services/shopify/catalogue.py`
(`after_delivery`); `app/services/stale.py`; `app/services/reconcile.py`
(`RESYNC_IN_FLIGHT`); migration `f4a2b8d10005`

## The situation

ADR 0025 says an order is finished with when it is delivered. The code
enforced that by locking an order **the moment the platform saw it
delivered**. Anything the platform first saw *after* something else had
happened to it never got locked, and the per-fulfilment rule — *delivered only
when every fulfilment is delivered* — then read the later events as the parcel
still travelling.

A read-only audit of every order staging held as in flight (1,114 orders,
28 September, reading each fulfilment from HBA's real shop) found the cases:

| Pattern | Orders | What happened |
|---|---|---|
| Delivered, then one or more fulfilments created **after** delivery, all shipping items the order had not shipped before | 565 | E-stebdal exchanges: the replacement is a new fulfilment, marked *fulfilled* by hand, that no courier ever reports on |
| A **cancelled** fulfilment, then a re-sent one that was delivered | 108 | Fulfilled, cancelled, fulfilled again (#22369) |
| A cancelled fulfilment, then a failed one | 12 | Never delivered (#22408) |
| Only cancelled fulfilments | 60 | Cancelled orders; all already void in commission |

Two facts decided the shape of the rule:

- **Every fulfilment created after delivery belongs to an order with a
  return, and every one ships new items.** Zero cases in the shop of a late
  split shipment or a re-send of the same goods after delivery.
- **Shopify's order totals do not say what the customer paid at delivery.**
  Across 246 delivered orders with a return: the *original* total matched the
  payments 182 times (an order edited before it shipped breaks it), the
  *total before returns* 75 times (exchanges inflate it), the current total 32.
  **The payments themselves** — successful sales and captures up to the
  delivery — existed on every one, and none arrived more than twelve hours
  after it.

## The rules

**Rule 1 — a return or exchange freezes the order** (owner, 28 September):

> The moment an order gets its first return or exchange request it is frozen
> exactly as it was just before: its delivery state and date, its items, and
> its money. Everything afterwards — returned items, exchange items, new
> fulfilments, price edits, extra payments, return shipping, refunds — is
> recorded and changes nothing the platform shows or pays.

A return can only follow delivery, so the frozen picture is the delivered one.
When the platform first sees an order after its request, the picture is
**rebuilt from Shopify's own history**, so it is the same whenever it was read:

- **Delivered** — judged only on the fulfilments created up to the first
  delivery. On an order with a return, later ones are ignored.
- **Items** — the products those fulfilments carried. A line only a later
  fulfilment carried (the exchange item) is marked `after_delivery` and left
  out of the order's products, her best sellers and the wardrobe.
- **Money** — what the customer actually paid up to delivery (successful
  sales and captures, less refunds, up to twelve hours after the first
  delivery), less shipping and tax. ADR 0011's *cash kept*, read from the
  payments rather than from a total Shopify recomputes. Used only for an order
  with a return that was not already final; an order the platform saw
  delivered before its return keeps the figure it was locked at.

**Rule 2 — a cancelled fulfilment carries nothing.** It is ignored when
deciding delivered or failed. An order whose only fulfilments were cancelled
is *not shipped* (no delivery state), which leaves its commission to the
cancellation rules that already void it.

## What is deliberately not decided here

- **Orders already earned with a post-return base.** An order imported after
  its return was locked at Shopify's figure at the time of import. Rule 1 says
  its base should be the cash at delivery. Earned is final (0025), so nothing
  rewrites them silently; the count and the difference are reported to the
  owner as a separate decision.
- **Fulfilled with no courier news.** Orders with no tracking number, or with
  a courier other than Bosta (Aramex, DHL), are never reported delivered to
  Shopify. They stay pending — counted and paid under ADR 0040 — and appear on
  a staff list after fourteen days so somebody marks them delivered or
  cancelled **in Shopify**, which remains the only source of delivery (0023).
  The platform does not guess.
- **A failed attempt plus a second fulfilment with no news** stays pending
  under the ordinary rule.

## Why the audit's facts are kept, not just the answer

`order_index.fulfilments` now stores each fulfilment's own status, created and
delivered times and courier. The question *why is this order in flight?* was a
day's investigation against Shopify; it is now one read.
