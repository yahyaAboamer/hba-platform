# Batch report — Phase 09, rehearsal and release

Date: 11 September 2026.

Branch and base/current commit: `phase09/rehearsal-and-release`, based on
`main` @ `64242f5`.

Requested scope: **09A and 09C.** Rehearse the historical reconstruction and
transition; then produce a reviewed release — exact commit, migration plan,
totals reconciliation, evidence, environment ownership, and a verified
backup/restore and rollback procedure.

**09C explicitly does not authorise a deployment**, and none was performed.

Delivered behaviour: **D01 is answered and closed**, the rollback nobody had
ever run is now tested, and the restore procedure that did not exist is
written.

---

## Review

### D01, and why answering it changed no code

D01 has been open since the package was written, and Phase 09 could not
describe a transition without it.

**September 2026 is the first month the platform pays for.** Everything before
it was settled outside: still calculated, approved and frozen, so a model opens
March and sees what March was worth — and never payable, because its balance is
zero by construction and the ledger refuses a transfer against it.

**Production was already configured that way.** `GO_LIVE_MONTH` is `2026-09`
there. So the decision is *no change*, and recording it is the point: the
setting was a default nobody had ratified, and it is now a decision somebody
made.

The history rule likewise matched the code exactly:

> For models created before 2026, we show them the history till January 2026.
> And anyone created after 2026, we show him starting from his starting month.

That is `max(collaboration_start_month, PLATFORM_START_MONTH)`, which
`months_for` already did. **Now it is held by tests** rather than being a
behaviour nobody had checked against an intention.

### The rollback nobody had ever run

Every migration in this repository has a `downgrade()`. **Not one of them had
ever been executed.** A rollback procedure nobody has run is a paragraph, not a
plan, and the moment somebody needs it is the worst moment to discover it
raises.

`test_the_latest_migration_can_be_rolled_back_and_reapplied` now takes the head
migration off and puts it back, and a second test proves the **append-only
triggers survive the round trip** — asserted by trying an update *and* a delete
that must both be refused, rather than by counting triggers, because a trigger
that exists and does nothing would pass a count.

Both restore the schema in a `finally` whatever happens. A test that leaves the
schema half-migrated poisons every test after it, which is not hypothetical: it
happened on 10 September and cost an hour chasing failures that were not real.

### Every migration is additive, and one is not

AC64 asks for no live-data loss. `test_no_migration_destroys_a_column_or_table_on_the_way_up`
reads the migration files and fails on a `drop_column` or `drop_table` in an
upgrade — from the files rather than the database, so it fails on the change
that introduces one rather than after it has run somewhere.

It found the one real exception immediately: `attributed_order.needs_review`,
dropped when delivery became final and nothing was held any more. That is
**recorded by name in the allow-list with its reasoning**, not excused. A name
there is a decision somebody made; a name absent is an accident.

### The restore that was never written down

Backups have run daily since ADR 0032 — `pg_dump --format=custom` to an
S3-compatible bucket, pruned to `BACKUP_KEEP`, keyed `<environment>/<timestamp>.dump`.

**Nothing described how to get one back.** `docs/runbooks/restore.md` now does:
finding a dump, restoring into a *new* database rather than over a live one,
the four queries that tell you what you actually have — and the one that
matters most, `max(occurred_at)`, because it tells you what the backup **does
not** contain.

It also checks the append-only triggers came back, since a restore that lost
them would let a later mistake erase a trail.

**The runbook is written and has not been rehearsed**, and it says so at the
top. Rehearsing needs the real bucket credentials and an isolated database,
both of which are the owner's to provide. Believed, not proven.

### What the rehearsal asserts

`tests/test_release_rehearsal.py` holds the properties a transition must have
**whatever D01 turned out to be**, so the only new thing when it arrived was
the boundary itself:

- a month before the boundary is worth something and owes nothing (AC13);
- **no transfer can be recorded against one** — the refusal lives in the ledger,
  so no import, however well meant, can go around it;
- a month after the boundary is ordinary, so the rule is a boundary and not a
  blanket;
- readiness read twice says the same thing and writes nothing (AC14, H06);
- approving the same historical month twice is refused (AC64);
- an order cannot be moved between months by a later sweep — **the database**
  refuses it, not a service (AC23).

One test I wrote and deleted: duplicate ingestion. It was written against a
helper that inserts rows directly, so it proved the helper worked and nothing
about the platform. The real upsert path already holds it in two places, and a
comment now says where.

### What the owner should try

Nothing new to look at — this batch is tests, a runbook and a decision record.
**What is owed is the walk-through**, which is 09B and is yours: nine batches
of merged screens have never been seen by a person.

