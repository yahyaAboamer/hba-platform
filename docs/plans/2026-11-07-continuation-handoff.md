# Where the work is — 7 November 2026 (Batch 4.1 built, not merged)

Supersedes `2026-11-06-continuation-handoff.md`, whose *Working notes* still
hold and are not repeated here. Overall picture: `hba-os-roadmap.md`.

## The exact position

Re-read the remote before describing it: `git ls-remote --heads origin main production`.

| | |
|---|---|
| **Both sites** | Unchanged since 6 November: `origin/main` = `origin/production` = `f9963c7` and later payments PRs (#152–#154); nothing from 4.1 is deployed |
| **Branch** | `claude/batch-4-1-production-planning-102e78`, its PR open, **not merged**: the owner's word is needed to merge and again to deploy |
| **New migration** | `d1b4f0a10025` (Production's tables; the role check lists gain Production's four levels). Joins the release gate's migration/rollback rehearsal list. Rehearsed up/down/up on a disposable database |

## What Batch 4.1 built (ADR 0069, ADR 0076)

- **`production-ui/`**: Production's screens from the ChatGPT export, in their
  own Vite build, served at `/production-app/` and shown inside HBA's frame at
  `/production/`. Every edit to the export is listed in `production-ui/CHANGES.md`.
- **`app/modules/production/`**: the old server's requests under
  `/api/production/…` on `production_` tables, behind HBA's sign-in, each
  change audited (department `production`). Its state answer was compared with
  the live site's on 7 November: every field of every order, task, sample,
  supplier and product matched, in the same order.
- **Team and access**: Production viewer, QC, staff, manager. QC is Production's
  alone. Approving a supplier payment is the owner's.
- **The strip**: HBA's sidebar folds to 64 px while Production is open; a thin
  bar on a phone.
- **`scripts/production_import.py`**: the one-off import with its count-by-count
  and field-by-field reconciliation. Proven on a disposable copy: every count
  and every compared field matched.

## Remaining, in order

1. **Review and merge the PR** (owner's word), then deploy to staging (owner's word).
2. **Import on staging** from a fresh export: the owner asks ChatGPT for a new
   export (the site was edited on 6 November, after the 2 November export).
   The private files stay outside the repository:
   - all of them live in the private evidence folder
     `evidence/production-export-2026-11-07/import-files/` (never in the
     repository): `fixture-lists.json` (made from the export's
     `lib/demo-data.ts` by `make-fixture-lists.mts`, run with
     `node --experimental-strip-types` beside a copy of that file),
     `fixture-texts.json` (the sentences `production-ui/CHANGES.md` lists),
     and `live-state-<date>.json` (the old site's `/api/state`, read the same
     day as the export);
   - rerun the import with `--check-only` after it to see the reconciliation again.
3. **Give the team their levels** in Team and access on staging; check every
   screen side by side against the live site (laptop and phone).
4. **Switch-over**: owner stops editing on ChatGPT, final export, import on
   production, reconcile, owner retires the ChatGPT site.
5. **Batch 4.1b**: supplier accounts that reach only their own orders.
6. Then Phase 3, and the items carried in the 6 November handoff.

## Known, accepted differences

- Three imported orders hold a dash as their dates; they read "—" as before,
  but the hidden ISO copy is empty instead of a dash.
- Uploaded photos now need a signed-in Production holder; the old site served
  them to anyone with the link.
- `update_task` refuses a date that is not one (the old server stored it).
- A confidential document is listed only to Production QC, staff, manager and
  the owner (the old server listed every document to anyone).
- An upload must state its size (`Content-Length`); one that does not is refused.
- The import's `--replace` refuses once Production holds uploaded files.
- Rolling back `d1b4f0a10025` leaves any Production role rows in place behind a
  `NOT VALID` check; revoke them first if the rollback is meant to last.

## Decisions not to reopen

ADR 0076 in full, in particular: tables not a document; the screens keep
their look and behaviour; HBA's sign-in only; QC kept apart from editing;
money in piastres, payment approval owner-only; supplier accounts are 4.1b.
