# 0023. Delivery is read from Shopify, not from Bosta

**Status:** Accepted
**Date:** 2026-08-25

## Context

ADR 0012 makes an order `earned` — the only state that pays — when it is
**delivered**. Something has to say so.

Two sources could. **Bosta** is the courier: it knows whether the parcel
actually reached the customer, and it is the closer thing to truth. **Shopify**
carries a fulfilment status that is updated as the shipment moves, which HBA has
confirmed does happen.

Bosta was proposed on exactly the right instinct — it is nearer the real event,
and a courier's own record is harder to argue with than a status field written
by something else.

## Decision

**V1 reads delivery from Shopify.** Bosta is not integrated.

Shopify is already the single system this platform reads. Adding Bosta means a
second set of credentials, a second rate limit, a second reconciliation sweep,
a second thing that can be down at month end — and a new question with no
obvious answer: **what happens when the two disagree about one parcel.** That
question has to be answered by a person, every time, for as long as both sources
exist.

The safety Bosta was meant to buy is bought more cheaply. The real hazard is not
that Shopify's status is *wrong*; it is that the thing writing it **stops**, and
nothing says so. That is the same failure shape as the auto-cancel automation in
§9.1: protection living outside the codebase, which disappears silently. A second
source does not fix it — Bosta's integration can break in exactly the same way.

So instead: **the platform watches its own signal.** If orders are still
shipping and none has reached delivered for an extended period, that is an
anomaly the maintainer sees, not a month that quietly calculates to zero.

## Consequences

One integration, one source, one answer per order. No disagreement to resolve
by hand.

The delivery signal is only as good as whatever writes it into Shopify — and
that is now watched rather than assumed. A dead signal shows up as a reported
anomaly, before it shows up as a model asking why she was not paid.

**What would change this decision.** Bosta becomes worth its cost when Shopify
genuinely cannot answer a question that money depends on:

- The delivery signal proves unreliable rather than merely absent — statuses
  that arrive late enough to cross a month boundary, or that report delivered
  for parcels the customer refused.
- Manual out-of-window exchanges (§9.4) need to be visible. These are created
  directly in Bosta and never reach Shopify at all, so no Shopify field will
  ever show them. This is the strongest future case, and it is deliberately out
  of scope for V1.

## Alternatives considered

**Integrate Bosta now, use it as the source of truth.** More accurate in
principle. It costs a second integration to remove a risk that a staleness check
removes for almost nothing, and it introduces a reconciliation problem that
does not currently exist (ADR 0019).

**Read both and require agreement.** The most conservative, and the worst to
operate: every disagreement blocks a payment until a person adjudicates it, and
the disagreements would mostly be timing, not substance.

**Treat `FULFILLED` as delivered.** Simplest, and it reintroduces exactly the
loss ADR 0012 was written to prevent. For cash-on-delivery through Bosta, the
gap between *shipped* and *delivered* is where refusals live, and refusals are
material.
