# Approved design parity audit and first correction batch

11 September 2026. Base `2089a1fb25139518c8bb4df7b78a067f3e2b5123`.
**Status: draft, incomplete, not deployed.** The owner asked for the approved
front end, structure, content and behavior, not a new theme over old pages.

## Why the previous implementation drifted

07A's report treated existing features as already matching the export, while the
inline Home chart still lived on `/year`. Layout comments still deferred required
changes to phases now reported complete. The continuation handoff said there was
no implementation left and made visual inspection entirely the owner's task.
Those claims are superseded by the current correction handoff. Tests showing a
component contains a word do not verify its page, position, hierarchy or workflow.

## Screen/action matrix

| Area | Evidence at base | Current correction branch | Still required |
|---|---|---|---|
| Admin shell | Old sidebar style and stacked account links, source + live | Approved geometry, green rounded active items, account menu, compact header | Browser comparison at both desktop reference widths |
| Admin Home | Old large alert blocks and operational KPIs, source + live | Three business cards, payout components, top-sales and content panels, compact notices | Real affected-model progress rows; historical totals contract; visual comparison |
| Models list | Old status/kind/readiness table and invitation content | Unchanged | Approved search/segments/card and table content; setup/detail navigation |
| Model profile | Five tabs absent, source + live | Five sections, existing forms grouped, wardrobe image cards and retry, embedded model targets | Profile hero, exact fields/layout; selected-month terms; complete performance and payment summaries |
| Product catalogue | Catalogue and paging exist | Unchanged | Reference layout, scope/search/counts, state restoration |
| Product detail | Inline promotion form and grouped roster | Unchanged | Approved secondary promotion editor, roster fields and shipment/detail navigation |
| Promotion guidance | Eligibility service exists | Unchanged | Both sides visually match; passive eligible cards; no completion/target trigger |
| Admin Targets | Older bulk editing grid | Existing revision-checked editor can render one model in profile | Exact approved main grid and editing layout; preserve latest owner-approved bulk-year behavior |
| Admin Payments list | Server totals/filter states exist; row action passes selected model in router state | Month/affiliate links can filter selected model | Approved row content and payment-detail entry point, reload-safe selection |
| Payment detail/receipt | Authorized destination reveal and ledger safeguards exist | Unchanged | Full approved detail hierarchy, saved InstaPay URL button, receipt context and proof |
| Terms editor | Month-history engine exists | Edit Terms reachable in profile Payments | Exact month selector/editor behavior and history locks, current vs selected terms |
| Admin Settings | All settings panels stacked | Six selected subsections with existing working controls | Historical readiness summary/finalization and exact subsection layouts |
| Model header/navigation | Extra arrow month bar; Ranking had no picker | Compact header picker; Ranking included; back headers; Year/Grow redirect Home | Exact spacing and secondary back destinations on phone |
| Model Home | Old month page, inline calculation/targets, separate Year/Grow links | Compact hero, inline chart, calculation page, separate payment state | Authoritative current performance/delivery counts/Uses history; exact visuals |
| Model Orders | Legacy commission states and prose | Home chips filter orders; stale response protection; filler paragraph removed | True delivery states, pending amounts, correction explanation and approved row design |
| Model Wardrobe | Received grid first, requests last, no top sellers | Unchanged | Personal top sellers and featured cards above owned/incoming rows; real images |
| Model Targets | Functional target screen exists | Unchanged | Full reference comparison including history/outcome-only states |
| Model Ranking | Server ranking exists; peers anonymous in UI | Month picker added | Approved rows, name visibility contract, brief basis copy; never peer sales |
| Model You/details/payout/notifications | Long account form rather than approved menu/secondary pages | Secondary header only | Approved menu and each subview, cancel/save, reauth and theme persistence |
| Receipt -> calculation | Query links to Home can retain another selected month | Explicit calculation route reads eligible requested month | Browser check including partial/multiple settlements and deep links |

## Financial implementation gaps are release blockers

Read the current handoff's C2. `calculate_month` remains the legacy path; preview
alone includes pending base. `GO_LIVE_MONTH=2026-09` is not proof of activation.
Order commission states must not be renamed delivery states. The chart's Uses
series has no backing field in `/api/me/year` yet; unavailable is deliberate in
this draft. Historical null earnings and source performance vs snapshots require
end-to-end fixes. No backend calculations, snapshots, transfers or proofs were
changed by this correction batch.

## Verification

- Authenticated live staging: admin Home, one model profile, Payments.
- Reference: exact HTML source and exported admin thumbnail.
- Modified branch: TypeScript/Vite production build passed; 270 frontend tests
  passed across 10 test files. `git diff --check` passed.
- New chart tests: no months, one point, all zero, missing/invalid samples.
- New header tests: Ranking eligible month selector and calculation back header.
- Receipt-link test updated for its explicit calculation destination.
- No modified-branch browser screenshots: local browser navigation was blocked.
- No completed live model session and no backend test run. The local environment
  lacks PostgreSQL/application Python dependencies. Do not substitute a live database.

Completion requires all rows above to have verified outcomes, not merely a green
build. No merge/deployment is represented as authorized by this report.
