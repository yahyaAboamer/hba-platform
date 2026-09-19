# 0040 — A pending order is a sale, and the carry becomes a backlog

**Status:** accepted
**Date:** 2026-09-19
**Related:** `docs/redesign/PRODUCT_RULES.md` F02, F07, F10–F13;
`HBA_Readiness_Audit/HBA_Readiness_Audit.md` findings A01 and A07;
`docs/repair/2026-09-19-batch-1-financial-rules.md`

## The situation

The agreed rule is F02: **orders count when pending or delivered, and a failed
delivery does not count.** The platform did not do that. `calculate_month`
counted delivered orders only, and the pending-inclusive rule lived in
`preview_calculation`, behind a screen that advertised
`live_transition_not_enabled`.

So there were two answers to *what is this month worth*. The readiness audit
reproduced the gap with the platform's own service functions: E£10,000 of
pending sales at ten percent produced **E£0 live and E£1,000 in the preview**.
A model could be shown one figure and paid the other.

Under the delivered-only rule, an order still travelling when its month closed
was left out and paid later, by whichever payroll ran after it was delivered —
the §11.4 carry-forward. That mechanism exists because the old rule needed it.
The new rule does not: an order counts in the month it belongs to, whether or
not the courier has confirmed it yet.

## Decision

**One rule, and the carry becomes a finite backlog rather than a mechanism.**

1. `calculate_month` counts `EARNED` and `PENDING`. `preview_calculation`
   keeps its name and its richer source facts, and now differs only in where
   the facts come from, never in what they are worth.

2. **Every snapshot records the rule that agreed it.** `payload_json["policy"]`
   is `pending_inclusive` on everything approved from here. A snapshot with no
   policy at all was agreed delivered-only — there is no third possibility,
   and that absence is what identifies the months the transition must
   reconcile.

3. **Approval settles every order it counted**, pending included, not only the
   delivered ones. The link naming which payroll paid an order is what stops a
   later payroll offering the same order again.

4. **`carried_into` pays only what an order's own month did not.** It reads
   the snapshot's frozen order list and the policy beside it
   (`counted_in_snapshot`). Under the old rule that is every order still
   travelling at approval; under the new one it is none. The set can only
   shrink, and nothing is ever added to it again.

5. **A closed month is recalculated under its own rule.** `correction_for`
   passes `policy_of(snapshot)` to `calculate_month`. Comparing a
   delivered-only agreement against a pending-inclusive recalculation would
   report *the policy change itself* as a difference, and tell somebody a
   closed month had become worth more on evidence that had not moved.

6. **A model's performance is not frozen, and her money is** (F13). An agreed
   month's total, breakdown and carried lines still come out of the snapshot.
   Her sales figure, her order counts and her year chart come from the month
   as it is now, so a parcel refused in November corrects September's sales
   without touching what September was agreed at.

## What this does not change

**No approved snapshot is rewritten and no recorded transfer moves.** The
transition is forward-only: old agreements stand exactly as they were made,
and the orders they left unpaid are still paid the way they always were.

**Reopening stays retired** (05B). A month whose evidence moves after approval
is still settled by a correction against the agreement (05C), never by
restating it.

**It does not decide D09** — a delivery failure later found to be wrong, after
a deduction has been used. Still open.

## The cost, stated plainly

A pending order that is counted and later fails is money agreed and possibly
transferred against a sale that did not stand. That is not new — it is the
business's own rule, and the reason the correction machinery exists. What this
ADR owes that rule is that the correction machinery be good enough to carry
it: cumulative rather than once-per-month, partial rather than all-or-nothing,
and visible before the transfer as well as after. Batch 1 rebuilt all three.
