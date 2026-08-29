# 0029 — A late order is paid at its own month's rate, on top of any guarantee

**Status:** accepted
**Date:** 2026-08-27
**Implements:** spec §11.4 (carry-forward)
**Related:** [0003](0003-multiply-first-divide-once.md), [0004](0004-round-once-at-the-end.md), §9.5

## The situation

An order placed 29 August, still travelling when August payroll runs on
5 September, delivered on 8 September. §11.4 calls this the common path rather
than an edge case: Egyptian cash-on-delivery routinely straddles month end, and
118 of 537 live orders are undelivered at any moment.

August is agreed and settled. The order cannot alter it — §11.4 is explicit
that orders settling after approval never change the approved month. So it is
paid by the next payroll that runs.

Until now it was **not paid at all**. `carried_into` found it,
`carry_forward_summary` printed it on September's row, and `calculate_month`
selected `business_month == month` and never added it to anything. Recorded in
`docs/limits.md`.

Three questions had to be answered before it could be paid. All three are
business decisions, and all three were put to HBA.

## Decision 1 — the rate is the source month's

The order is an August sale. §9.5 already holds that a rate change in June must
not rewrite what April was worth, and that reasoning does not weaken because
September happens to be the month writing the cheque.

So `carried_forward` resolves terms **per source month**, and a payroll can
therefore carry several rates at once: August's orders at August's rate,
July's at July's.

The consequence is that `calculate_month` no longer has one rate. Commission is
still exact and still divided once per rate group, and the **total** is rounded
once at the end (ADR 0003, ADR 0004). A carried line never introduces a
rounding step of its own.

## Decision 2 — carried money sits on top of a guarantee, never inside it

A base guarantee is `max(commission, base)` — a floor under **this month's**
work. An order from a different month is not this month's work, so it is added
after the comparison:

    payout = max(own_commission, base_if_applicable) + carried_commission

**The alternative was considered and rejected.** Including carried money in the
comparison would let a late August order be swallowed by a September guarantee
they were going to receive anyway: their figure would not move, and the order would
be paid nothing while appearing on their row as paid.

**The accepted cost, stated plainly.** If August itself paid at the guarantee,
its commission was already below the floor, and a late August order strictly
should only matter if it lifted August's commission *over* that floor. It does
not: they receive its commission regardless. This is a small overpayment in the
model's favour, and it was chosen over the correct-but-unexplainable
alternative — recomputing a closed month and paying the difference — because
§16 requires a policy a model can read and check against their own arithmetic.
*"Any order that arrives after your month closes is paid at that month's rate
in your next payment"* is a sentence they can verify. *"Your August was
recomputed and the difference against your floor..."* is not.

Listed in the deliberate-exposure table.

## Decision 3 — the paying month settles it

`approve_month` marks carried orders settled by **its** snapshot. Nothing else
in the schema records that an order has been paid, so without this the same
order is offered to October, November, and every month after.

This forced a second rule, and it is the sharper one:

> An order counts toward a month unless a **different** month's payroll paid
> it.

Both halves have a failure behind them, and both are tested:

- *Unless another month paid it* — once September has paid a late August order,
  reopening August must not offer that money again. Without this, August
  recalculates to include an order September already settled, and re-approving
  it agrees the same commission twice. This was reproduced before it was fixed.
- *A different month, not any month* — an approved month's own orders are
  settled by its own snapshot and must keep counting, or every month would
  recalculate to zero the instant it was agreed.

## What reopening now does

| Where the carried order sits | On reopening its own month |
|---|---|
| Next month still `draft` | **Comes back.** Un-approving August stops it being *carried* at all, and it returns to the month it belongs to. |
| Next month already `approved` | **Stays there.** That month is settled, and August no longer counts it. |

Both are §11.4's stated behaviour, and both are now the behaviour.

## A month with no terms

A carried month whose compensation terms have gone blocks the payroll with
`no_compensation_terms_for_a_carried_month` rather than skipping the month.
`assert_correctable` already prevents this state, so the guard is a backstop —
kept because the failure it prevents is not a crash but a **silent
underpayment**, which is the one outcome this platform exists to make
impossible.
