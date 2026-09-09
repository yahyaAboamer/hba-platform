# Phase 09 — Migration rehearsal, acceptance and release candidate

You are implementing the HBA redesign in the connected existing repository. This package lives at `docs/redesign/`. Read repository instructions and `docs/redesign/STATUS.md` first. Then read `PRODUCT_RULES.md`, the relevant sections of `REPOSITORY_AUDIT.md`, `BACKEND_CONTRACTS.md`, `DESIGN_REVIEW.md` and `DECISIONS.md` for this batch. Use only the two selected files under `designs/` as current visual references.

**Run only the first unfinished batch below, unless I explicitly name another batch.** Do not implement all phases in one response. Complete the requested batch, leave reviewable running behavior and a report, then stop at that boundary. If a previous batch is incomplete, report and finish that dependency rather than quietly skipping it.

Dependencies: All implemented feature batches; D01 transition manifest and all affected blocking decisions resolved.

Rules/coverage: MIGRATION_AND_RELEASE.md; all UI rows and acceptance checks, especially AC12–AC14/AC23/AC62/AC64.

Starting code locations (reverify in the current checkout): Alembic migrations, jobs/backfill, Dockerfile/Railway/backup/runbooks, actual schema/ledger records, final frontend routes and API contracts.

## 09A — Rehearse historical reconstruction and transition

On an isolated restored/synthetic database, additive migrations, term/target/source readiness, external-settled boundary, old carry reconciliation, dry-run per-month totals and second-run idempotency. No invented transfers, opening debt or production policy flip.

## 09B — Full product acceptance

Run required current suites sequentially on disposable DB, build frontend, walk every mapped function and both roles/devices/themes; collect actual screenshots and discrepancies. Resolve high-impact regressions; document approved deferrals explicitly.

## 09C — Prepare reviewed release; deploy only when separately authorized

Produce exact commit, migration/backfill plan, totals reconciliation, test/visual evidence, environment and import ownership, verified backup/restore and rollback/roll-forward procedure. Current request for a handoff does not authorize production deployment; after release authorization, execute approved cutover and record post-release checks.

## Completion gate

Do not claim release ready with unresolved financial/migration failures or missing app walkthrough. Do not follow old push-both-branches assumptions without verifying current conditions and the owner’s release instruction.

Use the real backend/data contracts and approved design together. Distinguish backend tests, source inspection and rendered visual checks. Do not ship mock arrays, sample bank details, false success or in-browser payroll. Update relevant CSV row statuses only with evidence. Preserve unrelated work and use a branch/worktree consistent with the current repo.

Before ending, create a batch report from `templates/BATCH_REPORT.md`, update `STATUS.md`, record decisions/limitations, and give the exact next batch and prompt. Report what changed, what I should try, and actual verification results. Ask only a necessary unanswered business question blocking this batch; continue independent authorized work where possible. Do not push/deploy to production or edit live financial data under this phase prompt alone.
