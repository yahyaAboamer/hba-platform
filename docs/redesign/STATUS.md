# Implementation status — update after every batch

Package prepared: 9 September 2026. Phase 00 completed 9 September 2026.

- Repository baseline reviewed by the package author: `025d8a8b059978e6c8113d3c998465be80730f91`.
- **Remote HEAD verified: Yes.** `origin/main` = `origin/production` =
  `025d8a8`. Authentication works from the implementation environment; the
  package author's 404 was theirs alone.
- **B1 answered 9 September: push `main` only.** Done — `origin/main` is now
  `63c64c3`. `production` stays at `025d8a8` deliberately; the branches are not
  level and that is the owner's current choice, not an oversight.
- Active branch: **`phase01a/design-tokens`**, based on `63c64c3`. Not merged.
- Current phase/batch: **02A and 02B complete. 02C next, and mostly pre-built.**
- Application files changed: **frontend styling only** (Phase 01A). No API,
  service, model, migration or money code has been touched.
- Runtime tests: green before and after every batch so far. Backend **1620
  passed** (exit 0) against a disposable `hba_platform_test` - 1589 at baseline,
  24 from 02A, 7 from 02B; frontend **190 passed** (106 before 02B's payout
  label guard, which runs per file); `npm run build` exit 0. The `1558 / 87` in
  `REPOSITORY_AUDIT.md` is stale.
- Browser acceptance: **both design references and both halves of the running
  app were opened and compared** (synthetic seed data). Per-screen visual
  acceptance remains owed batch by batch.
- Package integrity: `verify-package.py` → 19 assets, 52 rows, 64 checks,
  **0 issues** (needs `PYTHONUTF8=1` on Windows).
- Current prototype defects: see `DESIGN_REVIEW.md` (V01–V16). Unchanged.
- User business decisions pending: **none blocking.** 01A's question was
  answered on 9 September — **one typeface everywhere**; ADR 0027's mono rule is
  superseded by 0039 and the glossary entry that promised it was rewritten.
  One thing to look at rather than answer: **the maintainer's tool now defaults
  to dark**, following the approved admin export. One word reverts it.
  D01-D10 stand, each due at its own phase; D06 is confirmed a real card-number
  vs account-number conflict, not a relabel.
- Next instruction: `prompts/02_MODELS_AND_SETUP.md`, **batch 02C only**. Read
  `BASELINE_REPORT.md` §5 first: **the terms editor already exists**, shipped in
  `63c64c3`. What 02C owes is the *readiness* half - per-month setup coverage
  across every eligible month - not the editor.

| Phase | State | Report / commit / evidence |
|---|---|---|
| 00 Baseline | **Complete** | `BASELINE_REPORT.md`; checkout `63c64c3`; 1589 + 104 green |
| 01 UI foundations | **Complete** | `reports/01A-design-tokens.md`, `reports/01B-navigation-and-shells.md`; ADR 0039; `ROUTE_AND_PERMISSION_MAP.md` |
| 02 Models and setup | **02A + 02B done; 02C mostly pre-built** | `reports/02A-model-entry.md`, `reports/02B-profile-and-self.md`; migration `d4b81c07af22`; D06 and D07 closed; 02C's editor shipped in `63c64c3`, its readiness checks still owed |
| 03 Products and wardrobe | **03A done** | `reports/03A-catalogue-and-line-items.md`; migration `e7c2a5f1b930`; `read_products` now required. UI12-UI20 still Not started - 03A is the data underneath them |
| 04 Targets | **Partly built already** | Outcome-only historical targets shipped in `1fe55de` |
| 05 Financial rules | Not started | Commission still pays delivered-only; carry-forward still live |
| 06 Payments | Not started | Recording/proof/reconciliation already exist and are reusable |
| 07 Performance screens | Not started | Ranking absent |
| 08 Settings and notifications | Not started | Notice dismissal persistence absent |
| 09 Rehearsal and release | Not started | |

## Resume notes

**Runtime commands, seed accounts, test-database identity procedure and the
design-reference server are all recorded in `BASELINE_REPORT.md` §10.** Read
that rather than rediscovering them.

- Migration head: **`d4b81c07af22`** (33 files). Dev DB `hba_platform` and test
  DB `hba_platform_test` both at head. No secrets in this package.
- **Migrations do not run on `uvicorn` startup**, only in `docker-entrypoint.sh`.
  A local run after a new migration needs `alembic upgrade head` first.
- **Verify `current_database()` before running pytest.** `conftest.py` runs
  `DROP SCHEMA public CASCADE`. One pytest process at a time; never a
  concurrent `alembic` against the same database.
- Blockers: none. **Visual acceptance is owed for 02A and 02B**: browser
  automation cannot sign in (the typed value never reaches the field, so the
  form's own `required` check blocks it and no request is made). Backend work
  was verified over HTTP instead; the new screens are built and unseen. **C: is 99% full (1.9 GB free)**, still, since
  4 September. There is **no CI**; every check is local.
- `production` is deliberately one release behind `main`. Promoting it is a
  separate, owner-authorised act, not a tidy-up.
- Do not infer completion from a screen file or from this package. Phase 02 and
  04 are marked *partly built* because their code was read and run, not because
  a plan said so.
