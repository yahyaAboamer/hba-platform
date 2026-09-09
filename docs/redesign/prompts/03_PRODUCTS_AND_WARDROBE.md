# Phase 03 — Products, recipient matching and wardrobes

You are implementing the HBA redesign in the connected existing repository. This package lives at `docs/redesign/`. Read repository instructions and `docs/redesign/STATUS.md` first. Then read `PRODUCT_RULES.md`, the relevant sections of `REPOSITORY_AUDIT.md`, `BACKEND_CONTRACTS.md`, `DESIGN_REVIEW.md` and `DECISIONS.md` for this batch. Use only the two selected files under `designs/` as current visual references.

**Run only the first unfinished batch below, unless I explicitly name another batch.** Do not implement all phases in one response. Complete the requested batch, leave reviewable running behavior and a report, then stop at that boundary. If a previous batch is incomplete, report and finish that dependency rather than quietly skipping it.

Dependencies: 02 identity/profile links; verified Shopify access; D05 before personal-purchase inclusion.

Rules/coverage: W01–W12, F01; UI12–UI20; AC15–AC25.

Starting code locations (reverify in the current checkout): app/services/shopify/{client,queries,normalise,sync,bulk,fulfilment}.py, jobs.py, reconcile.py; existing PII structural tests; new catalog/recipient/wardrobe APIs and approved product/profile/wardrobe views.

## 03A — Read catalog, variants, media and line items

Use configured API schema and paginated durable sync. Verify all-orders/protected-field access; no writes to Shopify orders. New recipient field denial cannot break existing commission sync. Stable product/variant IDs, historical fallback and freshness metadata.

## 03B — Match recipient orders and build product history

Use normalized shipping phone in a separate restricted path, original gift/purchase basis, matching provenance and unresolved state. Resumable backfill from January; no full-store query per screen; idempotent/reordered events. Preserve old model links after phone changes.

## 03C — Deliver product roster, both wardrobes and passive requests

Active/All catalog, grouped roster, shared profile, owned/incoming/failed items, size/images. Received/Processing server-filtered feature guidance; no completion or target actions. Correct replacement at product level; no courier/collection/duplicate-blocking scope.

## Completion gate

Show one multi-product gift across both dashboards, failed shipment then partial-product replacement, and eligible/ineligible feature audiences. Real sync can be simulated with authoritative-shape fixtures in isolated development; do not start a staging import against shared production shop.

Use the real backend/data contracts and approved design together. Distinguish backend tests, source inspection and rendered visual checks. Do not ship mock arrays, sample bank details, false success or in-browser payroll. Update relevant CSV row statuses only with evidence. Preserve unrelated work and use a branch/worktree consistent with the current repo.

Before ending, create a batch report from `templates/BATCH_REPORT.md`, update `STATUS.md`, record decisions/limitations, and give the exact next batch and prompt. Report what changed, what I should try, and actual verification results. Ask only a necessary unanswered business question blocking this batch; continue independent authorized work where possible. Do not push/deploy to production or edit live financial data under this phase prompt alone.
