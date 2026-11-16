# Production rebuild, final batch: start from zero and retire the framed tab (plan)

Decision: `docs/adr/0085-production-starts-from-zero.md`
(accepted 16 November 2026). Branch:
`claude/production-switch-over`. It removes things: built only on the owner's
go-ahead, merged only on the owner's go-ahead, deployed to production only on a
separate one.

## The owner's answers (16 November 2026)

- Remove all the old Production tab's data; start from zero.
- Keep the 17 suppliers and their categories (they are the new Suppliers
  list).
- Export a backup file before anything is removed.
- Reading production's old records read-only to plan: allowed (done: same
  counts as staging, the activity list 171).

## What goes

| Kind | Staging | Production | How |
|---|---|---|---|
| Old orders, samples, tasks, styles, phases, activity, QC, documents, stage proposals, fixed lists | 53, 31, 32, 40, 2, 165, 0, 0, 0, 3 | 53, 31, 32, 40, 2, 171, 0, 0, 0, 3 | Backup file, then the tables are dropped by migration `…0038` |
| The framed app | `production-ui/`, `/production-app`, `ProductionScreens` (the frame), `own: true`, the strip and its CSS | same | Code removed |
| The old API | `/api/production/*`, `app/modules/production/api.py`, `actions.py`, `state.py`, its error handler | same | Code removed |
| Build and CI | the `production-ui` CI job, the Dockerfile build steps, `.gitignore` lines | | Removed (the CI job is also removed from branch protection if required there) |
| Permissions | `production.qc`, `production.payments` | | Removed; role sets, Team access screen and fixtures updated |
| Old import | `scripts/production_import.py` and its tests | | Removed |
| Old tests | `tests/test_production_api.py`, `ProductionFrame.test.tsx` | | Removed; the one access-words test moves to `test_permissions` |

## What stays

`production_supplier`, `production_supplier_category`, every `prod_*` table,
the audit log, the bucket's files, the typical stage days.

## The work, in order

1. **Backup (staging)**: a read-only export of every old table to one file on
   the owner's machine, outside the repository (a private folder; its path is
   recorded in the handoff, never committed). Checked by reopening it and
   comparing row counts. Taken right before the merge.
2. **Migration `…0038`**: drops the old tables, children first, keeping the
   two supplier tables and every foreign key the new tables hold to
   `production_supplier`. Its `downgrade()` recreates them empty. Every head
   pin in the tests moves to it.
3. **Native department**: `/production/next/*` becomes `/production/*` (about
   twenty files and their tests), `/production/next/...` and the old
   `/production/<page>` addresses redirect; the department gets its sidebar
   sections (Overview, Orders, Tasks, Incoming, Suppliers, Stage days);
   `own: true`, the frame, the strip and their CSS go; the factory desk keeps
   working.
4. **Removal** of the old app, API, CI job, Docker steps, permissions, import
   script and tests listed above.
5. **Verification**: the whole backend suite (`run-suite.sh`, in the
   foreground), `npm test` and `npm run build`; the migration up and down on a
   throwaway copy; a browser check at 1440 and 390 as owner, QC manager and
   factory, including the old addresses redirecting; an independent review
   of the removal (nothing still imports or calls what was removed; the
   suppliers' foreign keys intact).
6. **Production**, later and only on the owner's separate go-ahead: backup of
   production's old records immediately before the deploy, then the deploy.
