# Production: product details, task follow-up, payments (build contract, 19 November 2026)

Branch `claude/orders-tasks-management-52a023`. Owner's request, 19 November 2026:

> In orders when I open the product add the COGS of each product and all its details: colour code,
> suppliers for it, fabric type, pattern file, size chart, print / embroidery type and its width.
> Take away the done tasks in a tab alone by itself. Make tasks filtered by date. In tasks add what's
> the next action and make it updateable if there are any updates. Give each task a deadline to be
> done but it's optional. Add payments section and let me upload images. Make the payment filtered by date.

Reading of the request (engineering decisions, owner may redirect):

- "The product" is the production order's page (`/production/orders/:id`): one order is one style in one colour.
- "Payments section" is a new Production sidebar section, **Payments**, listing every payment to every
  supplier, filtered by date, where a payment is recorded and photos are attached (several per payment).
  It is money, so it is `production.owner` (admin and production manager, ADR 0086) only.

Rules that do not change: money is integer piastres; money keys are **absent** (not null) for anyone
without `production.owner`; the supplier account stays append-only; a write that knows an order locks
the order first, then the supplier; history sentences carry no money.

## 1. Product details on the order page

### Data (migration `f1c2d3e40039`, down-revision `e5b9a3d70038`)

`prod_order` gains, all nullable, all editable by `production.owner` through `PATCH /api/prod/orders/{id}`
(and accepted on `POST /api/prod/orders`), each change recorded in the order's history in words:

| column | type | meaning |
|---|---|---|
| `colour_code` | `String(40)` | e.g. `Pantone 19-0303`, `#2F3A2F` |
| `fabric_type` | `String(120)` | e.g. `Cotton fleece 320 gsm` |
| `decoration_type` | `String(120)` | print / embroidery type, e.g. `DTF print`, `Puff embroidery` |
| `decoration_width_cm` | `Numeric(6,1)` | its width in cm, `> 0` and `<= 999.9` |

Blank text is stored as null. Editable while the order is open (same lock as other order fields).

`prod_order_file` gains `kind String(12) NULL` with check `kind IS NULL OR kind IN ('pattern','size_chart')`.
`POST /api/prod/orders/{id}/files` accepts form field `kind` (`pattern` | `size_chart`, else none).
- `size_chart`: a photo or PDF (the existing first-bytes check).
- `pattern`: photo, PDF, **or any other file** (DXF, PLT, AI, ZIP…) up to 20 MB. A file that is not a photo
  or PDF is stored as `application/octet-stream` and served with `Content-Disposition: attachment`
  (with its name, safely quoted) and `X-Content-Type-Options: nosniff`; photos and PDFs stay `inline`.
  The stored name is the uploaded filename, trimmed to 255 characters.
- The files list (`GET /orders/{id}/files`) carries `kind` on each file.
- Same permission as files today (`production.edit`).

### Order view (`GET /api/prod/orders/{id}`), new keys

For everybody who reads Production:

```json
"product": {
  "colour_code": "…|null",
  "fabric_type": "…|null",
  "decoration_type": "…|null",
  "decoration_width_cm": "12.5|null",          // string, one decimal, or null
  "suppliers": [                                  // who supplies this product, names only, no money
    {"id": "SUP-1", "name": "Nour Factory", "roles": ["Factory"]},
    {"id": "SUP-4", "name": "Delta Fabrics", "roles": ["Fabric"]},
    {"id": "SUP-7", "name": "Print House", "roles": ["Printing", "Accessories"]}
  ],
  "pattern_files": [ {file view} ],               // live files of kind pattern, newest first
  "size_charts":   [ {file view} ]                // live files of kind size_chart, newest first
}
```

