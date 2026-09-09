# Phase 06 — Payment destination, recording and history

You are implementing the HBA redesign in the connected existing repository. This package lives at `docs/redesign/`. Read repository instructions and `docs/redesign/STATUS.md` first. Then read `PRODUCT_RULES.md`, the relevant sections of `REPOSITORY_AUDIT.md`, `BACKEND_CONTRACTS.md`, `DESIGN_REVIEW.md` and `DECISIONS.md` for this batch. Use only the two selected files under `designs/` as current visual references.

**Run only the first unfinished batch below, unless I explicitly name another batch.** Do not implement all phases in one response. Complete the requested batch, leave reviewable running behavior and a report, then stop at that boundary. If a previous batch is incomplete, report and finish that dependency rather than quietly skipping it.

Dependencies: 05 verified finance/approval/allocation contracts; 02 profile/payout semantics, D06 resolved.

Rules/coverage: A07 A08 F07 F08 F14 H03 M03 M04; UI25–UI29/UI32/UI42/UI43; AC31/AC32/AC36–AC41/AC55.

Starting code locations (reverify in the current checkout): PaymentRecord, Payments, AffiliatePayments, MyPayments, AffiliatePayout, MyPayout; app/api/payments.py, affiliate_self.py; services/payments.py, payouts.py, proof.py; existing reveal/proof endpoints.

## 06A — Admin month-end payment journey

Total needed and each model due, complete authorized destination, copy/Open InstaPay, review/approve link, external transfer recording with amount/date/reference/proof, partial/overpayment state and genuine transaction history. Inactive owed models remain. Reuse existing services and idempotency rather than a parallel ledger.

## 06B — Model payment views and destination changes

You payment history/proof and selected-payment calculation link; frozen destination and statement context, multiple/partial transfers and truthful no-record old months. Payout draft/cancel/password validation; exact submitted link and real instructional asset.

## Completion gate

Show each payment method and a full review→external-record→receipt flow in isolated data. Test timeout-after-save and proof retry, forbidden proof access, historic receipt context and later destination change. No actual transfer initiation.

Use the real backend/data contracts and approved design together. Distinguish backend tests, source inspection and rendered visual checks. Do not ship mock arrays, sample bank details, false success or in-browser payroll. Update relevant CSV row statuses only with evidence. Preserve unrelated work and use a branch/worktree consistent with the current repo.

Before ending, create a batch report from `templates/BATCH_REPORT.md`, update `STATUS.md`, record decisions/limitations, and give the exact next batch and prompt. Report what changed, what I should try, and actual verification results. Ask only a necessary unanswered business question blocking this batch; continue independent authorized work where possible. Do not push/deploy to production or edit live financial data under this phase prompt alone.
