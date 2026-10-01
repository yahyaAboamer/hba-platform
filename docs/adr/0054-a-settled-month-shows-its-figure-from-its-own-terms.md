# 0054. A settled month shows its figure from its own terms

**Status:** Accepted
**Date:** 2026-10-01
**Amends:** [0036](0036-pre-go-live-months-are-ordinary-months.md), in what a
settled month shows before it is approved

## Context

ADR 0036 made months before go-live ordinary months: terms entered by hand,
calculated by the same `calculate_month`, approved and frozen, and kept off the
payments desk because their balance is structurally zero. It assumed they
would be **approved** - and until a month was approved, the model's portal fell
back to ADR 0014's shape: her sales, a dash where the figure goes, and
*"Earnings are not available for this month yet."*

Approving those months is locked behind `HISTORICAL_FINALISATION_UNLOCKED`, and
`GO_LIVE_MONTH` became `2026-10` on 30 September: every month before October
is settled directly by HBA and the platform never pays it. So in practice the
fallback was the only thing a model ever saw for those months. The owner's
staging test with Sara (1 October 2026) showed it: a month of EGP 58,399.51 in
sales with no figure, no average order, and a "yet" that would never come true.

The owner, 1 October 2026: *"for a model, it should be shown as a normal month,
just like any month after the go live … the only thing that differs it is the
word settled on the month selector and the payments."* And: he records each
model's agreed terms for every month - and the target outcome for a guaranteed
minimum - **before she is approved**, for every arrangement type.

## Decision

1. **A settled month with terms recorded for it is calculated and shown like
   any other month**, without being approved: the figure, the breakdown, the
   salary/commission split, the average order. It is the live calculation from
   that month's own terms, exactly as an open month's is.
2. Its state stays `historical` so the screen can say the two things that
   differ: the pill reads **Settled**, and the payment line reads **Paid
   directly by HBA**. Nothing waits on anybody for it (`waiting_on` is empty):
   no approval or check is ever going to happen.
3. **It is still never owed.** `balance_for` keeps it off the payments desk and
   out of her payments list exactly as before; a figure on her screen is not an
   obligation.
4. A settled month with **no** terms recorded keeps the fallback: her sales as
   the big number, labelled *Sales*, with *"HBA settled this month with you
   directly, so only your sales are shown here."* - and no "yet". The platform
   still does not guess a rate.

## Consequences

- The figure is what the platform calculates from the recorded terms, not a
  record of what HBA actually transferred. ADR 0036 already accepted that the
  two may differ; correcting a month's terms on the pay-history grid corrects
  the figure.
- Her year chart and year total now include settled months that have terms,
  because they read the same `my_month`.
- A settled month's figure can move if its orders change (a late delivery
  failure), as an open month's can. Approving it under ADR 0036 would freeze
  it; that path is unchanged and still locked.
