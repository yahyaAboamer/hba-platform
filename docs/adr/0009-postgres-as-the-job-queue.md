# 0009. Postgres is the job queue; no Redis

**Status:** Accepted
**Date:** 2026-08-23

## Context

Webhook processing, historical imports and reconciliation all need background
work. The specification says "no queues", meaning no additional infrastructure
against a stated budget of about ten dollars a month.

That must not be read as "background work may vanish when the service restarts".
A dropped import or a lost webhook is a silent data gap, and silent gaps in
order data become wrong payouts.

## Decision

Postgres is the queue. `background_job` holds the work, and leasing uses
`SELECT ... FOR UPDATE SKIP LOCKED` so concurrent workers take different rows
rather than contending for the same one.

Each lease carries an expiry. A worker that crashes mid-job loses its lease and
the job is picked up again rather than stalling forever.

A job that exhausts its retries is marked failed and **left in place**, visible
in the operational view. It is never deleted and never retried indefinitely: a
silently dropped job is worse than a visible failed one, because nobody learns
the work never happened.

The worker runs inside the API process. With one replica that is simpler and
cheaper than a second service, and because jobs are leased rather than assigned,
splitting it out later requires no change to the queue.

## Consequences

Throughput is bounded by one process polling a table. At tens of thousands of
orders a year that is ample; it would not be if volume grew by two orders of
magnitude.

Succeeded jobs accumulate and need periodic pruning. Recorded in
`docs/limits.md`.

Polling adds a small constant query load, mitigated by sleeping only when idle
so that a backlog drains at full speed.

## Alternatives considered

**Redis with RQ or Celery.** The standard answer. It adds a paid service, a
second thing to operate, and a second place state can be lost.

**In-process asyncio tasks with no persistence.** Free, and loses every queued
job on restart - which on Railway happens on every deploy.
