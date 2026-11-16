# Production rebuild, batch 5: Overview (build plan)

Decision: `docs/adr/0084-production-is-rebuilt-around-the-production-order.md`
(decision 11). Approved screen: the `#v-overview` view in
`docs/redesign/mockups/production-orders.html` (sample data). Batches 1 to 4
(Orders, Tasks, Incoming, Suppliers) are merged; their contracts are the
other `docs/plans/2026-11-14-production-*-build.md` files.
Branch: `claude/production-overview`.

## Scope

One Overview screen at `/production/next/overview`, the first tab: **nothing
to type**. It reads what batches 1 to 4 already work out and puts it on one
page. No migration, no new table, no write endpoint.

Not in this batch: ratings, the performance record, the factory's login,
reminders, the platform's Today page, carrying old orders over.

## One read: `GET /api/prod/overview` (`production.view`)

One server function, `services/overview.py`, built **only** from functions
that already exist (do not re-derive a rule a batch already owns):
`orders.rows("open")` (next action, flags, lateness, steps),
`orders._facts_for` / `Facts`, `orders.cost`, `tasks.listing`,
`account.purchase_tasks`, `incoming.listing`, `suppliers.standings`.
"Today" is Cairo's date (`orders.today()`).

Response:

```
{
  today,
  summary: {open_orders, planned_pieces},
  figures: {
    decisions,                                  # count of `decisions`
    late_orders, open_orders,                   # "2 of 5"
    arriving_this_month: {month, pieces},       # incoming totals.this_month
    owed_piastres                               # owner only (omitted otherwise)
  },
  decisions: [...],
  problems:  [...],
  orders:    [...],   # orders.rows("open"), unchanged shape
  arriving:  [...],   # first 5 of incoming arrivals, by due date
  owed:      [...]    # owner only (key omitted otherwise)
}
```

### decisions: what waits for the owner

Every open task whose `who` is `owner`, from `tasks.listing` (so the sample to
approve, the order to settle, and hand-added "for the owner" tasks), sorted as
the Tasks list sorts them. Each item keeps the task's fields (`key`, `title`,
`order`, `due`, `since`, `open`, `overdue_days`, `kind`, `id`). The screen
writes "waiting N days" from `since`.

### problems: what is wrong right now

In this order, each with `kind`, `title` (plain words, sentence case), `detail`
(one short line), and `link` (`{to: "order", id, open?}` |
`{to: "incoming"}` | `{to: "tasks"}`):

1. **late_order**: each open order with `lateness_days > 0`. Title
   "<style> · <colour> is N days late". Detail: the last delivery-date move
   in the order's date history ("Factory moved 20 Nov to 26 Nov · <reason>")
   if there is one, else the current stage ("At Making"). Link: the order.
2. **late_material**: each purchase task whose key ends `:chase` (expected
   before today, not received). Title "<item> for <style> are N days late"
   (or "<item> from <supplier> are N days late" with no order). Detail: the
   supplier's name, and the stage the order is at. Link: tasks. **No price.**
3. **count_mismatch**: each delivery whose two counts differ with no reason
   (`needs_reason`). Title "N pieces missing between factory and Khazenly"
   (or "N more counted than shipped"). Detail "<style> · <colour> · no reason
   given yet". Link: the order with `open: "delivery-reason:<id>"`.
4. **cost_over** (**owner only**; never built for anybody else): each open
   order whose `actual_total_piastres` is not null and above
   `target_total_piastres`. Title "<style> · <colour> costs EGP N more per
   piece than planned". Detail "EGP actual against EGP target · <the parts
   over target, in words>". Link: the order.

The money is in the title of `cost_over` only, so that whole item is left out
for people without `production.owner`: drop the item, do not blank it.

### orders

`orders.rows("open")` as it is (it already carries no money). The screen
shows each with its next action.

### arriving: the nearest deliveries

The first 5 of `incoming.listing()["arrivals"]` by due date, unchanged shape
(pieces, order, kind: finished / fix, due, late flag). No money in it.

### owed (owner only)

Every supplier whose `Standing.owed > 0`, largest first, with
`{supplier: {id, name}, owed_piastres, detail}`. `detail` is one short line
from what is already known: the open (not fully paid) purchase items if any
("Rest of the fleece purchase"), else "Last paid <date>" when a payment
exists, else nothing. **Overpaid suppliers are not subtracted** from the
total: `figures.owed_piastres` is the sum of the positive balances only (an
overpaid factory does not reduce what is owed to the fabric supplier).

The mockup's "Next weekly payment 19 Nov" is not built: the platform does not
store a payment schedule. Divergence, recorded here.

### Money rule (keep it)

