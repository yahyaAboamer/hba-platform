# 0085. Production starts from zero; the old tab and its records are removed

**Status:** Accepted (the owner, 16 November 2026)
**Date:** 2026-11-16

## Context

ADR 0084 rebuilt Production around the production order and said existing
orders, samples, suppliers and uploads would carry over, and that the framed
tab stays until the new one covers it. Batches 1 to 6 are merged. On 16
November 2026 the old app held, on both staging and production: 53 orders,
31 samples (not linked to orders), 32 tasks (not linked to orders), 40
styles, 2 drop phases, the old activity list (165 on staging, 171 on
production), 17 suppliers in 7 categories, no uploaded documents and no QC
checks. The old order lacks most of what the new one needs (who buys the
fabric, printing, the five cost parts, often the size split).

## Decision

1. **Production starts from zero.** None of the old orders, samples, tasks,
   styles, phases or activity lines is carried over (the owner: "remove all
   the data from the previous production tab, we will start from zero").
   This replaces ADR 0084's "existing orders, samples and uploads carry
   over".
2. **The 17 suppliers and their categories are kept.** They are already the
   new Suppliers tab's list, sorted into sections; `production_supplier` and
   `production_supplier_category` stay.
3. **A backup file first.** Before the old records are removed from an
   environment, they are exported to one private file kept on the owner's
   machine, outside the code. Removal cannot be undone; the file is the only
   copy.
4. **The old tables are dropped** (`production_order`, `_order_stage`,
   `_stage_update`, `_qc_check`, `_document`, `_activity`, `_task`,
   `_sample`, `_product`, `_phase`, `_fixture`) by one migration, run when
   each environment is deployed. Files in the bucket are never deleted
   (there are none from the old app today).
5. **The department becomes native**: `/production/*`, Production's own
   sidebar sections, no frame. `production-ui/`, `/production-app`,
   `/api/production/*`, the old import script and the permissions only the
   old app used (`production.qc`, `production.payments`) are removed. Old
   addresses (`/production/<page>`) redirect to the new screens.
6. The platform's audit log is not touched: it keeps its record of what
   people did in the old app.

## Consequences

- The new Production opens empty apart from the suppliers, their sections
  and the typical stage days; the owner enters current orders as new orders.
- The migration's downgrade recreates the old tables empty; the records come
  back only from the backup file.
- The migration joins the migration and rollback rehearsal list.
- Production (the live site) gets all of this only when the owner authorises
  a production deploy; its backup is taken immediately before that deploy.
