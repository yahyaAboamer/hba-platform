# Phase 04 — Targets and historical outcomes

You are implementing the HBA redesign in the connected existing repository. This package lives at `docs/redesign/`. Read repository instructions and `docs/redesign/STATUS.md` first. Then read `PRODUCT_RULES.md`, the relevant sections of `REPOSITORY_AUDIT.md`, `BACKEND_CONTRACTS.md`, `DESIGN_REVIEW.md` and `DECISIONS.md` for this batch. Use only the two selected files under `designs/` as current visual references.

**Run only the first unfinished batch below, unless I explicitly name another batch.** Do not implement all phases in one response. Complete the requested batch, leave reviewable running behavior and a report, then stop at that boundary. If a previous batch is incomplete, report and finish that dependency rather than quietly skipping it.

Dependencies: 02 model/month/terms contracts; preserve current verification policy unless explicitly changed.

Rules/coverage: A06 F06 H02 M01; UI21–UI24; AC26–AC30.

Starting code locations (reverify in the current checkout): frontend/src/screens/Targets.tsx; app/api/targets.py; app/services/targets.py; app/models/targets.py; portal target serialization.

## 04A — Monthly required and achieved editor

Persist requirements separately from weekly cumulative achievements; null/zero/invalid/stale distinctions. No cross-month unsaved draft application. Keep admin model-profile summary consistent.

## 04B — Verification, historical outcome and model Targets

Known met/missed outcomes without invented counts for old months, current verification behavior and evidence. Models read current/history. Protect target data used by immutable approval; source corrections will use frozen qualification.

## Completion gate

Demonstrate saving 8 required videos does not alter achieved counts, unknown stories blocks a required guarantee decision, and history can record met without fake counts. Test realistic save/retry/conflict behavior.

Use the real backend/data contracts and approved design together. Distinguish backend tests, source inspection and rendered visual checks. Do not ship mock arrays, sample bank details, false success or in-browser payroll. Update relevant CSV row statuses only with evidence. Preserve unrelated work and use a branch/worktree consistent with the current repo.

Before ending, create a batch report from `templates/BATCH_REPORT.md`, update `STATUS.md`, record decisions/limitations, and give the exact next batch and prompt. Report what changed, what I should try, and actual verification results. Ask only a necessary unanswered business question blocking this batch; continue independent authorized work where possible. Do not push/deploy to production or edit live financial data under this phase prompt alone.
