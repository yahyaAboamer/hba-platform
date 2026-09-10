# Implementation status — update after every batch

Package prepared: 9 September 2026. Phase 00 completed 9 September 2026.

- **Updated after the Phase 05A fix-up, 10 September 2026.** This replaces the stale
  Phase 01/02 summary previously at the top of this file.
- Started on clean local `main` at the required completed commit
  **`8ad14a6cd7453bc8140d52b6f5c64faf91927b67`**. Ancestor check passed.
- **05A branch:** `phase05a/pending-inclusive-earnings`, ending at `6f69bdd`.
  The original batch is `5320fd6`, untouched; the review fixes are `8a20ca5`.
- **05B branch:** `phase05b/immutable-approval`, based on `6f69bdd` — 05A is
  not merged to `main`, so 05B builds on it rather than around it. Neither is
  merged, deployed or promoted.
- **05A and 05B implemented and verified locally; review and visual acceptance
  pending for both.** Read `reports/05A-pending-inclusive-earnings.md` and
  `reports/05B-immutable-approval.md` before continuing.
- **05A and 05B are merged to `main` and deployed to staging *and* production**
  on the owner's explicit instruction, 10 September. Both environments healthy
  on `9cbfcdb`; production took 39 commits and 5 migrations in one promotion.
  **Neither has been seen by anybody** - no rendered review of the financial
  preview, the approve screen or the retired reopen page.
- **05C is implemented and unmerged**, on `phase05c/late-failure-corrections`.
  It closes the gap below, so that gap is now historical rather than live.
- **05B retired reopening.** `POST /api/payroll/{month}/reopen` answers 409 and
  the button is gone; everything that *reads* reopened history still works, and
  the months already in that state are untouched. Between 05B and 05C there
  was no way to change an agreed month at all; **05C closes that**, and until
  it merges, production has 05B's retirement without 05C's replacement. Nothing
  real is exposed: no model is onboarded.
- Staff can open **Models → model → Financial rules preview**. It uses the
  real earnings API with `rules_preview=true`, counts pending + delivered in
  the source month, and shows legacy allocations separately. **No live policy
  switch:** existing approval, reopen and payment paths remain legacy pending
  05B/05C and D01. No new financial write endpoint or migration.
- Verification: **1769 backend tests passed**, final full run **383.46s**
  using `.venv/Scripts/python.exe -m pytest -q --color=no` (one non-failing
  local cache warning). **233 frontend tests passed**; `npx.cmd tsc --noEmit`
  and `npm.cmd run build` both exit 0. All ran after the final code fixes.
- A separate read-only reviewer returned no findings because it hit an account
  usage limit before completing review. Direct diff review and automated
  checks completed; no independent sign-off is claimed.
- **No screen in 05A has been seen by anybody.** Evidence is limited to a
  sign-in screenshot and three HTTP 200s, followed by a browser inspection
  rejection before any rendered review. See the precise evidence below.
- Package checker: **52 screen/action rows, 64 checks, 19 source assets**;
  raw-byte verification reports **8 CRLF/LF mismatches**. All eight match the
  manifest after LF normalization; design files have no Git changes from the
  starting commit. No assets or manifest were rewritten to hide this result.
- D02 remains open; **existing whole-pound half-up rounding preserved**, as
  instructed by the continuation handoff. D01 still gates live transition.
- Stop for **05A review**. After acceptance, the exact next implementation is
  **05B — Immutable per-model approval**, in `prompts/05_FINANCIAL_RULES.md`.

