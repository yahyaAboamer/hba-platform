# 0065. One application, arranged by department

**Status:** Accepted — owner, 25 October 2026, with the architecture proposal of that day. **Not built yet.**
**Date:** 2026-10-25
**Builds on:** ADR 0009 (Postgres is the job queue), ADR 0032 (backups in their own container), ADR 0034 (a second service splits staging from production)

## Context

The platform began as the affiliate programme's tool and is becoming HBA's
operating system: Inbox and Operations have joined Affiliates, Production is
next (ADR 0069), and Finance and People are expected after it.

What exists on 25 October 2026:

- **One deployable.** `app/main.py` serves the API and the built frontend from
  one FastAPI process, which is what keeps hosting inside the budget.
- **The background worker runs inside that process**, in three lanes (`main`,
  `operations`, `inbox`, `app/worker.py`), so a backlog in one never delays
  another. Jobs are leased (ADR 0021), so the worker can move to its own
  process without any change to the queue.
- **One replica per environment** (`railway.json`), migrations run on start
  (`docker-entrypoint.sh`), backups run in their own container (ADR 0032), and
  staging and production are separate services (ADR 0034).
- **The newer departments are already self-contained folders.**
  `app/services/inbox/`, `app/services/order_ops/` and
  `app/services/shopify/` import only their own code and the shared plumbing
  (jobs, audit, the Shopify client). The affiliate side, the oldest, is spread
  flat across `app/services/` and `app/api/`.

Almost everything HBA does touches the same order. Its confirmation (Inbox),
its delivery (Operations), its model's commission (Affiliates) and later its
cost (Finance) are four departments looking at one thing. The team is the owner
and AI-assisted engineering, not a group of teams that need to ship apart.

## Decision

**The platform stays one application, one backend and one deployable per
environment. Departments are walls inside the code, not separate services.**

- Each department gets one folder holding its API routes, tables and logic:
  `app/modules/inbox`, `app/modules/operations`, `app/modules/affiliates`,
  `app/modules/production`, and later `finance` and `people`. Shared plumbing
  (identity and access, audit, money, the job queue, the Shopify connection,
  mail, notifications) stays in a shared core.
- **A department calls another only through that department's public
  functions**, never by reading or writing its tables directly. An automatic
  check in the test suite (import-linter) fails when one does.
- The move into folders is **pure relocation**: no behaviour changes in the
  same change, so the existing tests prove nothing moved but the files.
- **Infrastructure stays as it is:** one Railway project (`hba-platform`, in
  the `HBA_Server` workspace), staging and production as separate services, one
  app service per environment, plus Postgres, the backup container and the file
  bucket.
- **The worker moves to a second service only when there is a measured
  reason**: the website needs more than one copy running, or jobs are seen
  slowing pages. It is then the same code started with the web part switched
  off (`WORKER_ENABLED`), not a separate codebase. ADR 0009 stands: no Redis or
  other queue.

## Consequences

- One deploy carries every department. A broken deploy breaks all of them at
  once, so the safety net has to be automatic: tests and the frontend build run
  on every change (CI does not exist yet and is the first thing built under this
  decision).
- Moving the affiliate code into its folder touches hundreds of imports. It is
  done once, as its own change, while nothing else is moving.
- The import rule adds friction: a quick fix that reaches into another
  department's table is refused and has to go through that department's
  function instead. That friction is the point.
- Departments cannot be scaled separately. At HBA's volume nothing needs to be;
  the worker split above is the one lever, and it is already prepared.

## Alternatives considered

- **A separate service per department.** Each cross-department read (the order
  page, Today, search) becomes a network call that can fail and data that can
  disagree, plus a deploy, a login and a bill per service. It suits many teams
  shipping independently; HBA has one.
- **A separate Railway project per department.** Separate bills, credentials
  copied between projects, and database access across projects that Railway
  makes awkward.
- **Keep the flat layout without walls.** Cheapest today; with six departments
  it becomes the tangle where a change to one breaks another nobody was
  looking at.
