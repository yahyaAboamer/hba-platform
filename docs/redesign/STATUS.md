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
- Current phase/batch: **01A complete. 01B next.**
- Application files changed: **frontend styling only** (Phase 01A). No API,
  service, model, migration or money code has been touched.
- Runtime tests: green before and after 01A. Backend **1589 passed** (exit 0)
  against a disposable `hba_platform_test`; frontend **104 passed**;
  `npm run build` exit 0. The `1558 / 87` in `REPOSITORY_AUDIT.md` is stale.
- Browser acceptance: **both design references and both halves of the running
  app were opened and compared** (synthetic seed data). Per-screen visual
  acceptance remains owed batch by batch.
- Package integrity: `verify-package.py` → 19 assets, 52 rows, 64 checks,
  **0 issues** (needs `PYTHONUTF8=1` on Windows).
- Current prototype defects: see `DESIGN_REVIEW.md` (V01–V16). Unchanged.
- User business decisions pending: **nothing blocks 01B.** One open question
  from 01A, answerable at leisure: keep the mono face for agreed money (ADR
  0027) or take the design's single face — see `reports/01A-design-tokens.md`.
  D01-D10 stand, each due at its own phase; D06 is confirmed a real card-number
  vs account-number conflict, not a relabel.
- Next instruction: `prompts/01_UI_FOUNDATIONS.md`, **batch 01B only**.

| Phase | State | Report / commit / evidence |
|---|---|---|
| 00 Baseline | **Complete** | `BASELINE_REPORT.md`; checkout `63c64c3`; 1589 + 104 green |
| 01 UI foundations | **01A done, 01B next** | `reports/01A-design-tokens.md`; branch `phase01a/design-tokens`; ADR 0039 |
| 02 Models and setup | **Partly built already** | 02C's terms editor shipped in `63c64c3`; historical readiness and profile fields still owed |
| 03 Products and wardrobe | Not started | Entirely absent from the codebase (UI12–UI20) |
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

- Migration head: `a71f4c9be830` (32 files). Dev DB `hba_platform` and test DB
  `hba_platform_test` both at head. No secrets in this package.
- **Verify `current_database()` before running pytest.** `conftest.py` runs
  `DROP SCHEMA public CASCADE`. One pytest process at a time; never a
  concurrent `alembic` against the same database.
- Blockers: none for 01B. **C: is 99% full (1.9 GB free)**, still, since
  4 September. There is **no CI**; every check is local.
- `production` is deliberately one release behind `main`. Promoting it is a
  separate, owner-authorised act, not a tidy-up.
- Do not infer completion from a screen file or from this package. Phase 02 and
  04 are marked *partly built* because their code was read and run, not because
  a plan said so.
