# Production rebuild, batch 1: Orders (build plan)

Decision: `docs/adr/0084-production-is-rebuilt-around-the-production-order.md`.
Approved screens: `docs/redesign/mockups/production-orders.html` (sample data).
Branch: `claude/production-tab-redesign-c917e8`.

This file is the contract between the backend and the frontend of this batch.
Where it and the ADR disagree, the ADR wins; say so and stop.

## Scope of this batch

The production order: list, create, one order with its ten stages, the size
table (planned to counted), the delivery-date history, deliveries with two
counts, cost per piece, what is owed to the factory, the sample decision,
photos, history; and a settings screen for the typical days per stage.

Not in this batch: the Tasks, Incoming, Suppliers and Overview screens,
purchases, supplier accounts and payments, ratings, the factory's login,
carrying the old orders over. **The old framed Production tab keeps working
untouched**: do not change `production-ui/`, the old `/api/production/*`
endpoints, the old `production_*` tables or `tests/test_production_api.py`.

## Coexistence

- New tables are prefixed `prod_`. No old table is altered or dropped
  (`tests/test_migrations.py` forbids `drop_table` / `drop_column` in an
  upgrade).
- New API prefix: `/api/prod`. New code lives in
  `app/modules/production/orders/` (`models.py`, `api.py`, `services/`).
  Register the models in `app/models/__init__.py` and the router in
  `app/main.py`. Respect the import-linter contract for Production in
  `pyproject.toml` (it may import `app.shared.*`, `app.core.*`, and other
  departments only through their `public.py`).
- New screens are reached at `/production/next/*` inside the existing
  Production department (which stays `own: true` with its iframe at the other
  paths) until the switch-over batch.

## Permissions

- `production.view` (`PRODUCTION_VIEW`): read orders, without money.
- `production.edit` (`PRODUCTION_EDIT`): the QC manager's writes: stages,
  cut counts, inspection counts, deliveries, date changes, photos.
- **New** `production.owner` (`PRODUCTION_OWNER`), held by `admin` only:
  create and edit an order, approve a sample, settle, write off fix pieces,
  reopen a stage, change the stage-days settings, **and see money**.
- Money is filtered on the server: without `production.owner` a response
  carries no cost, rate, value or settlement key at all (omitted, not null).
  A test must prove it for every endpoint that can return money.
- Adding a permission needs no migration, but update the snapshots:
  `tests/test_permissions.py`, `tests/test_several_roles.py`,
  `frontend/src/__tests__/frameHarness.ts` (`HELD`).

## Data model (all new)

Money is integer piastres in `BigInteger` columns named `*_piastres`, with
CHECK constraints (ADR 0002). Sizes are the fixed list `XS S M L XL XXL`.
Stage keys, in order: `plan sample materials fabric_check pattern_check
cutting making final_inspection warehouse settle`.

`prod_stage_days` — the adjustable typical days per stage.
`stage` (PK, one row per stage except `plan`), `days` (int, 0..365),
`updated_at`, `updated_by`. Seeded by the migration with: sample 7,
materials 7, fabric_check 2, pattern_check 3, cutting 2, making 17,
final_inspection 1, warehouse 3, settle 7.

`prod_order`
- `id` (int PK), `code` (unique, `PO-YYMM-NN`, generated, per-month counter),
- `style_name`, `colour` (text, required), `shopify_product_id` (nullable
  string; a style may be produced before it is listed),
- `factory_id` (FK `production_supplier.id`, required),
- `fabric_bought_by` (`hba` | `factory`),
- `printing` (`factory` | `outside` | `none`), `print_supplier_id` (nullable
  FK `production_supplier.id`, required when `outside`),
- `repeat_run` (bool: the sample stage is skipped),
- `target_date` (date), `delivery_date` (date: the current promise; starts
  equal to `target_date`),
- target cost per piece: `target_fabric_piastres`,
  `target_manufacturing_piastres`, `target_printing_piastres`,
  `target_accessories_piastres`, `target_packaging_piastres` (>= 0),
- actual cost per piece, nullable, same five names with `actual_`
  (typed by the owner in this batch; purchases will feed them later),
- `sample_status` (`none` | `pending` | `approved` | `changes`),
  `sample_note`, `sample_decided_by`, `sample_decided_at`,
