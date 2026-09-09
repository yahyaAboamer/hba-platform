# Phase 07 — Home, orders, ranking and analytics

You are implementing the HBA redesign in the connected existing repository. This package lives at `docs/redesign/`. Read repository instructions and `docs/redesign/STATUS.md` first. Then read `PRODUCT_RULES.md`, the relevant sections of `REPOSITORY_AUDIT.md`, `BACKEND_CONTRACTS.md`, `DESIGN_REVIEW.md` and `DECISIONS.md` for this batch. Use only the two selected files under `designs/` as current visual references.

**Run only the first unfinished batch below, unless I explicitly name another batch.** Do not implement all phases in one response. Complete the requested batch, leave reviewable running behavior and a report, then stop at that boundary. If a previous batch is incomplete, report and finish that dependency rather than quietly skipping it.

Dependencies: 03 product data, 04 targets, 05 financial contract and 06 payment views; D03 before ranking/uses; D08 only if an automatic weekly judgment is wanted.

Rules/coverage: A01 A02 F13 F14 W11 H01 M01 M02; UI19/UI33–UI40; AC24/AC25/AC31/AC32/AC48–AC54.

Starting code locations (reverify in the current checkout): MyMonth, MyOrders, MyYear, MyGrow, Overview, Orders, AffiliateDetail; services/portal.py and earnings/orders APIs plus new analytics/ranking service.

## 07A — Model Home and Orders

Actual month/history with own rate/arrangement, concise earnings/approval/payment explanation, original-month current sales and destination deduction, full order paging/status/products, no customer PII. Charts for zero/one/many/missing months; receipt context remains separate. No hardcoded fixture dates or 10% copy.

## 07B — Ranking, top sellers, owner Home and profile performance

Sales-ranked peers with permitted uses only, stable IDs/discount-aware product analytics, owner sales/pay forecast breakdown/active count/top3 and neutral content progress. Same totals across list/detail/chart; no house/inactive-history mistakes or misleading partial-period growth labels.

## Completion gate

Compare real screens against approved HTML on phones/laptops. Test all chart edges and network failures, cross-month correction display and API privacy. Do not calculate payroll from paginated order rows in the browser.

Use the real backend/data contracts and approved design together. Distinguish backend tests, source inspection and rendered visual checks. Do not ship mock arrays, sample bank details, false success or in-browser payroll. Update relevant CSV row statuses only with evidence. Preserve unrelated work and use a branch/worktree consistent with the current repo.

Before ending, create a batch report from `templates/BATCH_REPORT.md`, update `STATUS.md`, record decisions/limitations, and give the exact next batch and prompt. Report what changed, what I should try, and actual verification results. Ask only a necessary unanswered business question blocking this batch; continue independent authorized work where possible. Do not push/deploy to production or edit live financial data under this phase prompt alone.