| Phase | State | Report / commit / evidence |
|---|---|---|
| 00 Baseline | **Complete** | `BASELINE_REPORT.md`; checkout `63c64c3`; 1589 + 104 green |
| 01 UI foundations | **Complete** | `reports/01A-design-tokens.md`, `reports/01B-navigation-and-shells.md`; ADR 0039; `ROUTE_AND_PERMISSION_MAP.md` |
| 02 Models and setup | **Complete** | `reports/02A-model-entry.md`, `02B-profile-and-self.md`, `02C-setup-readiness.md`; migration `d4b81c07af22`; D06 and D07 closed. Finalisation is deliberately Phase 09 |
| 03 Products and wardrobe | **Complete** | `reports/03A…`, `03B…`, `03C-wardrobes-and-requests.md`, `03D-making-the-product-screens-load.md`, `03E-what-was-in-the-parcel.md`; migrations `e7c2a5f1b930`, `f1a93d6c48e2`, `a2f47b8e1c53`; D05 and D11 implemented. Line items are fetched and matching runs live (03E), so a wardrobe fills on real data - **re-run the scan once to fill parcels matched before that** |
| 04 Targets | **Complete** | `reports/04A-targets-editor.md`, `04B-model-targets.md`. The grid carries a revision - a save without one is refused. The model's Targets tab is built (UI24); verification and historical outcomes existed and were verified rather than rebuilt |
| 05 Financial rules | **05A and 05B merged and deployed; 05C awaiting review** | `reports/05A-pending-inclusive-earnings.md`, `05B-immutable-approval.md`. 05A is a read-only pending-inclusive preview; 05B freezes what an approval agreed to, refuses a stale or concurrent commit, and retires reopening. Existing live financial paths otherwise unchanged. `05C-late-failure-corrections.md` closes the gap 05B left: an agreed month that turns out wrong is corrected against rather than unmade. D04 closed. **Phase 06 next** |
| 06 Payments | Not started | Recording/proof/reconciliation already exist and are reusable |
| 07 Performance screens | Not started | Ranking absent |
| 08 Settings and notifications | Not started | Notice dismissal persistence absent |
| 09 Rehearsal and release | Not started | |

## Resume notes

**Runtime commands, seed accounts, test-database identity procedure and the
design-reference server are all recorded in `BASELINE_REPORT.md` §10.** Read
that rather than rediscovering them.

- Migration head: **`a2f47b8e1c53`** (35 revisions), unchanged since 03C —
  **Phases 04 and 05A added none**. Dev DB `hba_platform` and test DB
  `hba_platform_test` both at head. No secrets in this package.
- **Migrations do not run on `uvicorn` startup**, only in `docker-entrypoint.sh`.
  A local run after a new migration needs `alembic upgrade head` first.
- **Verify `current_database()` before running pytest.** `conftest.py` runs
  `DROP SCHEMA public CASCADE`. One pytest process at a time; never a
  concurrent `alembic` against the same database.
- No business question blocked 05A. Its rendered visual acceptance is pending.
  **D01, D02, D03, D04,
  D08, D09 and D10 remain open**; D05, D06, D07 and D11 are closed and recorded
  under `decisions/`. 05A preserved whole-pound rounding without closing D02.
- **Visual acceptance done by the owner on staging, 10 September: 01, 02A,
  02B, 02C, 03A, 03B, 03C, and now 03D, 04A and 04B** - reported as *everything
  works perfectly*, which covers the Products grid's paging and speed, all four
  Targets-grid behaviours (requirements independent of counts, clearing back to
  unrecorded, the two-tab conflict refusal, the cross-month save refusal) and
  the model's Targets tab.
- **03E is the one still unaccepted, and it is blocked on data rather than
  code.** Several models on staging share the phone number `01016215036`, so
  shipping-phone matching returns AMBIGUOUS and attaches nothing - which is the
  designed behaviour, not a failure. The owner is separating the numbers and
  will re-run *Settings → Shopify & data → Match parcels from 2026-01-01*
  before wardrobes can be judged. Until then, an empty wardrobe on staging is
  expected and says nothing about 03C or 03E.
- **05A browser evidence is limited.** DOM snapshots and read-only value
  inspection reported empty fields, while a sign-in screenshot showed typed
  values. The requests `POST /api/auth/login`, `GET /api/auth/me` and
  `GET /api/payroll/2026-09` returned HTTP 200. Automatic approval review then
  blocked further inspection for a usage limit, before any rendered review.
  Neither the screenshot nor those responses proves a rendered 05A screen.
  **No screen in 05A has been seen by anybody.**
- **`read_products` confirmed granted** on the shop, 10 September, after the
  owner deployed a new app version. `/api/operations/shopify-scopes` is the
  route that answers it; there is no button, by design.
- **C: is 99% full (1.9 GB free). There is no CI.** Every check is local.
- `production` is deliberately one release behind `main`. Promoting it is a
  separate, owner-authorised act, not a tidy-up.
- Do not infer acceptance from source files or passing unit tests. Phase 02/04
  have recorded owner acceptance; 05A's rendered review remains separate.
