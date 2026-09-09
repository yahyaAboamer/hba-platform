# Phase 05 — Financial engine, approval and corrections

You are implementing the HBA redesign in the connected existing repository. This package lives at `docs/redesign/`. Read repository instructions and `docs/redesign/STATUS.md` first. Then read `PRODUCT_RULES.md`, the relevant sections of `REPOSITORY_AUDIT.md`, `BACKEND_CONTRACTS.md`, `DESIGN_REVIEW.md` and `DECISIONS.md` for this batch. Use only the two selected files under `designs/` as current visual references.

**Run only the first unfinished batch below, unless I explicitly name another batch.** Do not implement all phases in one response. Complete the requested batch, leave reviewable running behavior and a report, then stop at that boundary. If a previous batch is incomplete, report and finish that dependency rather than quietly skipping it.

Dependencies: 02 monthly terms and 04 target evidence; D02 rounding before A; D04/D09 before affected C operations; D01 transition strategy before enabling live behavior.

Rules/coverage: F01–F15 H03; UI26/UI30/UI31/UI52; AC28/AC33–AC35/AC42–AC48/AC50/AC52/AC62/AC63.

Starting code locations (reverify in the current checkout): app/services/commission/{state,base,calculate,attribute,backfill}.py; app/services/payroll.py, payments.py, payments_state.py; financial models/APIs; append-only migrations/tests.

## 05A — Pending-inclusive earnings and source performance

Count/pay pending+delivered once; failed excluded independent of cancel; keep post-delivery basis, order-level after-discount total minus tax/shipping, exact aggregate rounding, Cairo months and house treatment. Reconcile old carry-paid links rather than deleting them. No live policy switch.

## 05B — Immutable per-model approval

Freeze source version, terms, target outcome, earnings, chosen allocations and payable; concurrent approval/stale preview safe. Disable active reopen API/route while preserving read-only history. Failure after approval before transfer becomes a correction, not an automatic changed instruction.

## 05C — Persistent late-failure review and allocation

Source-month guarantee-aware cumulative recoverable amount, HBA absorb/carry choice, shared destination capacity, remaining balance beyond four months/across years, frozen accepted allocations, idempotent events and D04/D09 handling. Model explanations supported by the same service, never JavaScript recomputation.

## Completion gate

This phase is high impact: implement only the requested sub-batch, run relevant real PostgreSQL financial/regression tests sequentially, and report exact before/after examples from financial-examples.json. Never disable append-only protections or change live amounts to make a test pass.

Use the real backend/data contracts and approved design together. Distinguish backend tests, source inspection and rendered visual checks. Do not ship mock arrays, sample bank details, false success or in-browser payroll. Update relevant CSV row statuses only with evidence. Preserve unrelated work and use a branch/worktree consistent with the current repo.

Before ending, create a batch report from `templates/BATCH_REPORT.md`, update `STATUS.md`, record decisions/limitations, and give the exact next batch and prompt. Report what changed, what I should try, and actual verification results. Ask only a necessary unanswered business question blocking this batch; continue independent authorized work where possible. Do not push/deploy to production or edit live financial data under this phase prompt alone.
