# Returns → E-stebdal "received" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Once a refund row in Operations → Returns is both paid and back (Khazenly *Return Completed*), the platform marks the matching E-stebdal request as received.

**Architecture:** Each row carries a small E-stebdal state, which nothing waits on. A
new service `estebdal_received.py` decides which request to mark and records
the outcome on the row. A background job sends the due rows (switch `auto`),
and a route sends one by hand (`manual` or `auto`). The E-stebdal client gains
two calls: a list filtered by order, and the POST.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, httpx, React + Vite.

**Spec:** `docs/adr/0090-a-settled-refund-is-marked-received-in-estebdal.md`

## Global Constraints

- Switch: `ESTEBDAL_MARK_RECEIVED` = `off` (default) | `manual` | `auto`.
- Due = `paid_on IS NOT NULL AND received_at IS NOT NULL AND estebdal_state IS DISTINCT FROM 'done'`.
- `notifyCustomer`: the row's `estebdal_notify`. It is true for new rows; the migration sets it false on every row already paid.
- Only requests whose `orderNumber` equals the row's `order_number` (compared without `#`) are used.
- Status words: mark `Approved`; wait on `Needs Review` and `Pending Payment`; treat `Processing` and `Closed` as done; `Rejected` and `Cancelled` are dead.
- The POST is sent once, with no automatic retry. The next run re-reads the list, so a lost answer shows up as *Processing* there.
- Never log or audit a customer's name, phone or refund handle, nor the key.
- Undoing paid never calls E-stebdal.

## Review Focus

1. A request was received but its answer was lost (timeout). The next run must see *Processing* and mark the row done, never fail it.
2. Two orders whose numbers contain one another (`#2546` and `#32546`). The `contains` filter returns both, and only the exact match may be used.
3. A row is unpaid, then paid again. A row already done stays done, and is never sent twice.
4. With the switch `off`, the route refuses, the job does nothing, and the tab shows no send button.
5. E-stebdal answers 400 for a request that is no longer Approved. The row is left `waiting` with E-stebdal's message, and nothing is raised to the job.

---

### Task 1: Columns, switch, client calls

**Files:** Create `migrations/versions/d5f7b9c20043_ops_refund_estebdal.py` (down_revision `c4e6a8b10042`). Modify `app/modules/operations/models.py` (OpsRefund), `app/config.py`, `app/modules/operations/services/estebdal.py`. Test `tests/test_order_ops_estebdal.py`.

**Produces:**
- `OpsRefund` columns:
  - `estebdal_state` String(10), null. CHECK in (`waiting`, `choose`, `missing`, `done`).
  - `estebdal_note` String(200).
  - `estebdal_choices` JSONB, default `[]`.
  - `estebdal_request` String(40), the request number.
  - `estebdal_tried_at`, `estebdal_done_at` (timestamps).
  - `estebdal_notify` Boolean, not null, server default true.
  - Partial index `ix_ops_refund_estebdal_due` on `estebdal_tried_at` where `paid_on IS NOT NULL AND received_at IS NOT NULL AND estebdal_state IS DISTINCT FROM 'done'`.
- The migration's upgrade sets `estebdal_notify = false WHERE paid_on IS NOT NULL`.
- `settings.estebdal_mark_received: Literal["off","manual","auto"] = "off"`.
- `EstebdalClient.requests_for_order(order_number: str) -> list[dict]`, each item `{"id","number","order_number","status"}`. It uses the filter `returnNumber contains "<digits>-R"` and keeps only exact `orderNumber` matches.
- `EstebdalClient.mark_received(request_id: str, notify: bool) -> dict` returns `{"status", "cash_refund_recorded", "warnings": [str]}`. It raises:
  - `KeyRefused` on 401/403;
  - `estebdal.Rejected(message)` on any other 4xx, with E-stebdal's `error.message`;
  - `SourceUnavailable` on 5xx or a network error.

Tests use `httpx.MockTransport`:
- the filter sent and the exact-match drop (`#2546` vs `#32546`);
- the POST path, the `x-api-key` header, and the body `{"notifyCustomer": false}`;
- 400 → `Rejected` carrying its message, 500 → `SourceUnavailable`, and exactly one POST attempt.

- [ ] Write the failing tests, then implement, then run `pytest tests/test_order_ops_estebdal.py`. Rehearse the migration up → down → up on the test DB. Commit.

### Task 2: Deciding and sending

**Files:** Create `app/modules/operations/services/estebdal_received.py`. Modify `app/shared/services/jobs.py` (`ORDER_OPS_ESTEBDAL_RECEIVED = "order_ops_estebdal_received"`, added to `OPERATIONS_READS`), `app/shared/services/schedule.py` (every 15 minutes), `app/shared/services/audit_words.py`, `app/modules/operations/services/__init__.py` if handlers register there. Test `tests/test_order_ops_estebdal_received.py`.

**Produces:**
- `mode() -> str`.
- `is_due(row) -> bool`.
- `send(db, row, client, *, choice: str | None = None, actor: UserAccount | None = None, now=None) -> None`. It never raises from E-stebdal; it raises only `returns.Refused` for a bad `choice`.
- `send_due(db, client=None, budget_seconds=None) -> int`: rows due and not tried in the last 15 minutes, oldest tried first, at most 50, stopping after 3 failures in a row or 2 minutes.
- `by_hand(db, refund_id, actor, choice=None) -> OpsRefund`. It refuses with "Sending to E-stebdal is off on this server." when the switch is off, and with "Only a refund that is paid and back can be marked received in E-stebdal." when the row is not due.
- Audit `order_ops.refund_estebdal_received`, after `{number, amount, request, emailed, by_hand}`.

The handler returns at once unless `mode() == "auto"`.

Tests, one per branch of ADR 0090 decision 2, plus:
- the choice branch (a choice must be among the Approved requests);
- a 400 → `waiting` with its message;
- a timeout, then the next run sees *Processing* → `done` with no second POST;
- a row with no order number → `missing`;
- `notify` passed from the row;
- the switch off/manual/auto for the job and `by_hand`;
- undo paid keeps `done`;
- audit text with no customer data.

- [ ] Write the failing tests, then implement, then run them. Commit.

### Task 3: API and tab

**Files:** Modify:
- `app/modules/operations/api.py`: `POST /returns/{id}/estebdal`, body `{"request_id": str | None}`, needs `returns.edit`. 409/422 come from `Refused`, as the other routes do.
- `app/modules/operations/services/returns.py`: `serialise` adds the `estebdal` block `{state, note, request, done_at, choices, due}`; `tab` adds `estebdal_mode`.
- `frontend/src/departments/operations/OperationsReturns.tsx`.

Test: the backend route in `tests/test_order_ops_estebdal_received.py`, covering the permissions (viewer 403, staff ok); the frontend in `__tests__/OperationsReturns.test.tsx`.

On a paid row, the tab shows one line:
- *E-stebdal: marked received (#32546-R1)*;
- *E-stebdal: waiting for Khazenly* (paid early);
- *E-stebdal: <note>* with **Try again**;
- for `choose`, one button per request, *Mark #…-R1*.

The send button appears only when `estebdal_mode !== "off"`. When the row is done, the undo-paid dialog adds "E-stebdal will still show it as received."

- [ ] Write the failing tests, then implement, then run `npm test` and `npm run build`. Commit.

### Task 4: Whole suite, review, PR

- [ ] Run `bash docs/repair/batch-1/run-suite.sh` until nothing remains. Run a code review and fix what it finds. Update the returns plan doc's "Added" section and the handoff. Open the PR; do not merge.