### Approved-design deviations and reason

**None.** No screen changed.

### Confirmation needed before the next dependent decision

**None blocking.** D02, D09 and D10 remain open and none of them stops a
release: D02 preserves today's rounding, D09 is a correction case that does
nothing automatic, D10 is about finance accounts that do not exist yet.

---

## The release candidate

### Exact commit

**`64242f5`** — `main`, Phase 08 merged. Staging is deployed and healthy on it.

### What production would gain

`origin/production` is at **`b6abcf5`**, seven commits behind: **07A, 07B and
Phase 08**.

**One migration: `c93f2a17d4e8`** — `notice_mute`. A single new table, no change
to an existing one, no backfill, and a real `downgrade` that drops it. Nothing
before it was muted, so there is nothing to migrate.

Promoting is a clean fast-forward:

```
git push origin main:production
```

### Migration and backfill plan

**No backfill is required.** Every phase since 03 has added exactly two
migrations and both are additive: `1c4b06a5f8d2` (payment operation key,
nullable and unique) and `c93f2a17d4e8` (notice mute).

Migrations run in `docker-entrypoint.sh` on deploy, not on `uvicorn` start.

### Totals reconciliation

**No figure changes.** Nothing in 07A, 07B or 08 alters what a month is worth:
the owner's breakdown is carved out of the existing payout, product analytics
read line items, and the notice work touches no money at all. A model's
approved months are frozen and untouched.

The one thing that *will* look different is **product analytics reading thin
for past months** — line items were never fetched for commission orders before
07A, so those figures start from now. A resync fills them in.

### Test and visual evidence

| Check | Result |
|---|---|
| Full backend suite | **1885 passed in 302.61s**, exit 0 |
| `cd frontend && npm test` | **256 passed**, exit 0 |
| `cd frontend && npx tsc --noEmit` | exit 0 |
| `cd frontend && npm run build` | exit 0 |
| Migration rollback and reapply | **tested**, with triggers checked after |

**Visual evidence: none.** Automation cannot sign in to this platform, and that
has been true for every batch. **Nine batches of merged screens have never been
looked at by a person** — the financial rules preview, the approve flow with
its staleness refusal, corrections, the month-end payment journey, receipts,
Targets, Ranking, the owner's Home and the notice controls. That is 09B, and it
is the single largest piece of unfinished acceptance in this project.

### Environment and import ownership

- `main` deploys **staging**; `production` is a fast-forward of `main`.
- **They share one Shopify shop**, so a bulk import must never be started from
  staging.
- `GO_LIVE_MONTH`: staging `2026-08`, production `2026-09` (D01).
- Backups: daily, per environment, to object storage.

### Rollback and roll-forward

**Schema rollback is tested.** `alembic downgrade -1` takes `c93f2a17d4e8` off
and the triggers survive it.

**Financial rollback does not exist and cannot.** Once a real approval, transfer
or correction has happened, reverting code cannot unmake it. If new money
actions must stop, stop them and keep read access — the evidence is the point.
Restoring an older backup after new transfers were recorded needs those
transfers reconciled by a person.

---

## Engineering evidence

### Files changed

| File | Change |
|---|---|
| `tests/test_migrations.py` | 3 new: rollback and reapply, triggers after it, and the additive property |
| `tests/test_release_rehearsal.py` | **New.** 9 |
| `docs/runbooks/restore.md` | **New.** The restore procedure, and what has not been rehearsed |
| `docs/redesign/decisions/D01-…` | The decision, and why it changed no code |

**No migration and no application change.** This batch adds tests, a runbook
and a decision record.

### No real credentials or personal data in evidence

The runbook names the environment variables the backup service already uses and
contains **no credential values**. Every fixture is synthetic.

---

## Continuation

### Remaining limitations

- **The restore has not been rehearsed.** Written, not proven.
- **No off-site copy of the backups.** If the bucket is lost, so are they.
- **No measured recovery time** on a real production dump.
- **09B is not done**, and it is not something an agent can do here.

### Decisions recorded

**D01 closed** — `decisions/D01-september-is-the-first-month-we-pay.md`. Open
set is now **D02, D09, D10**.

### Exact next batch and prompt

**09B — full product acceptance.** `docs/redesign/prompts/09_REHEARSAL_AND_RELEASE.md`,
**09B only**. It is a walk-through of every screen in both roles on a real
device, and it needs a person.

### Live deployment or data changes

**None.** 09C does not authorise a deployment and none was performed.
`production` remains at `b6abcf5` until the owner promotes it.
