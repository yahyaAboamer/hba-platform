# 0032. Backups run in their own container, not the app's

**Status:** Accepted
**Date:** 2026-08-30

## Context

The platform had no backup of its own data. Railway's native Postgres backups
and point-in-time recovery are Pro-plan features; this project is on Hobby.
The only copies of production and staging that ever existed were two manual
`pg_dump` files taken by hand before the Amsterdam region move (ADR 0031), and
they were only ever meant to cover that one operation.

Losing the database means losing every model's earnings history, every
payment record, every audit trail - with twenty people depending on figures
those records back. Nothing about the platform's design assumes this can
happen and be recovered from cheaply; it has to not happen.

## Decision

A backup runs once a day, in **its own Railway service, in its own container,
built from its own Dockerfile** (`ops/backup/`) - not inside the app, not as a
Python module the API imports, not sharing a deploy with anything.

It is built `FROM postgres:18-alpine` - the same major version Railway's
managed Postgres runs - with Python and `boto3` added on top. `pg_dump` is a
Postgres binary, not something psycopg can produce; the tool making the dump
should be the same build as the database being dumped, not "probably
compatible."

It runs as a Railway [cron job](https://docs.railway.com/cron-jobs), daily at
`00:00 UTC` (02:00 Cairo, outside anyone's working hours), for exactly as long
as a dump and an upload take, then exits. Railway does not bill a cron
service between executions - only for the seconds it actually runs.

The dump goes to Postgres's own `--format=custom`: compressed, and restorable
with `pg_restore` alone. It is uploaded to a Railway
[storage bucket](https://docs.railway.com/storage-buckets) - one per
environment, so a staging test dump can never sit in the same place as a
production one - under a key named for the environment and an ISO 8601
timestamp: `production/2026-08-30T000000Z.dump`. After each upload, everything
past the newest 30 (production) or 14 (staging) is deleted; timestamp
filenames sort chronologically as plain strings, so no parsing is needed to
find the oldest.

Every credential - `DATABASE_URL`, the bucket's access key - reaches the
script as a Railway variable reference (`${{Postgres.DATABASE_URL}}`,
`${{backups.ACCESS_KEY_ID}}`), resolved by Railway at deploy time. None of it
is typed into a file this repository holds.

## Consequences

**A second thing to keep working.** A cron job that fails silently is worse
than no backup, because it is trusted. `restartPolicyType: ON_FAILURE` with
two retries covers a transient blip within the same run; a failure that
survives that shows up as a failed deployment in Railway's own dashboard for
that service, which is where an operator needs to go to notice - this project
has no monitoring layer that would page anyone. Recorded in
[docs/operations.md](../operations.md) as the thing to glance at occasionally.

**Cost, measured rather than estimated.** Both databases are a few megabytes
each; a compressed daily dump is under 100 KB. Storage is $0.015/GB-month and
this project's own bucket egress and API calls are free. Thirty days of
production backups plus fourteen of staging is well under 5 MB, total -
effectively free, and tested against the real bucket before ever being
deployed as a scheduled job (five dumps taken and pruned by hand, against the
production database's own Postgres wire protocol, from a local build of the
exact image Railway runs).

**Restoring is a manual act**, deliberately not built as a button anywhere.
Restoring a backup overwrites a live database; the day this exists to be used,
it should not be a click away from an accidental one. `pg_restore
--dbname=<url> <file>.dump` against a freshly downloaded object is the
documented path, and it is a Railway `bucket credentials` command plus a
standard Postgres tool - nothing this project had to build.

## Alternatives considered

**Upgrading to Railway Pro** for native backups and point-in-time recovery.
Rejected for now on cost relative to what it buys at this data size - PITR
matters when losing minutes of data matters, and a once-daily offsite copy is
already a large improvement over the previous zero. Worth revisiting once the
platform is paying twenty people for real and an hour of missing orders would
be a real cost, not a hypothetical one.

**Running the dump from inside the main app**, as a background job the
existing queue already knows how to schedule (ADR 0009). Rejected because it
would make the app's own image responsible for a Postgres binary it has no
other reason to carry, and would let a backup failure and an app failure show
up in the same logs, the same deploy, the same blast radius - exactly the
coupling a backup exists to be independent of.

**A single shared bucket for both environments.** Rejected once it was clear
buckets are already free to create one per environment (Railway's own
guidance for the same reason: isolate test data from what actually matters).
