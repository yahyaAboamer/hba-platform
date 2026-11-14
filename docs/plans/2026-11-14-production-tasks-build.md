# Production rebuild, batch 2: Tasks (build plan)

Decision: `docs/adr/0084-production-is-rebuilt-around-the-production-order.md`
(decision 7). Approved screen: the `#v-tasks` view in
`docs/redesign/mockups/production-orders.html` (sample data). Batch 1 (Orders)
is merged: `app/modules/production/orders/`,
`frontend/src/departments/production/next/`, and its contract
`docs/plans/2026-11-14-production-orders-build.md`.
Branch: `claude/production-tasks`.

## Scope

One Tasks screen at `/production/next/tasks`: every piece of work Production
has open, generated from the orders, plus tasks added by hand.

Not in this batch: reminders or notifications, the platform's Today page,
Incoming, Suppliers, Overview. The old framed tab and its `production_task`
table are untouched and nothing is carried over from it.

## Where tasks come from

**Generated tasks are never stored.** They are worked out on each read from
the open orders, by one server function beside `next_action` in
`services/orders.py` (reuse `Facts`, `next_action`, `flags`). For each open
order, in this order, without repeating the same work twice:

1. **The order's next action** (`next_action`): what, who, by when.
2. **Each delivery whose two counts differ and has no reason:** "Give a
   reason for N missing pieces" (or "N more than shipped"), who `qc`, due the
   day Khazenly counted it.
3. **Each delivery shipped but not counted:** "Enter Khazenly's count for
   delivery N", who `qc`, due the day after it shipped.
4. **Fix pieces not yet back** once the final inspection is done: "Receive N
   fix pieces", who `factory`, due the order's delivery date.

Where an item in 2 to 4 is the same work as the order's next action (the
warehouse stage already says it), it appears once.

Each generated task carries:
- `key`: stable for the same work (e.g. `order:12:stage:cutting`,
  `delivery:7:reason`, `delivery:7:count`, `order:12:fix`),
- `title` (plain words, sentence case), `who` (`owner` | `qc` | `factory`),
- `due` (`YYYY-MM-DD` or null), `order` (`id`, `code`, `style_name`,
  `colour`), `stage` (the stage key it belongs to, or null),
- `waiting_on`: the supplier's name when `who = factory`, else null,
- `since`: the day it started waiting (the last stage done, or the delivery's
  date), for "waiting 3 days",
- `open`: which form the order page should open: one of `sample`,
  `stage:<key>`, `cut`, `inspection`, `delivery`, `delivery:<id>`,
  `delivery-reason:<id>`, `settle`, or null when there is nothing to fill in
  (waiting on the factory).

## Tasks added by hand

New table `prod_task`: `id`, `title` (1..200), `due_on` (date, nullable),
`order_id` (nullable FK `prod_order.id`), `note` (nullable text), `done_at`,
`done_by`, `created_by`, `created_at`, `deleted_at`. One migration, continuing
the sequence after `f6b3d8e10033` (ids end `0034`), with a `downgrade()` that
refuses while any row exists.

A hand-added task is `who = qc` unless it is made with `for_owner: true`
(column `for_owner` bool, default false). It can hang on an order or on none.
It is done when somebody marks it done, and can be reopened. Done tasks drop
off the list; the list can show the last 14 days of done hand-added tasks on
request (`?done=1`). Each write is audited (`production.task_*`, subject
`production:task:{id}`, an `after.summary` sentence).

## Grouping, counts and filters

"Today" is Cairo's date. Groups, by `due`:
- `overdue`: due before today (carry `overdue_days`),
- `today`,
- `week`: within the next 7 days,
- `later`: after that, or no date.

Inside a group: by due date, then order code, then title.

Counts for the filter chips: everything, overdue, `qc`, `owner`, waiting on
suppliers (`who = factory`). The owner sees the whole list; so does the QC
manager. **No task carries money**, for anybody: never put a cost, rate or
amount in a title or note the server writes.

## API (`/api/prod`, same conventions as batch 1)

- `GET /tasks` (`production.view`): `{today, counts, tasks: [...]}`; each
  task has `kind` (`generated` | `manual`), the fields above, `group`,
  `overdue_days`, and for manual ones `id`, `note`, `done`, `for_owner`.
  `?done=1` adds recently done hand-added tasks.
- `POST /tasks` (`production.edit`): title, due_on, order_id, note,
  for_owner.
- `PATCH /tasks/{id}` (`production.edit`): any of those, and `done: bool`.
- `DELETE /tasks/{id}` (`production.edit`): soft delete.

## Screen

Follow the mockup's `#v-tasks`: a header with the counts sentence, the filter
chips with counts, then the four groups (Overdue in the refused colour, Today,
This week, Later), each a surface of rows. A row: the title, the order line
under it (style, colour, code; "waiting on <supplier>"; "Added by hand"),
then who, the date with "N days" when overdue, and one button.

- A generated task's button goes to the order page with the right form
  already open: `/production/next/orders/{id}?open=<open>`. The order page
  must read `open` once on load, open that panel, and clear the parameter.
  Button words come from the form (e.g. "Enter counts", "Record check",
  "Review sample", "Record delivery", "Add reason"). A task with nothing to
  fill in shows no button, or "Open order".
- A hand-added task's button is "Mark done"; it also offers edit and delete.
- "Add task" opens an inline form: title, date, optional order (open orders),
  optional note, and for the owner a "For the owner" tick.
- Buttons a person cannot use are not shown: owner-only forms (sample,
  settle) show "Open order" to the QC manager; a viewer sees no buttons that
  write.
- Phone first: the QC manager uses this at the factory. Separate narrow
  layout by the same JS media query the Orders screens use; 44px targets; no
  horizontal scroll at 390px.
- Add a **Tasks** tab to `ProdTabs` between Orders and Stage days, with the
  count of overdue tasks beside its name when there are any.
- Empty state: "Nothing to do right now." Loading and error states as in
  batch 1.

## Verification

- Backend: `tests/test_prod_tasks.py`: each source of generated tasks, no
  duplicate with the next action, grouping around today, counts, filters'
  data, `open` values, the permission table, the no-money recursive check
  for viewer and staff, hand-added task lifecycle and audit, the migration's
  downgrade refusal. Also keep green: `test_prod_orders`, `test_migrations`,
  `test_reachability` (new routes must be called by the frontend),
  `test_permissions`, `test_several_roles`, `test_production_api`,
  `test_audit_by_department`.
- Frontend: tests for the list, groups and filters, the button per kind and
  per permission, Add task, mark done, and the order page opening the panel
  from `?open=`. `cd frontend && npm test` and `npm run build`.