- `status` (`open` | `closed` | `cancelled`),
- settlement snapshot, written when the owner settles:
  `settled_payable_piastres`, `settled_at`, `settled_by`,
- `notes`, `created_by`, `created_at`, `updated_at`.

`prod_order_size` — one row per size with a planned quantity.
`order_id`, `size`, `planned` (>= 0), `cut`, `passed`, `to_fix`, `rejected`
(nullable until recorded, >= 0). Unique `(order_id, size)`.

`prod_order_stage` — ten rows per order.
`order_id`, `stage`, `position` (1..10), `status` (`todo` | `done` |
`skipped`), `expected_date`, `done_on` (date), `done_by`, `note`.
Unique `(order_id, stage)`.

`prod_order_reason` — why a count dropped.
`order_id`, `kind` (`cut_short` | `rejected` | `to_fix`), `reason` (text),
`quantity` (> 0).

`prod_order_date_change` — the delivery-date history, append-only.
`order_id`, `old_date`, `new_date`, `set_by` (`owner` | `factory`),
`reason` (required), `created_by`, `created_at`.

`prod_delivery` — one batch leaving the factory.
`order_id`, `number` (1.. per order), `kind` (`finished` | `fix`),
`shipped_on`, `counted_on` (nullable), `mismatch_reason` (nullable text),
`created_by`, `created_at`. Unique `(order_id, number)`.

`prod_delivery_size` — `delivery_id`, `size`, `shipped` (>= 0), `counted`
(nullable, >= 0). Unique `(delivery_id, size)`.

`prod_order_file` — photos and files on an order.
`order_id`, `stage` (nullable), `name`, `storage_key`, `mime_type`,
`size_bytes`, `uploaded_by`, `created_at`, `deleted_at`. Reuse the bucket
and sniffing helpers the old Production code uses (`file_bucket`,
`image_type`, the size limit); keys under `production/orders/{order_id}/`.

History is the platform's `audit_event` (`record_audit`, actions named
`production.order_*`, subject `production:order:{id}`), each with a plain
`after.summary` sentence. No table of its own.

## Rules

1. **Create** (owner). Planned total must be > 0. Ten stage rows are made.
   `plan` is done on the day. `sample` is `skipped` when `repeat_run`, else
   `sample_status = pending`. Expected dates are filled backwards from
   `target_date` using `prod_stage_days`: `warehouse` = target date; each
   earlier stage = the next stage's expected date minus the next stage's
   days; `settle` = target date + settle days. A skipped sample takes no
   days. Each expected date can be edited afterwards (owner or QC manager).
2. **Current stage** = the first stage that is neither done nor skipped.
3. **Completing stages** (in order; a stage cannot be completed while an
   earlier one is `todo`):
   - `sample`: the owner approves (`approved`, stage done) or asks for
     changes (`changes`, stage stays todo, note required).
   - `materials`, `pattern_check`, `making`: the QC manager marks done with a
     date and optional note.
   - `fabric_check`: passed or failed with a note; only `passed` completes.
   - `cutting`: cut quantity per size, plus the factory's promised date. If
     total cut < total planned, reasons (`cut_short`) must add up to the
     shortfall. If the promised date differs from `delivery_date`, a date
     change (`set_by = factory`, reason "Promised at cutting") is recorded.
   - `final_inspection`: `passed`, `to_fix`, `rejected` per size. The three
     must add up to `cut` for every size before the stage can be completed.
     `rejected` reasons must add up to total rejected, `to_fix` reasons to
     total to fix. Counts may be saved (not completed) at any time after
     cutting is done, because pieces finish in batches.
   - `warehouse`: completes by itself when every delivery has a Khazenly
     count (every size), no mismatch is without a reason, finished pieces
     **shipped** cover `passed` and fix pieces **shipped** cover `to_fix`
     (pieces still at the factory hold it open, whatever was counted), and
     total counted + mismatch-explained pieces cover them. It is checked after
     every delivery, write-off and inspection save. The owner can **write
     off** fix pieces that will not return (they move from `to_fix` to
     `rejected`, reason required; the `to_fix` reasons shrink with them,
     largest first).
   - `settle`: the owner settles; the snapshot is stored and the order
     closes.
   The owner can reopen the latest done stage (reason required) while the
   order is open.
