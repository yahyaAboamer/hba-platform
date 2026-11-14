# 0084. Production is rebuilt around the production order, as platform screens

**Status:** Accepted (design approved; nothing built yet)
**Date:** 2026-11-14

## Context

Production moved in from an outside app (ADR 0069, 0076) and kept its own
look, in a frame, with 21 menu entries. About seven hold real records
(orders, samples, suppliers, tasks, the QC checklist, products, uploads). The
rest show fixed content or zeros: materials, bill of materials, route
templates, costing, payments (an approval that stores nothing), warehouse,
reports, problems, and copies of users, audit and settings.

The owner (12 to 14 November 2026) asked for it to be redesigned from how HBA
Wear really produces: about 2 styles and 2,000 pieces a month, all made
outside, about 14 suppliers around one main factory. The owners decide; one
QC manager orders materials, checks fabric and pattern, deals with suppliers
and inspects finished goods. Finished goods go to Khazenly, which counts them
and updates Shopify stock itself. Khazenly has no API: its count is read from
its dashboard by a person.

The owner's stated problems: late deliveries, wrong sizes, quantities not
tracked, some cost surprises. He wants to see the nearest deliveries with
quantities, the production team's upcoming tasks, and what needs attention.

The approved mockup is `docs/redesign/mockups/production-orders.html` (all
five sub-tabs; sample data). The owner approved each sub-tab in turn.

## Decision

1. **Platform screens, not a framed app.** Production is rebuilt in the
   platform's own frontend and design system. This supersedes ADR 0069's
   "keeps its own look" and ADR 0076 decision 6 (the frame). Existing orders,
   samples, suppliers and uploads carry over.

2. **Five sub-tabs:** Overview, Orders, Tasks, Incoming, Suppliers. Samples,
   quality checks, files and costs live on the order, not in a menu.

3. **The production order** is one style in one colour at one factory, with a
   size split (XS, S, M, L, XL, XXL; XS optional), who buys the fabric (HBA
   or the factory), how it is printed (at the factory, an outside print
   house, or not at all), a target date and a target cost per piece in five
   parts: fabric, manufacturing, printing, accessories, special packaging.
   Only owners create orders.

4. **Ten stages:** Plan, Sample, Materials, Fabric check, Pattern check,
   Cutting, Making, Final inspection, Warehouse receipt, Settle. Printing
   happens after cutting and is part of Making. The sample is skipped on a
   repeat run where nothing changed. The QC manager checks fabric whoever
   bought it. Each stage has an expected date, filled in backwards from the
   target date when the order is made, and editable. Owners approve samples
   and settle; the QC manager records the rest.

5. **The quantity chain, per size:** planned, cut, passed / to fix /
   rejected, shipped from the factory, counted by Khazenly. Planned and
   actual are both kept (the split can change at cutting). Every drop between
   two counts carries a reason. The factory ships as pieces finish, so an
   order has several deliveries; fix pieces return as a later delivery. Each
   delivery holds two counts, both typed by the QC manager or an owner, and
   they may be entered on different days. A mismatch is flagged and opens a
   task; the order cannot close until it has a reason.

6. **The date history.** When a delivery date moves, the old date, who moved
   it and why are kept. Lateness is calculated, never typed.

7. **Tasks are generated** from each order's current stage and its expected
   date, grouped as overdue, today, this week, later, with filters for
   overdue, QC manager, owner and waiting on suppliers. A task opens the form
   for its stage and is done when the stage is. Tasks can also be added by
   hand. There is one QC manager, so there is no assigning. The owner sees
   the whole list.

8. **Settlement.** The factory is owed the making rate (manufacturing, plus
   printing when it prints) for each piece cut. A rejected piece takes off
   the making rate when HBA bought the fabric, and the fabric cost plus the
   making rate when the factory bought it (the owner, 14 November 2026:
   accessories and packaging never come off the factory). Pieces sent back for fixing are held until they
   return.

9. **Suppliers** belong to one or more sections (manufacturers, fabric,
   printing houses, accessories, packaging; the owner can add a section by
   name). Each has a running account: finished work and purchases add to it,
   deductions, deposits and payments take off it. The factory is paid a lump
   sum weekly, not per order, so the balance can be overpaid. A purchase
   records what, how much (kilograms, metres or pieces), the unit price, the
   order it is for and an optional deposit; the rest stays on the balance
   with no due date. A payment records amount, date, method (bank transfer,
   cash, InstaPay, mobile wallet, cheque), kind, and an optional note and
   receipt photo. Only owners record payments. The account is append-only:
   a wrong line is reversed, never edited. Until an order is settled, what
   it has earned so far counts in what is owed but is not yet a line;
   settling writes the line. A purchase suggests the order's actual cost
   per piece and never sets it by itself. **The QC manager never sees
   money**: no prices, costs, balances or payments, on any screen.

10. **Ratings.** When an order is settled the owner rates each supplier on
    it: quality, timing, dealing with them (1 to 5 stars each) and a note.
    Timing is offered from the real lateness. Lateness and reject rate per
    supplier are calculated.

11. **Overview** adds nothing to type. It shows decisions waiting for the
    owner, problems (late orders, late materials, count mismatches, cost over
    target), every order with its next action, the nearest deliveries and
    what is owed.

12. **Not built.** Restock planning stays in Shopify's planner. Shopify stock
    is not touched (Khazenly updates it). Materials, bill of materials, route
    templates, capacity, priorities, drop phases, the typed progress
    percentage, the timeline and calendar views, the 15-item checklist,
    reports and Production's own users, audit and settings screens are
    removed.

## Build order

1. Orders (the order, its stages, the size table, dates, cost, deliveries).
2. Tasks.
3. Incoming.
4. Suppliers: sections, purchases, account, payments.
5. Overview.
6. Second build: ratings and the performance record, then the factory's own
   login (its own orders only; it enters cut quantities, dates and progress;
   it sees no costs, balances or other suppliers).

The old framed tab stays in place until the new one covers it.

## Consequences

- Supplier money is recorded in Production, separate from the Payments
  department, which pays models.
- The stage-date gaps in the mockup are placeholders; the real typical
  durations are needed from the owner or made adjustable.
- A wrong Khazenly count typed by hand looks like a missing piece. The
  mismatch task is where that is corrected.
- Later, not decided: reminders for overdue tasks, comparing suppliers within
  a section, reports, logins for suppliers other than the main factory,
  restock planning inside the platform.