`suppliers`: the factory (role `Factory`), the outside print house when `printing = 'outside'`
(role `Printing`), and the supplier of every **non-voided** purchase tied to the order (role = the
purchase's part label: `Fabric`, `Printing`, `Accessories`, `Packaging`, `Other`). One entry per
supplier, roles in that order without repeats; factory first, then by name.

Only with `production.owner`, inside the existing `cost` block:

```json
"cost": { …, "cogs": {
  "per_piece_piastres": 18500,            // = piece_cost (actual where typed, else target)
  "pieces": 480, "pieces_basis": "passed", // passed once the final inspection is done, else cut once cutting is done, else planned
  "total_piastres": 8880000               // per_piece × pieces
}}
```

### Screen

A **Product** card at the top of the order page's side column (before Sizes): colour (name + code
with a small swatch when the code is a `#rrggbb` hex), fabric type, print / embroidery type and width
("DTF print · 12.5 cm wide"), the suppliers with their roles (each links to `/production/suppliers/:id`),
pattern files and size charts (open / download links; upload buttons for `production.edit` while the
order is open). For `production.owner`: **COGS** "EGP 185.00 a piece · EGP 88,800.00 for 480 passed
pieces". "Edit details" (owner, order open) opens a panel with the four fields. Empty values read "Not
set". Same look as the other cards (`OrderCards.tsx`).

## 2. Tasks

### Data (same migration)

- `prod_task.next_action Text NULL` (max 500 characters, blank is null).
- New table `prod_task_update`: `id`, `task_id → prod_task.id NOT NULL`, `text Text NOT NULL`
  (1–2000 chars), `next_action Text NULL` (what the next action was set to by this update, if changed),
  `created_by → user_account.id SET NULL`, `created_at`. Index on `task_id`. Rows are never edited.

`ProdTask.due_on` already exists; it is the **deadline** (optional). Only the words change.

### API

- `NewTask` / `TaskEdit` accept `next_action` (optional). A change is recorded in history.
- `POST /api/prod/tasks/{id}/updates` (`production.edit`) body `{"text": "...", "next_action": "...|null|absent"}`:
  adds an update line; when `next_action` is sent it also replaces the task's next action. Refused on
  a deleted task (404). Allowed on a done task too. Answers `{"task": view}`.
