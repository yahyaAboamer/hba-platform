# 0074 — The payments desk on a phone goes past the approved export

**Status:** proposed — a divergence from the approved export, for the owner to accept or overrule
**Date:** 2026-11-06
**Related:** `frontend/src/departments/affiliates/Payments.tsx`, `Payments.css`;
`PaymentDetail.tsx`, `PaymentDetail.css`; `PaymentRecord.tsx`;
`__tests__/PaymentSafety.test.tsx`

## The situation

A first-time payer walked the Payments screens on staging (6 November 2026).
At 390px, measured:

- **The list.** Three 115px figure cards, then six filter chips over three
  rows, then an 864px table clipped at the screen's edge. The first model
  started about 700px down, and every row's action sat off the screen.
- **A model's month.** The side cards were 320px wide beside a 343px breakdown
  (a fixed `flex-basis`). The amount was the fourth line of its own list. The
  destination, with *Open InstaPay*, came before *Approve this month*, so the
  screen offered to send money before the figure was agreed.
- **The record form.** The outstanding figure was a 13px grey line, inputs
  were 14px (below the size iOS zooms on), and the acts were two small buttons
  side by side.

The owner asked for a mobile redesign with creative freedom, keeping the
business rules, payment safety and the line between approving an amount and
recording a transfer made elsewhere.

## Decision

Below 640px:

1. **The totals are one divided panel**, label left, figure right.
2. **The filters are one row that scrolls inside itself** and runs to the
   screen's edge, so the cut-off chip says there is more.
3. **The table becomes a list of rows**: name and amount on line one, the
   arrangement under the name, the destination and *Copy* on line two, the
   state and the one action on line three. Every field the table showed is
   still there. Explicit ARIA roles keep it a table to a screen reader.
4. **A model's month opens on its amount**, with the arithmetic under it.
5. **The card for the month's next act comes first**, keyed on its stage:
   *approve* (Approval first), *send* (Where to send it, then Transfers, then
   the settled Approval), *done* (Transfers first, the destination last).
   Every card stays on the page; only the order changes.
6. **Copy reads as a word** with a 44px target; actions are full width and
   48px tall.
7. **The record form leads with the outstanding figure** at 28px, sets inputs
   at 16px and up (the amount at 18px, tabular), and stacks *Record payment*
   above *Cancel*, both full width.

At every width: a **progress bar** in the Transfers card once a month is
approved (recorded against agreed; hidden from screen readers because the
sentence under it says the same), and the record form's outstanding figure as
a headline rather than a grey line.

Desktop is otherwise unchanged: five of eight desktop screenshots are
pixel-identical before and after.

## What it costs

- The phone's card order differs from the export's (destination, approval,
  transfers). On a phone, only one card is on screen at a time, so the order
  is the instruction.
- Two figures sit on the record form's desktop layout where the export has
  one line.

## Not changed

No figure, rule, permission or request changed. Approval still asks once
(PR #151), recording still states that nothing is sent,
and the server still refuses future transfer dates.
