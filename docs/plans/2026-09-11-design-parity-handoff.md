# Continue the approved-design correction

Date: 11 September 2026. Working branch: `fix/approved-design-parity`.
Base: `2089a1fb25139518c8bb4df7b78a067f3e2b5123`.

**The redesign is not complete. This is a draft correction branch, not a release.**
The owner reported that the implementation retained the old page structure.
Source inspection and authenticated staging inspection confirmed that report.
This file supersedes the completion claims in the previous continuation handoff
and the old phase status table. Historical phase reports describe work performed;
they do not establish fidelity to the approved designs.

## Authority and working method

1. The owner's approved exports are `docs/redesign/designs/Admin Dashboard.dc.html`
   and `docs/redesign/designs/Affiliate Portal v3.dc.html`. Match their page hierarchy,
   content order, navigation, typography, spacing, cards, tables and secondary views.
2. `PRODUCT_RULES.md`, closed decisions and the owner's later instructions control
   behavior. Do not copy prototype bugs, sample money, fixed dates, fake success,
   fake receipts, or demo-only scenario controls into production.
3. Existing API safeguards and ledger invariants remain. Keeping them does not
   require keeping old page components, old navigation, or explanatory paragraphs.
4. Work one batch at a time. Render reference and candidate at the same viewport,
   show the comparison, exercise the actual actions, then record completion.
   A component's existence or an SSR text assertion is not visual acceptance.
5. Do not deploy this branch while any release blocker below is open. Do not
   infer pending-inclusive activation from `GO_LIVE_MONTH` alone.

## What this branch changes so far

- Admin shell: approved sidebar geometry, rounded green selection, account menu,
  compact sticky page header and scrolling workspace.
- Admin Home: sales / payout breakdown / active-model cards; top-sales and content
  panels together; compact notices with separate dismiss, menu and persisted mute.
  Operational details remain reachable through existing destinations.
- Admin model profile: Overview, Wardrobe, Performance, Targets and Payments
  sections. Existing edit/approval protections retained. Wardrobe renders product
  images and sizes, and has explicit loading, empty, error and retry states.
  Embedded Targets restricts its writes to the selected model and retains revisions.
- Settings: six approved subsections; real existing team, sync, policy and audit
  controls. Historical setup links to actual term editors; it does not invent Ready.
- Model Home: approved compact hierarchy, inline Sales/Uses chart, separate
  calculation view and ledger-derived payment summary. Approval no longer says paid.
  Year/Grow bookmarks redirect Home. Ranking gets the eligible month picker.
- Model receipt calculation links now open `/earnings?month=...`; that view reads
  the requested eligible month directly, instead of retaining another Home month.
- Chart geometry covers empty, single-month, zero, missing and invalid samples.
  Missing API values remain missing, not invented zeroes.

**Not a claim of full parity.** Product/target/directory/payment/detail/account
layouts and several data contracts still need the batches below. Current terms in
an admin profile still come from the profile's current-month payload; selecting an
older month does not yet substitute that month's terms. Do not treat this as done.

## Evidence and limitations

- Authenticated staging Admin Home, model profile and Payments were inspected.
  The admin profile had no section tabs; the Home screenshot showed the old
  operational layout. Reference export thumbnail and HTML source were inspected.
- A payment-row URL looked identical across models, but source inspection confirms
  it passes the selected `affiliate_ids` in router state. Normal clicks do not
  approve the wrong model. The dedicated workflow and reload/deep-link behavior
  still need matching to the approved payment-detail view.
- Model sign-in was not verified successfully. Do not claim a model live walkthrough.
- Browser navigation to the local reference server was blocked. The modified branch
  has not been rendered in the supported browser. Visual acceptance remains open.
- Frontend tests/build were run; see report for final counts. No backend files or
  financial data were changed. Backend tests were not run: this workspace lacks
  PostgreSQL and the Python application dependencies. Never run destructive tests
  against a development, staging or production database to get around that.
- At initial inspection GitHub main and production both pointed at the base above.
  Old handoff branch references were stale. A branch SHA is not proof of the running
  Railway build's SHA; verify deployment identity before a release.

## Remaining batches, in order

### C1 — Finish layout fidelity and complete the screen inventory

Use `reports/10-approved-design-parity-audit.md`. Render both exports locally in the
coding agent's working environment, with supporting assets. Compare at the selected
1280/1440 admin reference width and approximately 390px model width. Do not include
the export's outer demo frame, toolbar or fake phone furniture.

