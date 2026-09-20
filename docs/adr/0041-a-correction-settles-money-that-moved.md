# 0041 — A correction settles money that moved; a balance is money that has not

**Status:** accepted
**Date:** 2026-09-20
**Amends:** [0035](0035-an-adjustment-closes-a-difference.md)
**Related:** spec §11.5; `docs/redesign/PRODUCT_RULES.md` F07, F09, F12;
[0040](0040-a-pending-order-is-a-sale.md);
`docs/repair/2026-09-19-batch-1-financial-rules.md`

## The situation

The follow-up review of Batch 1 ran the platform's own `balance_for` against
mocked ledger totals and got an answer nobody had intended:

| | |
|---|---|
| August, agreed and frozen | E£2,000 |
| Transferred | E£1,000 |
| Correction carried into September | E£200 |
| **What August still owed** | **E£800** |

August was agreed at E£2,000 and E£1,000 had been sent, so E£1,000 was still
to send. The screen said E£800.

The E£200 is then recovered a second time, in September, where the credit
lands and that month is paid E£200 less. HBA keeps it twice and she is paid
E£1,800 against an agreement of E£2,000 — without anybody reopening the month,
which 05B retired precisely so that an agreed figure could not quietly move.

Absorbing had the mirror-image fault. *HBA takes the loss* reduced the money
HBA still owed her, which is not a loss being taken.

## Why it was not obvious

ADR 0035 fixed a sign error by making an adjustment **close whichever
difference the month had**, and that sentence is right about one difference and
wrong about the other. There are two:

* **A correction's difference** is between the figure a month was agreed at and
  what that month now calculates to. It concerns money that has **already
  moved**, and the decision is where it is recovered from — or that it is not
  recovered.
* **A balance** is the rest of what was agreed and has **not moved yet**.

`balance_for` subtracted the first from the second. Every existing test walked
past it because each one held only one of the two facts: the correction tests
asserted correction status and never the source month's balance, and the
payment tests had no correction in them.

## Decision

**A correction adjustment does not change what its source month still owes.**

1. `balance_for` asks two different questions of the ledger. An **overpaid**
   month — more sent than it was agreed at — is closed by `SETTLES_AN_EXCESS`:
   `credit`, `writeoff`, `correction`, exactly as 0035 decided, unchanged. A
   month that is **still owed** money is reduced only by `FORGIVES_A_DEBT`:
   `writeoff` and `correction`.

2. **A `credit` is on the second list nowhere.** Carrying recovers the money
   from the month it is carried *to*. Taking it off the source as well is the
   double recovery above. This is the one clause of 0035 that this ADR
   overturns: *"a credit or a write-off reduces the difference, whichever
   direction that difference runs"* is true of a write-off and false of a
   credit.

3. **Absorbing a correction records an `accepted`, always.** R4 introduced that
   type for the case it had noticed — a month with no transfer recorded, where
   nothing can be taken back. The same sentence turns out to be true whenever
   anything is still owed. A write-off means *we are not sending the rest*; an
   acceptance means *the agreed figure stands and HBA takes the difference*.
   They were one row type and therefore one arithmetic, and the arithmetic
   belonged to the other one.

4. **Nothing a write-off has ever meant changes.** It still closes an
   overpayment and still forgives a remainder nobody will chase, and a row
   already written keeps its type and its effect. What changed is which act the
   corrections service records with it.

5. **A `release` un-applies a credit at both ends.** It is netted out of any
   total that counts credits and appears in no total that does not — otherwise
   an overpaid month whose carry bounced back reads as settled on a recovery
   that never happened.

## What follows from it, said plainly

**Absorbing takes the whole remaining difference.** There is no partial
version, because absorbing recovers nothing either way. Anything recoverable is
carried first and the rest absorbed — which is the order somebody would choose
anyway: take back what moved, then decide about what did not.

**A month can be fully corrected and still owe money.** That is not a loose
end. The agreement stands (05B), the correction is settled, and what has not
been sent is still to send. The Payments screen shows the two separately, and
`forgiven_piastres` is on the balance so the difference between *adjusted* and
*what reduced the balance* is visible rather than netted away.

## The cost

An operator who understood *absorb* as "and that closes the month" will find
the month still payable. That is the correct reading and it was always the
correct reading; the arithmetic simply agreed with the wrong one. The decision
screen now says which of the two figures each choice moves, beside the button,
rather than leaving it to be inferred from a balance afterwards.
