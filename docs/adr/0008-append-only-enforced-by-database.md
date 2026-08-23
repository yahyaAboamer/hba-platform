# 0008. Append-only is enforced by database triggers

**Status:** Accepted
**Date:** 2026-08-22

## Context

Financial history must be appended, never rewritten. Enforcing that in
application code protects only against the application: anyone with database
access, any future migration, and any admin tool bypasses it entirely.

While implementing the audit log, a probe against Postgres established something
the original design had missed:

```
DELETE:   blocked by the row-level trigger
TRUNCATE: NOT blocked - rows gone
```

A `BEFORE UPDATE OR DELETE ... FOR EACH ROW` trigger **does not fire on
TRUNCATE**. One statement would have erased the entire audit trail silently, and
`TRUNCATE` is precisely what a careless administrator or an attacker reaches
for.

## Decision

Append-only tables carry **two** triggers: a row-level one refusing `UPDATE` and
`DELETE`, and a statement-level one refusing `TRUNCATE`. Both call a single
shared `reject_mutation()` function.

This applies to `audit_event` and `integration_event`, and later to
`payment_transaction`, `payment_allocation` and `payroll_snapshot`.

A foreign key into an append-only table uses `ON DELETE RESTRICT`, never
`SET NULL`. Nulling a column is an `UPDATE`, which the trigger blocks, so
`SET NULL` would fail at an unrelated moment with a baffling error.

## Consequences

**The database cannot be reset, only rebuilt.** A `TRUNCATE` on a referencing
table cascades into the protected one and is refused. Tests needing an empty
database drop and re-migrate the schema, which has the side benefit of
exercising the migration chain from zero continuously.

An account that has done anything cannot be hard-deleted. It is suspended
instead, which is what the specification calls for regardless.

Correcting a mistake means appending a correcting record, never editing the
original.

Rows accumulate permanently. That is the point for an audit trail, and a
capacity question for high-volume tables - recorded in `docs/limits.md`.

## Alternatives considered

**Application-level enforcement.** Protects against the application and nothing
else, which is the wrong threat model for a financial record.

**Row-level trigger only.** What the plan originally specified. It would have
passed its tests and been worthless against the one command that matters.
