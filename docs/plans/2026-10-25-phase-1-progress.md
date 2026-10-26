# Phase 1 — progress and checkpoint

**The overall picture is `docs/plans/hba-os-roadmap.md`**; this file is the
working checkpoint of the batch in flight.

The working state of `docs/plans/2026-10-25-phase-1-foundations.md`. Updated
at each milestone, so that a restarted session resumes from here instead of
redoing finished work. Newest facts first within each section.

## Where things are

| | |
|---|---|
| **Batch in flight** | 1.3 — two-step sign-in, signed-in devices, suspending (ADR 0067, decisions 4–6) |
| **Branch** | `phase-1/batch-3`, cut from `origin/main` at `ef266a2` on 26 October 2026 |
| **Base** | `origin/main` = `origin/production` = `ef266a2` (checked 26 October 2026) |
| **Shipped so far** | Batch 1.0/1.1 (PR #125, `a2ae261`), release gates (PR #126), Batch 1.2 (PR #127, `ef266a2`); all deployed to staging and production |
| **Merged / deployed (1.3)** | nothing; neither is allowed without the owner's word for each |

## Batch 1.3 — decisions taken while building

- **One API contract first**, so backend and frontend were built side by side:
  the pending sign-in token, `/api/auth/login/two-step`, `/api/auth/two-step*`,
  `/api/auth/sessions*`, the owner's `/api/staff/{id}/sessions*` and
  `/two-step/reset`, `two_step` in the session payload.
- **The requirement has a switch, `TWO_STEP_ENFORCED`, off by default.** The
  plan makes the rollout the owner's call; until it is on, nobody is forced,
  and the screens still say who it will be required for.
- **One gate instead of a special sign-in path:** a person who must set it up
  and has not can reach only `/me`, the two-step endpoints and sign-out. That
  covers sign-in, invitation acceptance and sessions already open on the day it
  is switched on.
- **Suspending now removes every role and ends every session**, in one audit
  entry; bringing someone back gives no access until *Add access* is used.

| Workstream | Who | State |
|---|---|---|
| Backend: models, migration, TOTP, recovery codes, pending token, gate, devices, owner reset, suspend | subagent, Opus, high | **done**; whole suite 120/120 files, 3,239 tests |
| Frontend: sign-in code step, forced set-up, Settings → My preferences panels, Team lock icon, devices dialog, reset, suspend copy | subagent, Sonnet, medium | **done**; `npm test` 860/860, build passes |
| Review, security review, whole suite, build | orchestrator + Opus security reviewer | **done.** No critical finding. Fixed: a reset no longer clears the code limits (H1); a 24-hour cap of 50 wrong six-digit codes (M1) that recovery codes skip, so a stolen password cannot keep the owner out; set-up asks for the password (M2); last-admin race locked (L1); no key wording before sign-in (L2); spent pending rows purged (L3); fresh reads under locks (L4). Also: a password reset asks for the code when two-step is on; a former member of staff can never apply as a model. **Not done:** an email when the password was right but the code wrong; an owner reset that also ends that person's sessions (L5). |
| Push, PR, CI | orchestrator | not started |

## Batch 1 — the safety net

| Workstream | Who | State |
|---|---|---|
| CI workflow (`.github/workflows/ci.yml`, `run-suite.sh` learns `PYTHON`, one-migration-head check) | subagent, Sonnet, medium | **done, reviewed, committed.** Action SHAs checked against their tags. Limits widened to 60 / 55 min for the first run; narrow them after it. Locally: 2 of 117 files ran in 80 s against `hba_batch1_ci`, guard passed. |
| Sentry, backend (`sentry-sdk`, scrubbing, worker failures, `/api/client-config`) | subagent, Opus, high | **done, reviewed, committed.** `sentry-sdk` 2.71.0. Orchestrator added scrubbing of scheme-less paths' queries and `token=` values in error text. 107 targeted tests pass on `hba_batch1`; the whole suite runs in CI. |
| Sentry, frontend (`@sentry/react`, scrubbing URLs of their tokens) | subagent, Sonnet, medium | **done, reviewed, committed.** `@sentry/react` 11.6.0 (`dataCollection` all off; v11 has no `sendDefaultPii`). Orchestrator added scrubbing of addresses and `token=` inside error messages. `npm test` 817/817, `npm run build` passes. |
| Owner's setup guide: Sentry, uptime, 2FA, branch protection (`docs/runbooks/monitoring-and-account-security.md`) | orchestrator | **done** |
| Review, local tests, commits | orchestrator | not started |
| Push, PR, first CI run measured | orchestrator | not started |

**Contract between the Sentry workstreams:** `GET /api/client-config`, no
sign-in needed, returns `{"sentry_dsn": str | null, "environment": str | null,
"release": str | null}`. The DSN is the frontend project's (`SENTRY_FRONTEND_DSN`).
Nothing in it is secret: a browser DSN is public by design.

## 25 October, later: verified and fixed

- **UptimeRobot showed production down while it was up.** Its HTTP monitor
  asks `https://affiliate.hbawear.store/api/health/ready` with **HEAD**; the
  route declared GET only, so HEAD got 405 (`Allow: GET`) on the custom
  domain, the Railway production address and staging alike. Fixed in
  `1c0a9fc` (GET and HEAD, tested); it shows green once deployed.
- **CI had never run.** `${{ runner.temp }}` at job level made `ci.yml`
  invalid, so each push failed instantly and the PR had no checks. Fixed in
  `48d32f5`; `actionlint` 1.7.12 is clean.
- **Sentry in Railway, checked without printing a value:** `SENTRY_DSN` and
  `SENTRY_FRONTEND_DSN` are set on `hba-platform` (production and staging)
  and `hba-platform-staging`, all EU (`*.de.sentry.io`), backend and frontend
  different. `RAILWAY_ENVIRONMENT_NAME` reads `production` and `staging`.
  `/api/client-config` is 404 on production until the merge is deployed.
- **The Production ChatGPT site still answers signed out** (200, 114,825
  bytes). With the repository public again, its address was removed from
  ADR 0069 (`22eb6a5`); earlier commits on this branch still hold it.
- `ANOMALY job_gave_up` no longer logs the payload or error text (`9b00440`).
- The account-level 2FA list is now a recommendation outside the roadmap.

## 25 October, night: Batch 1 shipped, release gates rehearsed

- **Merged and deployed** (owner's go-ahead): PR #125 as `a2ae261`; `main` and
  `production` both there. Both sites answered HEAD 200 about 80 s later;
  `/api/client-config` reports `production` / `staging` and release `a2ae261`.
- **Release gates, on production's dump of 25 October 00:04 UTC** (24.6 MB,
  Postgres 18.6; 30 nightly dumps in the bucket), restored into a throwaway
  local database with the owner's authorisation, then deleted with the dump:
  - *Restore:* `--exit-on-error`, clean. Schema `a6c9e3f70018` = code head.
    19 profiles, 7,077 attributed orders, 15,713 orders, 597 audit entries,
    24 accounts; **no payment, payroll month or snapshot yet**.
  - *Protections:* 18 triggers; a real UPDATE and DELETE on `audit_event` are
    refused. The runbook's `WHERE false` probe could not show this; corrected.
  - *Reconciliation* (`docs/repair/batch-1/reconcile.py`, read-only): every
    figure zero, because no month has been approved yet. Clean but untested on
    real payroll; **rerun after the first approval.**
  - *Migration rehearsal*, head back to before `a6b1c4e20006` (17 steps) and
    forward: the newest step rolls back and forward cleanly. Deeper, three
    guards refuse on real data, each by design and each undone completely:
    a payment request exists (ADR 0062's step); a `customer_service` holder
    exists (that role's step, a check-constraint failure); declined profiles
    exist (`a6b1c4e20006` itself). With those rows set aside in the copy, 16 of
    17 steps ran. Upgrading back left every count and trigger unchanged.
    **So a code rollback past ADR 0062 is not available while that data
    exists; the way back from there is this restore.**
  - *`SETTINGS_ENCRYPTION_KEY` cases* on the copy's real saved WhatsApp and
    Shopify-tag secrets: missing, malformed and wrong key all leave the secret
    unused, describe the problem, and raise nothing. The right key is proven
    by production using those secrets.
- **Worth knowing:** production runs Postgres 18.6; local tests and CI use 17.
- Throwaway databases `hba_batch1`, `hba_batch1_ci` and `hba_restore_check`
  dropped.

## Owner decisions and actions

| Item | State |
|---|---|
| Repository private | **done by the owner**, 25 October 2026 |
| Error tracking: Sentry | **chosen by the owner** |
| Uptime checker | recommended UptimeRobot; owner creates the account |
| Branch protection on `main` and `production` | **blocked**: GitHub answers *"Upgrade to GitHub Pro or make this repository public to enable this feature"* for both branches and for rulesets (checked 25 October). Needs GitHub Pro (owner's purchase) or nothing. |
| 2FA on GitHub | not readable with the current token (no `user` scope); the owner checks Settings → Password and authentication, for both signed-in accounts (`yahyaAboamer`, `hbaaesthetics-lgtm`) |
| Sentry DSNs set in Railway (staging, production) | waits for the owner's Sentry projects; nothing is sent until set |

## Found along the way, not part of Batch 1

- `ANOMALY JOB_GAVE_UP` writes a failed job's whole payload and its error text
  into Railway's logs (`app/services/jobs.py` via `app/core/signals.py`),
  against `signals.py`'s own note never to pass a customer's details. Sentry
  never receives it (log values are filtered), but the logs keep it. A small
  separate fix.
- Mail-provider and media error texts are logged as they come
  (`notifications.py`, `payments.py`, `inbox/media.py`, `order_ops/polling.py`);
  they can quote an address. Same treatment: filtered for Sentry, still in
  the logs.
- The runbook first told the owner to set Sentry's variables on both services.
  Corrected: values are typed on `hba-platform` in each environment, and
  `hba-platform-staging` gets references (`docs/operations.md`).

## Local environment notes

- The worktree has no `.venv` or `frontend/node_modules` of its own; each
  workstream that needs one creates it here (both are git-ignored).
- Docker Desktop was not running on 25 October; it lives at
  `D:\Docker\DockerDesktop`. Backend tests use a **separate disposable
  database, `hba_batch1`**, on the 5433 test server, so they cannot collide
  with another session's run on `hba_platform_test`. Drop it when Batch 1 is
  done.

## How to resume

1. Read this file and `git log --oneline -15` on `phase-1/batch-1`.
2. Re-check the remote: `git ls-remote --heads origin main production`.
3. Continue the first workstream above that is not *done*.
