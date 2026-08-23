# 0021. The worker commits the lease before running the handler

**Status:** Accepted
**Date:** 2026-08-23

## Context

The obvious worker does one job in one transaction: lease it, run the handler,
mark the outcome, commit. Everything is atomic and the code is shorter.

It is also wrong in two ways that only show up under load.

**A long handler holds a row lock for its whole run.** `lease_job` takes
`FOR UPDATE`, so until the transaction commits, the row stays locked and the
Postgres transaction stays open. A Shopify call that takes forty seconds means a
forty-second transaction — which blocks vacuuming, keeps a connection out of a
small pool, and grows the more work there is to do.

**The lease never actually does anything.** Uncommitted, the `RUNNING` status
and `leased_until` are invisible to every other transaction. What protects the
job is the row lock, which dies with the connection. So a crashed worker's job
returns to `pending` by transaction abort, and `leased_until` — the mechanism
built specifically for this — is never exercised. A safety mechanism that never
runs is a safety mechanism nobody knows is broken.

## Decision

**Three transactions per job.**

1. Lease it, commit. The lease is now durable and visible; the row lock is
   released.
2. Run the handler in a transaction of its own.
3. Commit the outcome — success, or a failure recorded after a rollback.

The failure path is the subtle one. A handler that raises has its transaction
rolled back so no half-finished work is committed, and **the failure is then
recorded in a fresh transaction**. Recording it in the rolled-back one would
discard the fact that the job was ever attempted, leaving `attempts` at zero and
the job retrying forever.

## Consequences

Transactions stay short regardless of how long a handler takes.

`leased_until` is now load-bearing, and `lease_reclaimed` fires when a worker
dies mid-job — including on every deploy, since the worker is cancelled with the
API. That is expected, and it means the reclaim path is exercised continuously
rather than only during an incident.

**A job can now be observed mid-flight**, which the one-transaction version hid.
`status = 'running'` with a lease in the future is a job someone is working on;
with a lease in the past it is a job someone died working on. Both are visible in
the table.

**The window between step 1 and step 3 is not atomic**, by design. A worker that
dies after leasing but before finishing leaves a job marked `running` for up to
60 seconds before it is reclaimed. That delay is the price of not holding a lock,
and it is bounded.

This puts a real constraint on handlers: they must never commit or roll back the
session they are given, because the worker owns that boundary. Stated in
`register_handler`'s docstring, and unenforced — recorded in `docs/limits.md` as
an assumption a future handler could break silently.

## Alternatives considered

**One transaction per job.** Simpler, and it makes `leased_until` decorative
while turning every slow handler into a long-running transaction.

**A separate connection for the lease.** Same effect as committing, with an
extra connection held from a pool sized for a free tier.

**Advisory locks instead of a lease.** They release on disconnect, which is
neat, and they are invisible in the table — so a stuck job could not be seen or
diagnosed by looking at `background_job`, which is where anyone would look.