Finish admin Models catalogue, profile hero/fields and product images, and Settings
subsection content. Home's content panel must list affected models and their actual
progress, not only aggregate counts. Add query-backed return state for searches,
filters, month and selected profile. Correct current-month terms under older month
selection. Preserve authorization for each existing action.

### C2 — Align read contracts with the already-approved financial rules

Investigate the actual route-to-service call chains before changing them. Confirmed
source gaps at the base commit:

- `payroll.blockers_for` calls `calculate_month`; `commission/calculate.py` includes
  pending base only when `is_preview` is true. The new rules currently have a
  separate read-only preview. D01's date being configured did not activate that path.
- `portal.my_month` still reads old commission states for sales/counts. Historical
  months without snapshots return `amount_piastres: null` even when newer history
  setup features exist. H02/H06 need an end-to-end proof, not another completion note.
- `my_year` has `orders`, not `uses`; the draft chart explicitly shows unavailable
  Uses history until this is wired. Add authoritative `uses` per eligible month.
- Legacy commission-state counts are not delivery-state counts. Draft Home/Orders
  deliberately say Counted/Excluded rather than mislabel them Delivered/Failed.
  Supply true delivered, pending and failed counts, then use the approved labels.
- Current source performance must be separate from frozen approval and real payments.
  Do not make a frozen sales snapshot masquerade as the current sales graph.
- The old order payload and copy still describe pending commission as unavailable
  and older delivery carry-forward. Remove that behavior for new-policy months,
  retaining older audit records and avoiding duplicate commission when delivery lands.
- Model-specific product-sales analytics are missing from the model-facing API;
  the existing top-products endpoint is staff-only and aggregates all models.

Do not sum money or implement commission/guarantee logic in React. Reuse the approved
calculation engine, snapshot and correction services, with verified source selection.
Use original-month terms/target evidence for guarantee corrections. F02/F04/F07/F13,
D01 and D04 are not new questions. Keep unresolved D02/D09/D10 visible where applicable.

Validate pending -> delivered without duplication; failure before/after approval;
fully/partly paid and approved-unpaid snapshots; target-met guarantee correction;
fixed-plus-commission; source graph vs settlement month; earlier deductions consuming
a month; external-settled history without invented payments; eligibility/readiness.
Run these against a positively identified, disposable test database, one process.

### C3 — Products and the complete wardrobe journey

Match `vProducts`, `vProduct`, `vShipment`, `vPromo` and the model wardrobe views.
Promotion editing is its approved secondary view, not a long inline form in the
product roster. Show model-specific top sellers, eligible passive feature cards,
then owned/incoming products in the approved row layout. Use real product images.
Never expose staff aggregate sales as this model's own top sellers. Feature requests
are eligible for Received or Processing, never Not sent or failed-only. No Done
button and no target mutation. Keep four grouped roster states and shipping-phone
matching; no courier integration or Shopify writes.

### C4 — Payments, terms, receipts and account views

Use one model/month payment detail as the approved entry point. It must show current
terms, approved earnings, deductions, funds to send, full authorized method-specific
destination, exact saved InstaPay link, actual history and receipt navigation.
Preserve explicit approval preview/source version and durable payment operation keys.
Opening InstaPay does not create a payment. A zero transfer due creates no fake row.

Match the selected-month terms editor (select Jan/Feb, save; then Mar/Apr, save,
stay in editor; unselected months unchanged). Preserve locks and immutable references.
Replace the long model You form with its approved menu and secondary details,
measurements, payout, notifications, appearance, FAQs and payment/receipt views.
Keep current-password reauthentication and real required payout fields (D06/D07).

### C5 — Final acceptance and release preparation

Complete screenshot comparisons for every primary and secondary view, not three
sample journeys. Verify actions, phone overflow, long names, sparse/large data,
loading/empty/retry, both themes and all approved financial states. Update the audit
matrix with evidence for each row. Run required frontend and isolated backend gates.
Prepare a reviewable PR and deployment plan; release only with the owner's deployment
authorization. Do not label the redesign complete while screenshots or data contracts
remain unverified.

## Copy into the coding agent

Continue branch `fix/approved-design-parity`. Read CLAUDE.md and this handoff first,
then reports/10-approved-design-parity-audit.md, PRODUCT_RULES.md and closed decisions.
The reference HTML files already live in docs/redesign/designs with their assets.
Start C1; do not repeat the old claim that adding a feature to an old page proves
parity. Inspect the diff in this branch before changing it. Preserve completed backend
protections and do not deploy. Report the actual before/after screenshots, functioning
actions, unresolved data contracts and test results after each batch. Then continue
C2-C5 in order, stopping only for a genuinely unresolved policy or access requirement.
