# Production rebuild, batch 3: Incoming (build plan)

Decision: `docs/adr/0084-production-is-rebuilt-around-the-production-order.md`
(decision 5). Approved screen: the `#v-incoming` and `#v-deliver` views in
`docs/redesign/mockups/production-orders.html` (sample data). Batches 1 and 2
are merged: `app/modules/production/orders/`,
`frontend/src/departments/production/next/`, and their contracts in
`docs/plans/`. Branch: `claude/production-incoming`.

## Scope

One Incoming screen at `/production/next/incoming`: what is still to arrive at
Khazenly, nearest first, with quantities per size, and every delivery with its
two counts. **No new table and no migration**: everything is read from the
orders, sizes and deliveries batch 1 stores. Recording a delivery, entering
Khazenly's count and giving a mismatch reason already exist on the order page
(`DeliveryForm`); this screen links to them with `?open=` (batch 2).

Not in this batch: Shopify stock (Khazenly updates it itself), reading
Khazenly (it has no API; both counts are typed), incoming fabric and
accessories (they arrive at the factory and are stages and tasks), Suppliers,
Overview. The old framed tab is untouched.

## What the screen answers

"What are the closest orders to receive, with quantities and every important
detail?" (the owner's words), and where the warehouse count is recorded.

## Data (one server function, beside `next_action` in `services/orders.py`)

Reuse `Facts`. For every **open** order that is not fully received:

**An arrival row for finished pieces**, when pieces are still to leave the
factory:
- `expected` per size and in total, from the latest count the order has:
  `planned` until cutting is done, then `cut`, then `passed` once the final
  inspection is done. `basis` says which (`planned` | `cut` | `passed`).
- `shipped` so far on `finished` deliveries, per size and in total.
- `to_come` = expected - shipped, never below zero, per size and in total.
- `due`: the order's `delivery_date`; `late_days` from batch 1's lateness.
- `stage` (key, label, position) and `status_words`: a short plain phrase for
  where it is ("being cut, final numbers after cutting", "waiting for
  fabric", "sample not approved yet", "arriving as pieces finish").
- `can_record`: true once cutting is done (deliveries are allowed).

**An arrival row for fix pieces**, once the final inspection is done and fix
pieces are not all back: `to_come` = to fix - shipped on `fix` deliveries, per
size; `due` the delivery date; `kind: "fix"`.

Rows are ordered by `due`, then order code; fix rows after the finished row of
the same order.

**Deliveries**: every delivery of an open order, and deliveries of closed
orders counted in the last 30 days, newest first. Each: order (id, code,
style, colour), number, kind, `shipped_on`, `counted_on`, shipped and counted
per size and in total, and `state`:
- `waiting_for_count` (any size has no count),
- `mismatch` (counts differ and no reason) with `difference` (counted minus
  shipped, signed) and the sizes that differ,
- `explained` (counts differ, reason given; carry the reason),
- `match`.

**Totals for the four figures at the top:**
- pieces to come with `due` in the current Cairo month,
- pieces to come with `due` in the next month,
- pieces shipped and waiting for Khazenly's count,
- pieces in unexplained mismatches (sum of absolute differences).
Overdue arrivals (due before this month) count in the current month. Also
`to_come_total` and the label of each month ("November", "December").

No money anywhere in this response, for anybody.

## API

`GET /api/prod/incoming` (`production.view`):
`{today, totals, arrivals: [...], deliveries: [...]}`.

## Screen (follow the mockup)

- Tab **Incoming** in `ProdTabs`, after Tasks.
- Header: "Incoming" with the sentence "N pieces still to leave the factory ·
  N shipped and waiting for Khazenly's count".
- The four figures (the mismatch figure in the refused colour when not zero,
  waiting-for-count in the owed colour when not zero).
- **Arriving next**: one row per arrival: a bold title ("Oversized hoodie ·
  Off-white · 685 of 985 still to come", or "· 800 planned", or "· 30 fix
  pieces"), the sizes on one line ("S 148 · M 296 …", only sizes that are not
  zero), the order line (code, factory, status words), the date with
  "N days late" when late, and "Record delivery" when `can_record` and the
  person holds `production.edit`. The button goes to
  `/production/next/orders/{id}?open=delivery`. The title links to the order.
- **Deliveries**: one row per delivery: title ("Oversized hoodie · Black ·
  delivery 2"), a line ("11 Nov · factory shipped 446 · Khazenly counted 445 ·
  size M is 1 short"), a pill in words (Counts match, Waiting for count,
  N pieces missing, N more than shipped, Explained), and one button for
  `production.edit`: "Enter Khazenly's count" (`?open=delivery:<id>`) or "Add
  reason" (`?open=delivery-reason:<id>`).
- Empty states in words ("Nothing is on its way.", "No deliveries yet.").
- Phone first; same narrow-layout approach, 44px targets, no horizontal
  scroll at 390px; both themes; tokens only.

## Verification

- Backend: `tests/test_prod_incoming.py`: the `expected` basis at each point
  (planned, cut, passed), partial deliveries, fix rows, ordering, every
  delivery state, the four totals around a month boundary and with overdue
  arrivals, closed orders dropping out (and their recent deliveries staying
  30 days), cancelled orders never listed, the permission table (viewer
  reads; someone without `production.view` gets 403), and the recursive
  no-money check. Keep green: `test_prod_orders`, `test_prod_tasks`,
  `test_reachability`, `test_production_api`, `test_migrations`.
- Frontend: tests for the figures, both lists, the pill and button per state
  and per permission, empty states. `cd frontend && npm test` and
  `npm run build`.
