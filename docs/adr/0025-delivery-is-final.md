# 0025. Delivery is final: V1 ignores what happens afterwards

**Status:** Accepted
**Date:** 2026-08-26
**Supersedes the return-handling parts of:** 0011, 0012, 0024

## Context

ADR 0011 froze the commission base when a return or exchange began, and ADR 0024
finalised an order on an exchange. What remained was to reduce the base for a
**genuine return** while leaving an **exchange** alone — and those look identical
in Shopify, because E-stebdal opens the same return object for both.

Three attempts to close that gap each failed on the data:

**Refund amounts do not say what HBA refunded.** Return shipping is deducted (E£120
today, and it moves), exchanges are sometimes settled outside E-stebdal leaving the
order still claiming a refund is owed, and sometimes nothing is recorded on Shopify
at all.

**Shopify will not distinguish them.** `Order.returns` is refused: `read_returns` is
not granted, and getting it costs a scope change and an app release.

**And then the shape of an exchange turned out to be unbounded.** An exchange is not
*X items out, X items back*. A customer may return three items and take one, or
return one and take three. Detecting "a replacement appeared" would have identified
*that* an exchange happened while saying nothing about what the customer ended up
holding, and every rule built on it would have needed a further rule for the
mismatch.

## Decision

**An order is finished with when it is delivered.** Nothing that happens afterwards
changes what it is worth.

| Outcome | State |
|---|---|
| Delivered | `earned`, and final |
| Delivery failed | `void`, and final |
| Anything in between | `pending` |

Returns, exchanges, refunds and order edits **after delivery are ignored**. Not
mis-handled, not deferred to a person — read, stored, and deliberately not acted on.

Before delivery nothing changes: an order edited pre-shipment still reflects the
edit, a cancellation still voids it.

## Why this is the right trade, not a retreat

**The inputs cannot support a better answer.** Every mechanism above would have fed
a reduction computed from figures HBA has said are unreliable and sometimes absent.
Building precision on top of an input known to be wrong is the expensive way to be
confidently incorrect (ADR 0019).

**HBA had already accepted most of this exposure.** ADR 0012 absorbs any return
arriving after a month is approved, with no clawback, because prompt predictable
payment to twenty people the business knows personally is worth more than perfect
reversal. This extends the same principle from *after approval* to *after
delivery* — a difference of a few weeks, on the same reasoning.

**The exposure is small and measured.** Across the 537 orders indexed on
26 August 2026, **six show money having gone back**: one `refunded` and five
`partially_refunded`. That is **1.1% of orders**, and only a fraction of any one
of them is commission. It is larger than the ~E£90/year of rounding accepted in
ADR 0004 and the same kind of decision.

**It is reversible.** `order_index` still stores `return_status`, `return_activity`,
`refunded_total_piastres` and `refunded_merchandise_piastres` on every order. The
facts keep arriving; the engine simply does not read them. A later phase can measure
exactly what this cost over a real year and decide again with evidence rather than
estimates.

## Consequences

**A large amount of machinery is deleted**, and with it the failures it could have
had: the return-decision hold, the `needs_review` column, the freeze's dependence on
having seen an order before its exchange opened, and the whole exchange-versus-return
question.

**`read_returns` stops being needed.** It was the last thing blocking Phase 4.

**A wholly returned order still pays.** A customer who receives E£5,000 of goods and
sends all of it back leaves the model paid on a sale that reversed. This is the case
that will eventually be noticed, and it is accepted knowingly — HBA was asked
specifically about it and chose to keep the rule whole rather than carve out an
exception. See *Alternatives*.

**A model's dashboard will show a returned order as earned.** That needs saying in
the plain-language policy text (§16), not left for them to work out.

**The base is simply what they sold.** No freezing to explain, no timestamp to
interpret, no state that can be reached two different ways.

## Alternatives considered

**Void an order that was fully refunded, and ignore everything else.** The one case
that is unambiguous — `financial_status = 'refunded'` means every piastre went back,
which no exchange produces. One boolean, no line items, no scope, and it removes the
worst outcome above.

**Put to HBA on 26 August 2026 and declined for V1**, on the grounds that *nothing*
related to an edit after delivery belongs in this version — a full refund included.
That is the more consistent rule: one exception invites the next, and each one
carries back a little of the machinery this ADR removed.

Recorded in §3 of the specification as the **first** thing to add whenever reversal
is revisited, because it is the cheapest and removes the most noticeable case.

**Grant `read_returns` and detect the replacement.** Identifies that an exchange
happened; says nothing about what the customer kept when the item counts differ.
Would have needed line-item storage and a further rule for every mismatch, all of it
resting on refund figures already known to be unreliable.

**Hold every resolved return for a person.** What Phase 4 shipped. Correct, and it
means roughly one order in eight eventually needs a human decision, every month, for
a 1.1% effect. That is a standing operational cost for a rounding-sized problem.

**Wait for the return window before earning.** Rejected in ADR 0012, and rejected
again: it delays every affiliate's pay by ten days.
