# Historical transition, migration and release

This is an implementation/rehearsal plan. It does not itself authorize live database changes, Shopify imports or branch promotion.

## Baseline before migrations

Record the actual checkout SHA, migration head, database targets, worker state, current live payment boundary and existing financial records. Verify the local test connection uses a disposable PostgreSQL database: this repository's test fixture rebuilds the schema at session start. **Run only one pytest process at a time**, and do not run Alembic concurrently against the same test DB. Never point these tests at staging/production or a local database containing records to keep.

Use the existing backup/restore mechanism, prove a restore into an isolated environment, and check append-only triggers before/after migrations. The repo's deliberately isolated test fixtures are not permission to disable data protections in an application migration.

## Additive development strategy

1. Add nullable/new profile fields and normalized catalog, matching and correction persistence needed by the chosen implementation. Inventory indexes/constraints and migration order. Avoid destructive renames or removal of old financial columns in the first rollout.
2. Keep compatibility while new APIs/UI are assembled. If a feature flag is used, default it off for real finance until rehearsal passes; do not build a broad feature-flag framework just for this project.
3. Separate schema migrations from potentially long Shopify backfill/reconstruction jobs. Deploy startup migrations must not launch a hours-long store scan or calculate every historical month synchronously.
4. Provide dry-run/readiness output with counts and unresolved items. Batch jobs have explicit IDs, checkpoints, retry limits, idempotency and a resumable cursor. Replaying a batch changes no already-correct records or transfers.

## Transition manifest

Create an explicit reviewed model/month manifest through setup and reconciliation. Required facts: model ID, actual collaboration start, last externally settled month/new-policy boundary, compensation coverage, historical target outcome/evidence, source-order completeness, any existing approved snapshots/transfers/legacy carry allocations, and setup status. Never store full bank numbers/phones or credentials in this report.

For each month classify the migration treatment:

| Record situation | Treatment |
|---|---|
| Before January 2026 or before actual model start | Outside model month selection; do not fabricate zeros or earning statements. |
| Legitimate zero-sales month after start | Eligible and visible; calculate any fixed/guaranteed arrangement correctly from actual terms/outcome. |
| Existing externally settled pre-platform month | Reconstruct performance and entitlement, keep same model UI, create no transfer/receipt/debt. Finalized external settlement prevents repayment. |
| Existing real approved/paid platform month | Preserve original snapshots, transaction/allocation/proof IDs and sums. No conversion to a guessed external settlement; reconcile separately. |
| Open transition month | Resolve the agreed policy and all existing allocations before switching. Do not sum both old delivered-only earnings and newly pending-inclusive earnings. |
| Older order already paid by legacy carry-forward | Preserve its actual payment evidence; prevent double-counting on migration or later delivery. Current historical performance can show the sale in its original month with provenance. |
| Missing terms/target outcome/source history | Mark incomplete for setup; don't finalize, invent a rate or manufacture content counts. Continue other complete models. |

## History reconstruction rehearsal

- Ingest required Shopify history from January 2026 using verified access. Coordinate with the existing shop-level import restrictions; do not start an import from staging while it shares the production shop under the current runbook.
- Backfill product/variant/line-item and recipient matches independently from financial attribution. Track missing/ambiguous phones and original gift/purchase basis.
- Use recorded historical monthly terms and outcome-only evidence where counts are unavailable. Read-only dry-run totals should distinguish current reconstructed performance from original actual transfer amounts.
- Compare per-model/per-month net sales, pending/delivered/failed counts, commission, fixed amount, guarantee top-up, approved amounts, payments, applied/absorbed/remaining corrections. Preserve cents/exact arithmetic and the chosen final rounding rule.
- Do not manufacture late-failure debts from externally settled history. The owner accepted reconstructed historical differences; they did not request recovery of those differences. New post-launch handling applies to the agreed cohort/boundary.
- Confirm that finalized externally settled months never enter payable totals or accept a transfer, even through direct API requests. Model payment history remains truthful about absent records.
- Run twice: second run should be a no-op for finalized data and contain no duplicate order, snapshot, correction, transfer, notice or email event.

## Staging acceptance

Use synthetic/anonymized fixtures plus a carefully scoped read-only reconciliation where available. Do not copy private payment screenshots into a public PR or artifact.

Walk the complete journeys: invitation→application→approval→model home; selected-month terms→targets→review→approval→external transfer record→receipt; Shopify shipment→product roster→shared profile→model wardrobe; feature visibility changes; late failed order→absorb or carry→next approval→model explanation; archived model→history; empty/new model; connection failure/retry; settings/staff/support permissions.

Verify both themes and intended screen widths. Check old URLs/redirects, browser Back, accessible focus, paging, keyboard/touch, image failures and charts. Perform cross-role negative checks with actual API authorization, including proof ownership and full destination access.

## Release candidate checklist

- Every in-scope row in `SCREEN_AND_ACTION_MAP.csv` is implemented/verified or explicitly deferred by the owner; no silent omissions.
- All blocking financial/identity/migration decisions are resolved; non-blocking choices have honest fallback behavior.
- Actual relevant suites/build/integration results are recorded; historical test counts are not cited as evidence.
- Migration dry run, second-run idempotency, totals reconciliation, backup/restore and append-only constraints pass.
- No development fixtures, review controls, mock receipts, in-browser payroll, fake credentials or unsupported success states remain.
- Verify current branch/environment/deployment policy and notification/import owners. Produce a concrete commit, migration list, rehearsal report and rollback plan before proposing production release.

## Cutover and recovery

During the reviewed cutover, coordinate financial approvals and workers so the same month cannot be approved under two policies concurrently. Record the actual cutover boundary/revision. Resume ingestion, verify backlog/reconciliation, and check representative model/admin totals and receipt access.

Schema rollback and financial rollback are different. Once a new real approval/payment/correction exists, reverting the frontend cannot erase it. Keep additive compatibility or roll forward; if new money actions must pause, preserve read access and evidence. Restoring an older database backup after new transfers were recorded requires explicit reconciliation of those real-world transfers, not an automatic rollback script.

Post-release checks: health/jobs/sync freshness; duplicate financial events; model Home vs admin totals; new pending→delivered no extra pay; failed delivery correction creation; notices/email once; received/processing promotion eligibility; externally settled history still non-payable. Record results in the release report.
