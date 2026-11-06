# 0075 — The payments desk's totals, labels and messages go past the approved export

**Status:** accepted by the owner, 6 November 2026. A divergence from the approved export.
**Date:** 2026-11-06
**Related:** ADR 0074 (the desk on a phone), ADR 0042 (full destinations),
F14 (an estimate is not a debt), `docs/design-refinement/payments/JOURNAL.md`
(the findings, with screenshots, that each decision answers)

## The situation

The whole Payments desk was refined on 6 November 2026. Every state was walked
on staging with fictional models added in the browser, and nothing was
written. Several of the problems found are in the export's own words or
structure:

- **The totals did not add up.** *Total required* included the month's
  estimate, so *Total required* − *Recorded so far* never came to
  *Remaining to send*. A payer checking the arithmetic stops trusting the
  page.
- ***Approved*** **named one state when three states are approved.** A
  part-paid or fully paid month is approved too; the pill meant "approved,
  nothing sent yet".
- **A transfer's page was titled *Receipt*.** It then said *No receipt
  attached* twice, and dated the transfer *Recorded* when the date is the day
  it was sent.
- **Amber meant everything.** It was used for a changed destination, an
  overpayment, a credit note and a missing receipt alike.

## Decision

1. **Two cards: *Left to send* (first) and *Recorded*.** Both are the
   server's own totals (`still_owed_piastres`, `recorded_piastres`).
   - A first draft had a third card, *Total to send* (sent + left). It added
     up, but it called money already sent "to send". On an overpaid month it
     was also more than the month's approved pay. It was removed in the
     second review round (journal §11, F2-2).
   - The estimate is not a debt (F14), so it is one quiet line under the
     cards: *Not approved yet: 3 models, about EGP 6,400*.
   - An overpayment is one line too, with its amount: *Overpaid: Hana by
     EGP 500*.
   - An overpaid row shows the approved amount under *To receive*, with the
     excess under it. The server's per-row figure for an overpaid month is
     what was sent, which is not what *To receive* means (F2-1).
2. **Labels:**
   - *Approved* becomes ***Ready to send*** (pill and filter).
   - *More sent than due* becomes ***Overpaid***.
   - A blank *Unavailable* becomes ***Not worked out yet***, with the reason
     under it.
   - A transfer's page is ***Transfer***, dated ***Sent on***, and its link is
     ***Details →***.
   - Settling an overpayment and deciding a correction both say ***Take it
     off a later payment*** and ***HBA absorbs it***.
3. **Three tiers of message**, each drawn differently:
   - **Warnings** use an amber rule on a tinted ground, with the fact in bold
     and the act beside it. They cover a changed destination, an
     overpayment, and a month that can't be approved yet.
   - **Notes** use a quiet rule and no fill. They cover a credit, and what
     saving the record form does.
   - **Help** is plain quiet text.
   - A missing target or missing terms is shown as a warning, not an error,
     because it is somebody's turn, not a fault (§11.3).
4. **A model's month opens with one sentence saying what is next**, for
   example *Send EGP 9,800 to Mona's InstaPay, then record the transfer here.*
5. **Neither money decision is preselected.** The correction screen used to
   preselect *Carry*; the overpayment screen already preselected nothing.
6. **Smaller items:**
   - Filters with no rows are hidden.
   - A failed load offers *Try again*.
   - An empty search offers *Show all models*.
   - Record-form errors sit under their own field, tied to it with
     `aria-describedby`.
   - The approval button names its amount (*Approve EGP 6,400*).
   - Every Payments control is at least 44px tall on a phone.

7. **Less repetition** (second round, journal §11):
   - each amount is said once on a model's month;
   - *Copy* and the destination line appear on desk rows only where money is
     still to be sent;
   - there is no empty Transfers card before approval.
8. **The shared month picker is 44px tall with 16px text on phones**, on
   every screen that uses it. Desktop keeps the export's 38px.

## What it costs

- The desk no longer shows a month total. The export's three cards are now
  two.
  - Somebody asking finance for the month's cash needs *Left to send*, which
    is the first card.
  - Somebody asking for the month's approved pay opens Payroll, which is
    where that figure is agreed.
- Six labels differ from the export.
- Paid and credit-covered rows on a phone no longer show where the money
  went. It is one tap away, on the model's month.

## Not changed

- No calculation, request, permission or safeguard changed.
- Approval still asks once and still sends the same fingerprint.
- Recording still uses one operation key, uploads the proof first, requires
  a reason when the amount differs, and refuses future dates (now also an
  empty one).
- The overpayment form still caps the amount, and the correction still sends
  the outstanding figure it showed.
- Every figure is still the server's. The client sums nothing; it chooses
  which server figure goes under each label.
