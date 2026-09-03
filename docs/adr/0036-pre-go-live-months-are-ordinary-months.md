# 0036 — Months before go-live are ordinary months, settled outside

**Status:** accepted
**Date:** 2026-09-04
**Supersedes:** [0014](0014-historical-months-show-sales-only.md)
**Implements:** spec §11.2
**Related:** [0029](0029-a-late-order-is-paid-at-its-own-months-rate.md), §9.5

## The situation

ADR 0014 gave months before go-live their own state. They showed order counts
and net sales, never a commission figure, and were labelled *"Settled before
the platform"*.

Its reasoning was not stylistic. It said, correctly at the time:

> Calculating those months correctly is not possible either. It would require
> the compensation terms in force at the time, which exist only in the old
> system and in people's memory.

**That premise has changed.** The business is entering those terms — through a
new pay-history editor, month by month or by range, per model. The information
is no longer only in somebody's memory; it is about to be in the database, put
there deliberately by the person who knows it.

What ADR 0014 bought was safety: no month HBA had already paid could be
approved and paid a second time. What it cost was a model opening the portal
and seeing seven months of her own year drawn hollow, captioned *"not shown
here"*, next to two months that were real. The business's words: *"I don't
want the models to feel that we treated them differently."*

## Decision

**A month before go-live is an ordinary month in every way except that it
cannot be paid.**

1. It has compensation terms, entered by hand, which may differ month to month
   in **type** as well as amount — a model can be commission-only in January
   and on a guaranteed minimum from June, which is what actually happened.
2. It is calculated by the same `calculate_month` as any other month. No second
   implementation, no reconstructed arithmetic.
3. It has targets, where the arrangement needs them, recorded as an **outcome**
   rather than as counts (see Consequences).
4. It is approved, producing a snapshot, and frozen thereafter exactly like
   September will be.
5. It is marked **settled externally**. Its balance is always zero, it never
   appears as owed, and the payments screen refuses to record a transfer
   against it.

`historical` disappears from every model-facing screen. The word survives only
where the business needs it: **one line on the Payments tab**, shown only to a
model who actually has a month before go-live — a model who joins in October
never learns there was an old dashboard.

Point 5 is what preserves ADR 0014's protection. The safety no longer comes
from refusing to calculate the month; it comes from the month's balance being
structurally zero. **A month that cannot carry a balance cannot be paid twice**,
which is a stronger guarantee than a blocker somebody can remove.

## Consequences

**The blocker becomes a mode.** `ALREADY_SETTLED_OUTSIDE` stops preventing
approval and starts marking its result. The double-payment protection moves
from `blockers_for` into `balance_for`, where it cannot be bypassed by
approving the month.

**Targets on backfilled months record an outcome, not counts.** The business
has whether a target was met; it does not have the video and story numbers from
March. Inventing counts to reach a known outcome would be fabricating evidence
for a figure that decides money. So a backfilled target carries *met* or
*missed*, recorded by hand, and the model's Targets card says so — the count is
shown as an em dash with a note that the numbers were not kept on the old
dashboard. This is the one place a pre-go-live month reads differently from a
new one, and it reads differently because it *is* different.

**A computed figure may disagree with what was actually paid.** March's
commission calculated here could be a few pounds from what the old dashboard
sent. The business has accepted this and will say so to the models directly,
before the portal opens, rather than in reply to a question. Nothing on the
dashboard apologises for it; a banner about discrepancies invites an audit of
months nobody would otherwise have questioned.

**Approving eight months for twenty-one models is real work**, even with
ranges. It is one-time, and it is the price of the year looking like a year.

## Alternatives considered

**Backdate the terms in code.** Rejected by the business, and rightly: the
rates and salaries differ per model and per month, and a developer typing them
from a spreadsheet is a worse record than a maintainer entering them on a
screen that shows what they have entered.

**Show sales only, with no commission** — ADR 0014's answer, retained for the
charts. Rejected as the whole answer: it leaves the earlier months visibly
lesser, which is precisely the feeling being removed. It survives as the
fallback if a model's historical rates genuinely cannot be established.

**Move `GO_LIVE_MONTH` back to January.** Rejected: go-live means *the month
this platform started paying*, it differs by environment (staging 2026-08,
production 2026-09), and moving it would make eight months of settled money
payable — the exact failure ADR 0014 was written to prevent.
