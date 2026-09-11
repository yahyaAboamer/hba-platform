# Implementation status — update after every batch

Package prepared: 9 September 2026. Phase 00 completed 9 September 2026.

- **Updated after Phase 06A, 11 September 2026.**
- 06A started from a clean `main` at
  **`0f0ce641f81a2209cb211a5f51251e82c5f44159`** on branch
  `phase06a/admin-month-end-payments`. The implementation, report and handoff
  form one local batch commit; it is not merged or deployed.
- **Phase 05 is complete on `main`.** Reopening remains retired; approval
  freezes the reviewed figure; later source changes become a separate
  correction; D04 recovery may reduce a valid earned month to zero transfer.
- **06A is complete in code and awaits review.** Payments is now the admin
  month-end control desk: forecast, approved amount, recorded transfers and
  remaining money stay distinct; inactive obligations remain; house accounts
  are excluded; unresolved corrections across all models are visible before
  another transfer is recorded.
- The payment detail reveals the complete authorised method-specific
  destination, keeps the exact submitted InstaPay URL copyable/openable, records
  amount/date/reference/proof, and lands on the genuine append-only history.
  Opening or copying a destination never records success.
- Duplicate clicks/timeouts reuse one durable `operation_key`. A retry returns
  the original payment and creates no second allocation or notification;
  reusing the key for different transfer facts is refused. Successful proof
  uploads are retained across a failed record attempt.
- A month settled entirely by a carried correction says **No transfer due**
  and creates no zero payment. The approved gross figure remains visible
  separately from the funds required.
- Verification after the final code changes: **1807 full-suite backend tests
  passed**; the **252-test focused finance, correction, destination and
  permission set passed**; **246 frontend tests passed**; `npx.cmd tsc
  --noEmit` and `npm.cmd run build` exit 0. Every pytest command named the
  isolated `hba_platform_test` database and only one process ran at a time.
- Visual evidence is React server-rendering of all three destination shapes
  (exact InstaPay, bank/card, WE Pay wallet) plus source/contract inspection.
  **No live 06A browser walkthrough was performed and no owner acceptance is
  implied.**
- Package inventory remains **52 screen/action rows, 64 checks, 19 source
  assets**. The known eight Windows raw-hash CRLF/LF differences match after LF
  normalisation; no design source was rewritten.
- **C: is 99% full (1.9 GB free). There is no CI.** Every check is local. Free
  memory fluctuated between 0.47 and 0.96 GB during 06A, so the repository's
  killed-pytest cleanup rule remains operative.
- D01, D02, D03, D08, D09 and D10 remain open. D04, D05, D06, D07 and D11 are
  closed. D01 still gates live transition; existing whole-pound half-up
  rounding remains unchanged while D02 is open.
- Stop at the 06A boundary. The exact next implementation is **06B — Model
  payment views and destination changes**, in `prompts/06_PAYMENTS.md`.

| Phase | State | Report / commit / evidence |
|---|---|---|
| 00 Baseline | **Complete** | `BASELINE_REPORT.md`; checkout `63c64c3`; 1589 + 104 green |
| 01 UI foundations | **Complete** | `reports/01A-design-tokens.md`, `reports/01B-navigation-and-shells.md`; ADR 0039; `ROUTE_AND_PERMISSION_MAP.md` |
| 02 Models and setup | **Complete** | `reports/02A-model-entry.md`, `02B-profile-and-self.md`, `02C-setup-readiness.md`; migration `d4b81c07af22`; D06 and D07 closed. Finalisation is deliberately Phase 09 |
| 03 Products and wardrobe | **Complete** | `reports/03A…`, `03B…`, `03C-wardrobes-and-requests.md`, `03D-making-the-product-screens-load.md`, `03E-what-was-in-the-parcel.md`; migrations `e7c2a5f1b930`, `f1a93d6c48e2`, `a2f47b8e1c53`; D05 and D11 implemented. Line items are fetched and matching runs live (03E), so a wardrobe fills on real data - **re-run the scan once to fill parcels matched before that** |
| 04 Targets | **Complete** | `reports/04A-targets-editor.md`, `04B-model-targets.md`. The grid carries a revision - a save without one is refused. The model's Targets tab is built (UI24); verification and historical outcomes existed and were verified rather than rebuilt |
| 05 Financial rules | **Complete.** 05A, 05B and 05C merged to `main` | `reports/05A-pending-inclusive-earnings.md`, `05B-immutable-approval.md`, `05C-late-failure-corrections.md`; immutable approval, retired reopening and explicit corrections. D04 closed |
| 06 Payments | **06A merged; 06B implemented, unmerged** | `reports/06A-admin-month-end-payment-journey.md`, `06B-model-payment-views.md`. 06A is the admin month-end journey - forecast, approved and recorded money kept apart, corrections listed across every model, and a retry-safe transfer record (migration `1c4b06a5f8d2`). 06B is the model's side: a receipt names the destination it actually went to and links to the month that explains it. 06B is frontend only |
| 07 Performance screens | **Complete** | `reports/07-d03-d08-ranking-and-pace.md` (merged), `07A-model-home-and-orders.md`. D03 and D08 shipped the Ranking board and the maintainer's weekly-pace column, both part of 07B. 07A put code uses on her Home and verified the rest. `07B-owner-home-and-analytics.md` finished it: the owner's Home carries the payout broken into commission, salaries and guarantee top-ups, with the parts carved out of the one rounded total so they always add up; plus top sellers, active count and content needing review by reason. Product analytics use real attributed line items and discounted totals (W11) |
| 08 Settings and notifications | **Next** | Notice dismissal persistence absent |
| 09 Rehearsal and release | Not started | |

## Resume notes

**Runtime commands, seed accounts, test-database identity procedure and the
design-reference server are all recorded in `BASELINE_REPORT.md` §10.** Read
that rather than rediscovering them.

- Migration head: **`1c4b06a5f8d2`** (36 revisions). Phase 06A adds one
  backward-compatible nullable, unique payment operation key; existing payment
  rows remain valid. The isolated test database was migrated to head. No
  secrets in this package.
- **Migrations do not run on `uvicorn` startup**, only in `docker-entrypoint.sh`.
  A local run after a new migration needs `alembic upgrade head` first.
- **Verify `current_database()` before running pytest.** `conftest.py` runs
  `DROP SCHEMA public CASCADE`. One pytest process at a time; never a
  concurrent `alembic` against the same database.
- No business question blocked 06A. Its rendered visual acceptance is pending.
  **D01, D02, D03, D08, D09 and D10 remain open**; D04, D05, D06, D07 and D11
  are closed and recorded under `decisions/`. Existing whole-pound rounding is
  preserved without closing D02.
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
- **06A has no live browser evidence yet.** Destination variants were rendered
  in frontend tests and all code/build checks passed, but no person has walked
  the admin month-end journey in a browser.
- **`read_products` confirmed granted** on the shop, 10 September, after the
  owner deployed a new app version. `/api/operations/shopify-scopes` is the
  route that answers it; there is no button, by design.
- **C: is 99% full (1.9 GB free). There is no CI.** Every check is local.
- `production` is deliberately one release behind `main`. Promoting it is a
  separate, owner-authorised act, not a tidy-up.
- Do not infer acceptance from source files or passing unit tests. Phase 02/04
  have recorded owner acceptance; 05A's rendered review remains separate.
