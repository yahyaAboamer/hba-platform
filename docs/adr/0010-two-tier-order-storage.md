# 0010. Every order is indexed; only attributed ones are stored in full

**Status:** Accepted
**Date:** 2026-08-22

## Context

The old dashboard stored every Shopify order in full, including the large
majority that used no affiliate code. Its Railway volume reached 431 MB of 500
MB, and the platform's new database is a free tier of similar size.

The obvious correction - store only orders that used a registered code -
introduces a worse problem. It makes "was this code used before it was
registered?" unanswerable without re-scanning all of Shopify, and that question
comes up every time an affiliate is onboarded with a code that was already live.

## Decision

Two tiers.

`order_index` holds **every** order in about 150 bytes: identifiers, date,
business month, the discount codes used, and totals. `attributed_order` will
hold full financial detail for **attributed** orders only.

At roughly 30,000 orders a year with about 15% affiliate-attributed, that is
around 11 MB a year.

## Consequences

Registering a code becomes a local query followed by a small targeted fetch,
rather than a full re-scan of Shopify.

An unregistered-code alert becomes possible: a code live on real orders and
belonging to no affiliate is precisely the case where a model's sales vanish
silently.

Programme-level reporting becomes possible - what share of orders come through
affiliates - which is a genuine business question.

The cost is a second table and the discipline of keeping the index row small.
Adding fields to it is cheap individually and expensive in aggregate.

## Alternatives considered

**Store everything in full.** What the old system did, and what filled its disk.

**Store only attributed orders.** Smaller still, and it discards the information
that makes onboarding and alerting work.
