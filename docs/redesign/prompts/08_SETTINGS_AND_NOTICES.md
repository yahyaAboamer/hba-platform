# Phase 08 — Settings, operations, notices and help

You are implementing the HBA redesign in the connected existing repository. This package lives at `docs/redesign/`. Read repository instructions and `docs/redesign/STATUS.md` first. Then read `PRODUCT_RULES.md`, the relevant sections of `REPOSITORY_AUDIT.md`, `BACKEND_CONTRACTS.md`, `DESIGN_REVIEW.md` and `DECISIONS.md` for this batch. Use only the two selected files under `designs/` as current visual references.

**Run only the first unfinished batch below, unless I explicitly name another batch.** Do not implement all phases in one response. Complete the requested batch, leave reviewable running behavior and a report, then stop at that boundary. If a previous batch is incomplete, report and finish that dependency rather than quietly skipping it.

Dependencies: Relevant previous feature APIs and baseline permission map; D10 before any new role or access grant.

Rules/coverage: A09 A10 S05 S06 M05; UI44–UI50; AC02/AC03/AC05/AC56–AC61.

Starting code locations (reverify in the current checkout): Settings, DataPanel, Glossary, MyPolicy; app/api/operations.py, staff.py, policy.py, audit.py; services/notifications.py, notification_prefs.py, staff.py, policy.py.

## 08A — Preserve admin operations in approved navigation

Real staff invitations/roles/status, Shopify scope/sync/job health/retry and guarded import support, history setup entry, brand codes, policy versions/audit/reference. No sample secrets or fake connection controls; no role composer inferred from user stories.

## 08B — Notices, preferences, theme and help

Temporary hide vs permanent item mute vs issue resolution; correct single/multi-record destination and durable state. Two confirmed model email preferences map to existing events without muting security mail. Help/policy copy matches pending pay/no reopen, with concise product text.

## Completion gate

Show real settings/notice flows, access failures and preference persistence. Retain current shop-level import restrictions; no live invitations/emails/imports just to demo the screen. Use test delivery where needed.

Use the real backend/data contracts and approved design together. Distinguish backend tests, source inspection and rendered visual checks. Do not ship mock arrays, sample bank details, false success or in-browser payroll. Update relevant CSV row statuses only with evidence. Preserve unrelated work and use a branch/worktree consistent with the current repo.

Before ending, create a batch report from `templates/BATCH_REPORT.md`, update `STATUS.md`, record decisions/limitations, and give the exact next batch and prompt. Report what changed, what I should try, and actual verification results. Ask only a necessary unanswered business question blocking this batch; continue independent authorized work where possible. Do not push/deploy to production or edit live financial data under this phase prompt alone.
