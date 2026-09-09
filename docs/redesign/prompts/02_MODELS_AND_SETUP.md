# Phase 02 — Models, profiles and historical setup

You are implementing the HBA redesign in the connected existing repository. This package lives at `docs/redesign/`. Read repository instructions and `docs/redesign/STATUS.md` first. Then read `PRODUCT_RULES.md`, the relevant sections of `REPOSITORY_AUDIT.md`, `BACKEND_CONTRACTS.md`, `DESIGN_REVIEW.md` and `DECISIONS.md` for this batch. Use only the two selected files under `designs/` as current visual references.

**Run only the first unfinished batch below, unless I explicitly name another batch.** Do not implement all phases in one response. Complete the requested batch, leave reviewable running behavior and a report, then stop at that boundary. If a previous batch is incomplete, report and finish that dependency rather than quietly skipping it.

Dependencies: 01 shells and baseline role/route map; resolve D07 before new contact writes and D06 before changing payout semantics.

Rules/coverage: A03–A06, H01–H06, M03; UI03–UI11/UI41/UI42; AC03–AC14/AC55.

Starting code locations (reverify in the current checkout): Affiliates, AffiliateDetail, Apply, InviteModel, MyDetails, MyPayout, Compensation; app/api/affiliates.py, applications.py, affiliate_self.py; services/compensation.py, applications.py, payouts.py; profile/compensation models.

## 02A — Finish model entry and directory

Invite/accept/apply/wait/code verification/approve through real services. Preserve inactive/archive and house treatment. Add real collaboration start as distinct data. Optional measurements do not block application.

## 02B — Shared profile and self-editing

Directory/product/target/payment links target one model profile. Persist authorized contacts and optional measurements; model-only measurement writes. Keep payout change reauthentication and exact URL behavior. Resolve contact-versus-login email and bank-field ambiguity before mutating those meanings.

## 02C — Selected-month terms and setup readiness

Implement atomic arbitrary month assignment with overlap/range preservation, approved locks, mixed selection and repeated Save in same editor. Add setup coverage by every eligible month, including outcome-only historical target hooks. Do not finalize live historical records yet; use isolated fixtures until phase09.

## Completion gate

Demonstrate Jan/Feb commission, Mar/Apr salary, other months unchanged, stale-lock rejection and model/self profile persistence. Tests must cover atomicity and approved evidence. No ad hoc production edits.

Use the real backend/data contracts and approved design together. Distinguish backend tests, source inspection and rendered visual checks. Do not ship mock arrays, sample bank details, false success or in-browser payroll. Update relevant CSV row statuses only with evidence. Preserve unrelated work and use a branch/worktree consistent with the current repo.

Before ending, create a batch report from `templates/BATCH_REPORT.md`, update `STATUS.md`, record decisions/limitations, and give the exact next batch and prompt. Report what changed, what I should try, and actual verification results. Ask only a necessary unanswered business question blocking this batch; continue independent authorized work where possible. Do not push/deploy to production or edit live financial data under this phase prompt alone.