Without `production.owner`: no `owed`, no `figures.owed_piastres`, no
`cost_over` problems, and no key ending `_piastres` anywhere in the response.
A recursive test walks the whole response for a viewer and for the QC manager
(`production.edit`) and fails on any money key or any "EGP" in a string.

## Screen

Follow `#v-overview`:

- Header: "Production", under it "<Friday 13 Nov> · N orders in production,
  X pieces planned". "New order" button for the owner only.
- Four figures (`.facts` pattern used by the supplier page): Waiting for your
  decision (owed colour when > 0), Orders running late "2 of 5" (refused
  colour when > 0), Arriving in <Month> "N pieces", You owe suppliers
  "EGP N" (owner only; the QC manager sees three figures).
- Two cards side by side, one column under 860px: **Waiting for your
  decision** (for the QC manager headed "Waiting for the owner", with no
  buttons) and **Problems right now**. A decision row: the title, the order
  line and "waiting N days"; its button goes to the order with `?open=` like
  the Tasks screen (e.g. "Review sample", "Settle"); a hand-added one shows
  "Open tasks". A problem row: title, detail, an "Open" link.
- "Every order, and what happens next": a surface of rows, each the order
  name (link), "N of 10 · <stage> · <quantity line>", the step bar, and on
  the right "Next: <what> · <who in words>" and the date with lateness in the
  refused colour. Reuse the Orders list's pieces (step bar, quantity line,
  lateness words) rather than re-writing them.
- Two cards: **Arriving next** (pieces · style · colour, the date, late in
  the refused colour, "by <date>" when late) and **What you owe** (owner only;
  the QC manager sees Arriving next full width).
- Empty states, in plain words: no decisions "Nothing is waiting for you."
  (QC: "Nothing is waiting for the owner."), no problems "No problems right
  now.", no orders "No orders in production." with the New order button for
  the owner, nothing arriving "Nothing is on its way.", nothing owed "You owe
  no supplier anything." Loading and error states as in batches 1 to 4.
- Add **Overview** as the first tab in `ProdTabs`; `/production/next` (the
  index) goes to Overview instead of Orders.
- Phone: 390px with no sideways scroll, 44px targets, one column.

## Verification

- Backend: `tests/test_prod_overview.py`: each kind of problem appears and
  disappears with its cause; decisions are the owner's tasks; late count and
  open count; arriving is the 5 nearest; owed sums positive balances only and
  skips overpaid suppliers; the recursive no-money check for viewer and QC
  manager (and that the owner does get `owed` and `cost_over`); permission
  table (no `production.view` → 403). Also keep green: `test_prod_orders`,
  `test_prod_tasks`, `test_prod_incoming`, `test_prod_suppliers`,
  `test_reachability` (the new route must be called by the frontend),
  `test_permissions`.
- Frontend: tests for the four figures with and without money, each card's
  rows and empty states, the decision button per kind and per permission,
  the tab and the index redirect. `cd frontend && npm test` and
  `npm run build`.
- Browser: a throwaway local database (`hba_browser`) with sample orders at
  different stages, a late purchase, a mismatched delivery, an order over its
  cost, owed and overpaid suppliers; as the owner and as the QC manager, at
  1440 and 390.

## What was built (15 November 2026)

- `app/modules/production/orders/services/overview.py` and `GET /api/prod/overview`;
  `frontend/src/departments/production/next/OverviewScreen.tsx` and
  `overviewLogic.ts`. Overview is the first tab and `/production/next` opens it.
- Choices the contract left open:
  - `figures.arriving_this_month` also carries `label` (the month's name).
  - `decisions` keep a fixed list of a task's fields, so a hand-added task's
    note never rides along.
  - Problems: late orders most late first; cost over target biggest first;
    late materials in the Tasks list's order. A delivery short on one size
    and over on another is said as the missing pieces.
  - **What you owe, the line under a supplier**: a weekly payment is tied to
    no purchase, so a purchase bought before the last weekly payment may be
    paid off and cannot be told apart. A purchase is named ("Rest of the
    fleece purchase") only when it was bought after the last lump-sum payment
    and its own deposit is short of its total; otherwise the line is "Last
    paid <date>", or nothing.
  - For the QC manager the first figure and the card read "Waiting for the
    owner".
  - Money figures use the platform's `formatEgp` ("EGP 143,150.00"), as the
    Suppliers screens do, not the mockup's whole pounds.
- Independent review (read-only) of the money gating: no leak found; one
  wording fix (the QC manager's first figure), made. Residual, by design: a
  date-move reason or a purchase's item name is typed by a person, and a
  price typed there would be seen by the QC manager.
