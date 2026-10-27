# HBA OS roadmap

**The one place to see how everything fits.** One hierarchy only: Phase →
Batch → Task → Status. Statuses: **Completed**, **In progress**, **Blocked by
owner**, **Pending**, **Deferred**. Updated 26 October 2026.

Sources: ADRs 0065–0069 (the architecture), `2026-10-25-phase-1-foundations.md`
(Phase 1 in detail). The batch in flight keeps its working checkpoint in
`2026-10-25-phase-1-progress.md`.

**Not in this roadmap, with plans of their own:** the Inbox switch-over
(`2026-10-11-whatsapp-inbox-and-order-confirmation.md`; its "phases 0–8" are the
Inbox's own, unrelated to these) and the audit repair's release gates
(`2026-10-11-continuation-handoff.md`). The release gates were rehearsed on
production's backup on 25 October; the reconciliation is rerun after the first payroll approval.

---

## Phase 0 — Decide

**Batch 0.1 — Architecture and design decisions**

| Task | Status |
|---|---|
| Architecture proposal | Completed |
| ADRs 0065–0069 | Completed (on PR #125, not merged) |
| HBA OS shell mockup | Completed (approved 25 October) |
| Production-frame mockup | Completed (approved 25 October) |
| Accounting: build or buy | Deferred: decided before Finance |

## Phase 1 — Foundations

**Batch 1.0 — Before anything**

| Task | Status |
|---|---|
| Repository visibility | Deferred: public until the GitHub upgrade, then private |
| Production site requires sign-in | Deferred: the owner retires the ChatGPT site once Production moves in |
| Release gates: restored-copy reconciliation and migration rehearsal | Completed 25 October (see the progress file); rerun the reconciliation after the first payroll approval |

**Batch 1.1 — Safety net** (PR #125)

| Task | Status |
|---|---|
| CI on every pull request | Completed (first full run 9m43s; limits set from it) |
| Server error alerts | Completed in code; dormant until deployed |
| Browser error alerts | Completed in code |
| Health checks answer HEAD (the UptimeRobot 405) | Completed in code; takes effect when deployed |
| A failed job's log line carries no customer data | Completed in code |
| Sentry account and Railway variables | Completed: verified in Railway (both DSNs, EU, all three places) |
| UptimeRobot monitor | Completed by the owner; reads down until the HEAD fix is deployed |
| Merge PR #125 | Completed (`a2ae261`, 25 October) |
| Deploy to production | Completed (`a2ae261`; Sentry live in both, HEAD answers 200) |
| After deploying: a test alert from staging, the monitor green | Pending |
| Narrow CI's time limits from the first measured run | Completed |
| Branch protection requiring CI | Deferred: after the GitHub upgrade |

**Batch 1.2 — Several roles per person** (ADR 0067)

| Task | Status |
|---|---|
| Roles held together, add and remove, the operations manager's access moved without change, audit tagged by department | Completed: PR #127, deployed to staging and production as `ef266a2` on 26 October; role migration checked on both, and a read-only browser check of production passed |

**Batch 1.3 — HBA OS two-step sign-in, devices, suspending** (ADR 0067)

| Task | Status |
|---|---|
| Authenticator codes for the owner and money roles, recovery codes, signed-in devices, suspend | In progress: authenticator version, devices and suspending live since 26–27 October (PRs #128, #129); on 27 October the owner changed the second step to an email code on a new browser for money roles and an authenticator for the owner only, with browsers remembered for 30 days (ADR 0067 decision 5 amended; `phase-1/batch-3b`). Enforcement (`TWO_STEP_ENFORCED`) stays off until the owner switches it on |

**Batch 1.4 — Department folders** (ADR 0065)

| Task | Status |
|---|---|
| Move code into `app/modules/…`, import check in CI | Pending: when no other branch is open (`feature/whatsapp-inbox` is) |

## Phase 2 — One frame for every department (ADR 0068)

**Batch 2.1 — The frame**

| Task | Status |
|---|---|
| Departments declared once; the sidebar; department addresses with redirects; Today; Team and access by department; Settings split; the phone layout | Pending: after Batch 1.2 |

## Phase 3 — Shared records (ADRs 0066, 0068)

**Batch 3.1 — Records every department points at**

| Task | Status |
|---|---|
| One page per order; search across departments | Pending: after Phase 2 |
| A shared customer record; staff profiles | Pending: when a second department needs each |

## Phase 4 — Departments, one at a time

**Batch 4.1 — Production moves in** (ADR 0069)

| Task | Status |
|---|---|
| Site requires sign-in | Deferred: the owner retires the site once Production moves in |
| Source code, data and files exported from ChatGPT | **Blocked by owner** |
| Production-frame mockup approved | Completed |
| Read the exported code in full | Pending: after the export |
| The platform answers Production's five requests; data into HBA's database | Pending: after Batch 1.2 |
| HBA sign-in for the team, supplier accounts | Pending: after Batch 1.2 |
| Side-by-side check, data reconciled, everyone switched, ChatGPT copy retired | Pending |
| Production's costing and payments meet the money rules | Deferred: its own decision before any money is recorded |

**Batch 4.2 — Finance** — Deferred.  **Batch 4.3 — People** — Deferred.

---

## Not project work: the owner's account security

Two-step sign-in on GitHub, Railway, Sentry, UptimeRobot, Shopify, Meta,
ChatGPT, the email and storage providers, and Google: a recommendation for each
account holder, listed in `docs/runbooks/monitoring-and-account-security.md`,
section 3. It is not tracked as implementation. It is different from Batch 1.3,
which is HBA OS's own sign-in for its staff, a feature of the product.