- A manual task's view gains `next_action`, `updates` (newest first: `id`, `text`, `next_action`,
  `created_at`, `created_by` name) and `updated_at` (newest update's time, or null).
- `GET /api/prod/tasks` gains query params:
  - `view=open` (default) | `done`. `open` = generated + manual not done (as today without `done=1`).
    `done` = manual tasks marked done, **all of them** (not only 14 days), newest done first, group `done`.
    The old `done=1` keeps working as today.
  - `from`, `to` (ISO dates, optional, inclusive). For `open`: keep tasks whose deadline (`due`) is
    within the range; a task with no deadline is left out when either bound is given. For `done`: by the
    Cairo date it was marked done. Counts are counted over what is returned.
  - `from > to` is a 422 with plain words.

### Screen

- Two tabs at the top: **Open · N** and **Done · N** (the done count is from the done view's answer;
  load it lazily, show "Done" without a number until loaded). The "Show tasks done in the last 14 days"
  checkbox goes.
- A date filter row: "From" and "To" date boxes and "Clear", plus quick chips "Today", "This week",
  "Overdue" can stay as the existing who/overdue chips. Filter applies server-side (`from`/`to`).
- "Date (optional)" becomes **"Deadline (optional)"** in the form, and rows say "Due 21 Nov" / "No deadline".
- Form gains **Next action (optional)**.
- A manual task row shows "Next: <next action>" under the title, and the latest update ("Update · 2 h ago: …").
  A **Update** button (production.edit) opens a small panel: "What happened" (required) and "Next action"
  (prefilled with the current one); saving posts to `/updates`. The row can expand "All updates (n)".

## 3. Payments

### Data (same migration)

- Drop the unique index `uq_prod_supplier_receipt_live`: a payment can hold several photos.
- `prod_supplier_entry` is untouched (append-only trigger stays).

### API (all `production.owner`; anyone else 403)

- `GET /api/prod/payments?from=&to=&supplier=` → payments (kind `payment`), including reversed ones
  marked `reversed: true` (reversal lines themselves are not listed), newest `paid_on` first:
  ```json
  {"from": "…|null", "to": "…|null",
   "total_piastres": 123400,                     // of the listed, not reversed
   "payments": [{"id": 12, "supplier": {"id","name"}, "amount_piastres": 50000, "paid_on": "2026-11-18",
     "method": "cash", "method_label": "Cash", "kind": "weekly", "kind_label": "Weekly payment",
     "note": "…|null", "reversed": false, "created_by": "name|null",
     "photos": [{"id": 3, "mime_type": "image/jpeg", "size_bytes": 1234, "created_at": "…"}]}],
   "suppliers": [{"id","name"}]}                  // for the filter and the form
  ```
  Date filter on `happened_on`, inclusive; `from > to` → 422.
- Recording a payment uses the existing `POST /api/prod/suppliers/{id}/payments`.
- `POST /api/prod/entries/{entry_id}/photos` multipart `file` → adds one photo (photo or PDF, ≤ 20 MB),
  **without** replacing the others. Same refusals as the receipt. Answers `{"payment": <row as above>}`.
- `GET /api/prod/receipts/{receipt_id}` → the file, inline, nosniff (owner only).
- `DELETE /api/prod/receipts/{receipt_id}` → removes one photo (`deleted_at`); answers `{"payment": row}`.
- The old single-receipt routes keep working: `POST /entries/{id}/receipt` replaces **all** live photos
  with the new one; `GET` serves the newest live one; `DELETE` removes all live ones. The supplier
  page's account line shows `receipt: true` when any photo is live.
- Every photo add/remove writes the supplier's history in words (no amounts).

### Screen (`/production/payments`, sidebar between Suppliers and Stage days, shown only with `production.owner`)

- Head: "Payments", subtitle "N payments · EGP total" for the range.
- Filter row: From / To dates, quick chips "This month", "Last month", "This year", "All"; supplier select.
  Default: this month.
- "Record payment" opens a panel: supplier, amount (EGP), date (default today), method, kind, note, and
  photos (several, `accept="image/*,application/pdf"`, with camera capture on phones). Save records the
  payment, then uploads each photo; a photo that fails says so and leaves the payment recorded.
- A list (table on wide, cards on narrow): date, supplier (link), kind, method, amount, note, photo
  thumbnails (images as small previews loaded from the receipt URL; PDFs as a "PDF" tile); each opens
  in a new tab. "Add photos" and remove (×, with a confirm) on each payment. Reversed payments are shown
  struck through with "Reversed".
- Empty state: "No payments in this period."

## Verification

- Backend: new tests in `tests/test_prod_product_details.py`, `tests/test_prod_task_updates.py`,
  `tests/test_prod_payments.py`; the money-absence recursive test covers the new keys and the payments
  route (403 for staff and viewer); `tests/test_factory_login.py` refuses the factory the new routes;
  head-revision asserts move to `f1c2d3e40039`; the migration upgrades and downgrades cleanly.
- Frontend: tests for the Product card, the tasks tabs/date filter/updates, the Payments screen;
  `npm run build` passes.
- Browser: the three screens on a throwaway local database at 1440 and 390.

## 4. Style picker (added 19 November 2026)

The New order form's style picker offers **draft** products as well as active ones (a style may be
made before it is on sale); archived products are not offered. `GET /api/prod/choices` answers each
product as:

```json
"products": [
  {"id": "111", "title": "Oversized hoodie", "status": "active", "image_url": "https://…|null"},
  {"id": "333", "title": "Winter jacket", "status": "draft", "image_url": null}
]
```

ordered by title. `image_url` is the product's one picture (`product.image_url`), shown small beside
the title; `status` lets the screen mark drafts ("Draft"). An order may be created or edited with a
draft product's id (the check is only that the product is in the product list).
