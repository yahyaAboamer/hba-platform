# Phase 01 — Shared UI foundations

You are implementing the HBA redesign in the connected existing repository. This package lives at `docs/redesign/`. Read repository instructions and `docs/redesign/STATUS.md` first. Then read `PRODUCT_RULES.md`, the relevant sections of `REPOSITORY_AUDIT.md`, `BACKEND_CONTRACTS.md`, `DESIGN_REVIEW.md` and `DECISIONS.md` for this batch. Use only the two selected files under `designs/` as current visual references.

**Run only the first unfinished batch below, unless I explicitly name another batch.** Do not implement all phases in one response. Complete the requested batch, leave reviewable running behavior and a report, then stop at that boundary. If a previous batch is incomplete, report and finish that dependency rather than quietly skipping it.

Dependencies: 00 baseline report and current repository instructions.

Rules/coverage: S01–S07; screen rows UI01/UI02/UI51; AC01/AC02/AC57.

Starting code locations (reverify in the current checkout): frontend/src/App.tsx, components/Layout.tsx, components/AffiliateLayout.tsx, screens/AffiliatePortal.tsx, styles/, lib/theme.ts and lib/api.ts.

## 01A — Port approved design tokens and shared components

Dark/light colors, type, spacing, tables/cards, fields, status chips, modal/sheet, buttons and brief empty/error/loading patterns. Preserve style isolation, replace red deliberately, retain money formatting. Do not add a new UI framework just to mimic HTML.

## 01B — Wire authenticated navigation and responsive shells

Admin six tabs and model five tabs plus You. Preserve all required secondary routes/access/onboarding, consistent Back/month context and server permissions. Show actual existing data where available; unfinished areas must be clearly identified in development and not released as functioning pages.

## Completion gate

Show real admin and model shells in both themes. Run frontend build and relevant auth/routing/style tests. No backend finance changes or sample-data deployment.

Use the real backend/data contracts and approved design together. Distinguish backend tests, source inspection and rendered visual checks. Do not ship mock arrays, sample bank details, false success or in-browser payroll. Update relevant CSV row statuses only with evidence. Preserve unrelated work and use a branch/worktree consistent with the current repo.

Before ending, create a batch report from `templates/BATCH_REPORT.md`, update `STATUS.md`, record decisions/limitations, and give the exact next batch and prompt. Report what changed, what I should try, and actual verification results. Ask only a necessary unanswered business question blocking this batch; continue independent authorized work where possible. Do not push/deploy to production or edit live financial data under this phase prompt alone.
