# Restoring the database from a backup

**Written 11 September 2026, Phase 09C.** Backups have run since ADR 0032 and
nothing described how to get one back. A backup nobody can restore is a file,
not a safety net — and the moment somebody needs this is the worst moment to
work it out.

> **This procedure has been written and not rehearsed.** Rehearsing it needs
> the real bucket credentials and an isolated database, both of which are the
> owner's to provide. Until somebody has run it end to end, treat every step
> here as *believed* rather than *proven*, and do the rehearsal on a day when
> nothing is on fire.

---

## What exists

A container in `ops/backup` runs `pg_dump --format=custom` on a cron of
`0 0 * * *` — **daily at midnight** — and uploads the result to an
S3-compatible bucket. Old dumps are pruned to the newest `BACKUP_KEEP`.

Objects are keyed `<environment>/<timestamp>.dump`, so production's backups
live under `production/` and staging's under `staging/`.

The format matters: **custom, not plain SQL**. It restores with `pg_restore`,
not `psql`, and it can be restored selectively.

## Before you touch anything

**Restore into a new database, never over a live one.** A restore that
overwrites production replaces the thing you are trying to compare against, and
if the dump turns out to be wrong you have nothing left.

**Know what happened after the dump.** A backup is a moment. Any transfer,
approval or correction recorded after that moment is **not in it** and will not
come back with it. `MIGRATION_AND_RELEASE.md` is explicit: restoring an older
backup after new transfers were recorded needs those real-world transfers
reconciled by a person, not by a script.

## Getting a dump

List what is there, newest last:

```
aws s3 ls s3://$BUCKET/production/ --endpoint-url "$ENDPOINT"
```

Download the one you want:

```
aws s3 cp s3://$BUCKET/production/<timestamp>.dump ./restore.dump \
  --endpoint-url "$ENDPOINT"
```

The credentials are the backup service's own `ACCESS_KEY_ID`,
`SECRET_ACCESS_KEY`, `BUCKET`, `ENDPOINT` and `REGION`, readable from Railway.
They are write-and-read keys for the backup bucket; treat them as secrets and
do not paste them into a shell history you keep.

## Restoring it

Into a **new, empty** database:

```
createdb hba_restore_check
pg_restore --dbname="postgresql://.../hba_restore_check" \
  --no-owner --no-privileges --exit-on-error ./restore.dump
```

`--exit-on-error` on purpose: a restore that reports success while having
skipped statements is worse than one that stops, because you will believe it.

## Checking you actually have it

Four questions, in the order they tell you something:

```sql
SELECT version_num FROM alembic_version;             -- which schema
SELECT count(*) FROM payment_transaction;            -- money that moved
SELECT count(*) FROM payroll_snapshot;               -- months agreed
SELECT max(occurred_at) FROM payment_transaction;    -- how recent
```

That last one is the important one: it tells you **what this backup does not
contain**, which is everything after it.

Then confirm the protections came back with the data — a restore that lost the
append-only triggers would let a later mistake erase a trail:

```sql
UPDATE audit_event SET action = 'probe' WHERE false;
```

It must raise `append-only table: audit_event cannot be modified by update`.
A silent success means the triggers did not restore and the database is not
safe to promote.

## If the schema is older than the code

A dump from before a migration restores the schema it had. Bring it forward:

```
DATABASE_URL='postgresql://.../hba_restore_check' \
  .venv/Scripts/python.exe -m alembic upgrade head
```

Every migration this platform ships is additive, and a test holds that
(`test_no_migration_destroys_a_column_or_table_on_the_way_up`), so moving an
old dump forward does not drop anything.

## Rolling a migration back

The head migration's `downgrade` is exercised by
`test_the_latest_migration_can_be_rolled_back_and_reapplied`, and the append-only
triggers are checked after it. So this is tested rather than hoped:

```
DATABASE_URL='...' .venv/Scripts/python.exe -m alembic downgrade -1
```

**Schema rollback is not financial rollback.** Reverting the code cannot unmake
an approval, a transfer or a correction that has already happened. If new money
actions must stop, stop them — and keep read access, because the evidence is
the point.

## What is still missing

- **Nobody has run this.** See the note at the top.
- **No restore of the object store itself.** If the bucket is lost, so are the
  backups; they are not replicated anywhere this repository knows about.
- **No documented recovery-time expectation.** How long a restore takes on a
  real production dump is unmeasured.