4. **Deliveries** can be recorded once cutting is done. `shipped` per size is
   entered first; `counted` may come later. A `finished` delivery cannot take
   total shipped above `passed`; a `fix` delivery cannot take total above
   `to_fix`. When both counts exist and differ for any size, the delivery is
   a mismatch until `mismatch_reason` is given. Either the QC manager or the
   owner records both counts.
5. **Delivery date.** Changing it needs a reason and who moved it; the old
   date is kept in the history. Lateness is calculated, never stored:
   - finished (warehouse done): days between `target_date` and the day the
     warehouse stage was done, if positive;
   - otherwise: days between `target_date` and the later of `delivery_date`
     and today (Cairo), if positive.
6. **Money** (owner only).
   - Cost per piece: five parts, target and actual, with totals.
   - Making rate = manufacturing + printing when `printing = factory`, else
     manufacturing; actual if typed, else target.
   - Work value = total cut x making rate.
   - Rejected deduction = total rejected x making rate when
     `fabric_bought_by = hba`; x the whole actual-or-target cost per piece
     when `factory`.
   - Held until fixed = (to fix not yet returned) x making rate.
   - Payable now = work value - rejected deduction - held.
   Shown from the moment cutting is done; frozen at settle.
7. **Next action.** Every open order answers: what happens next, who does it
   (`owner` | `qc` | `factory`), and by when (the current stage's expected
   date, or the delivery's). One server function computes it; the list and
   the order both use it, and the Tasks batch will reuse it. An order also
   carries its attention flags: `late`, `waiting_for_owner`,
   `count_mismatch`, `fix_pieces_due`.

## API (`/api/prod`, JSON, errors as `HTTPException` with `detail`)

Guards on the router (`production.view`); writes add their own guard.
Refusals follow the Operations pattern (`Refused` -> 422, locked -> 409).

- `GET  /orders?status=open|closed` — list rows for the order list.
- `POST /orders` — create (owner).
- `GET  /orders/{id}` — the whole order.
- `PATCH /orders/{id}` — basics, target and actual cost (owner). Who buys
  the fabric, printing and the print house are locked once cutting is done
  (409; the same value sent again is no change); the order's own factory or
  print house may stay even if deactivated, only a changed one must be active.
- `PATCH /orders/{id}/stages/{stage}` — expected date, note.
- `POST /orders/{id}/stages/{stage}/complete` — body depends on the stage.
- `POST /orders/{id}/stages/{stage}/reopen` — owner, reason.
- `PUT  /orders/{id}/cut` — sizes, reasons, promised date (completes cutting).
- `PUT  /orders/{id}/inspection` — sizes, reasons; `complete: bool`.
- `POST /orders/{id}/write-off` — owner; sizes, reason.
- `POST /orders/{id}/sample` — owner; `approved` | `changes`, note.
- `POST /orders/{id}/delivery-date` — new date, set_by, reason.
- `POST /orders/{id}/deliveries` — kind, shipped_on, shipped per size.
- `PATCH /deliveries/{id}` — counted_on, counted per size, mismatch_reason,
  or corrected shipped numbers.
- `POST /orders/{id}/settle` — owner.
- `POST /orders/{id}/cancel` — owner, reason.
- `GET/POST /orders/{id}/files`, `GET /files/{id}`, `DELETE /files/{id}`.
- `GET  /orders/{id}/history` — the order's audit events, newest first.
- `GET  /settings/stage-days`, `PUT /settings/stage-days` (owner).
- `GET  /choices` — what the New order form needs: active suppliers
  (id, name, category) from `production_supplier`, and active Shopify
  products (id, title) from the shared catalogue tables.

Dates travel as `YYYY-MM-DD`; money as integer piastres in keys ending
`_piastres`. "Today" is Cairo's date.

## Verification

- Backend: a new `tests/test_prod_orders.py` covering every rule above, the
  money filter, and the permission table. Run with the disposable database
  only (see `CLAUDE.md`); one pytest process at a time.
- `tests/test_reachability.py`: add the router to `_served()`; routes the
  frontend does not call yet go in `NOT_BUILT_YET`, and come out as the
  frontend wires them.
- Frontend: `cd frontend && npm test` and `npm run build`.
- The migration id continues the sequence after `e5a2c7d90032 (renumbered to f6b3d8e10033 after main gained three)` and has a
  working `downgrade()` that refuses rather than lose rows.
