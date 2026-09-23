# 0035 — An adjustment closes a difference; it never opens a larger one

**Status:** accepted, amended by
[0041](0041-a-correction-settles-money-that-moved.md)
**Date:** 2026-09-04
**Implements:** spec §11.5 (reconciliation)
**Related:** [0004](0004-round-once-at-the-end.md), [0030](0030-a-reopened-month-emails-once-on-reapproval.md)

## The situation

A model on staging was reopened, re-approved and paid twice. The screen then
offered to settle a difference that grew every time it was settled.

Reconstructed from the database, not from the screen:

| | |
|---|---|
| August obligation, active snapshot (v3) | EGP 4,332.00 |
| Transferred (two payments, 28 August) | EGP 4,589.00 |
| **True overpayment** | **EGP 257.00** |
| Adjustments recorded against August | EGP 4,817.00 |
| What the payments screen reported | overpaid by **EGP 5,074.00** |

The overpayment displayed was twenty times the real one, and each press of
*Settle the difference* doubled it: EGP 2,537 became EGP 5,074, and would have
become EGP 10,148.

The cause is one sign in `balance_for`:

```
balance = obligation + credited - paid - adjusted
```

On the **source** month an adjustment was subtracted, which pushes an
already-overpaid month further into overpayment rather than closing it. On the
**destination** month a credit was added, which makes the later month owe
*more* — while the reconcile screen promises the model "keeps it, and next
month owes that much less".

Three docstrings, the reconcile screen and the word *credit* all described
carrying an **overpayment** forward. The arithmetic implemented moving an
**unpaid obligation** forward, which is a different operation with the opposite
sign. `test_a_credit_increases_what_a_later_month_owes` pinned the second while
its docstring claimed the first: its fixture is a month that was never paid at
all.

## Decision

**An adjustment moves a month's balance toward zero. It can never move it away
from zero, and it can never exceed the difference it is closing.**

Concretely:

1. On the **source** month, a credit or a write-off *reduces the difference*,
   whichever direction that difference runs. An overpaid month becomes settled;
   an underpaid month written off becomes settled. The sign follows the
   balance, it is not fixed in the formula.

   > **Amended by [0041](0041-a-correction-settles-money-that-moved.md), and
   > this clause is the half that was wrong.** It is true of a write-off and
   > false of a **credit**. Carrying recovers the money from the month it is
   > carried *to*; reducing the source month as well recovers it twice, and a
   > month agreed at EGP 2,000 with EGP 1,000 sent and EGP 200 carried reported
   > EGP 800 still to send. Everything else here stands.
2. On the **destination** month, a credit means the model **already holds that
   money**, so the later month needs that much less in transfers.
3. The amount is **capped at the true difference** — `paid − obligation` — and
   never at a balance that already has adjustments folded into it. The cap
   alone would have stopped this defect at EGP 257 even with the sign wrong.

The reconcile screen's existing wording is correct and does not change. The
code changes to match it.

## Consequences

`test_a_credit_increases_what_a_later_month_owes` is rewritten, not deleted:
its scenario — moving an unpaid obligation to a later month — is a **different
feature** that nothing asks for today. If it is ever wanted it gets its own
name and its own control, because calling it a "credit" is what produced this.

Three adjustments on staging (EGP 4,817 against a real EGP 257) are junk generated
by the defect. `payroll_adjustment` is append-only by design, so they are
deleted directly at the database rather than reversed. **Production has never
had an adjustment recorded**, so nothing there is affected.

The cap makes one previously-possible act impossible: settling more than was
overpaid. That was never a legitimate act, and losing it is the point.

## Alternatives considered

**Leave the arithmetic and rewrite the docstrings** to say a credit moves a
debt forward. Rejected: it would leave the business with no way at all to
resolve an overpayment, which is the case §11.5 exists for and the only case
that has ever arisen.

**Cap without fixing the sign.** Rejected: the cap would hold the number still
while the source month stayed permanently overpaid on screen — correct
arithmetic is what makes the month reach zero.
