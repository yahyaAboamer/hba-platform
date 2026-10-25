# Phase 1 — progress and checkpoint

The working state of `docs/plans/2026-10-25-phase-1-foundations.md`. Updated
at each milestone, so that a restarted session resumes from here instead of
redoing finished work. Newest facts first within each section.

## Where things are

| | |
|---|---|
| **Branch** | `phase-1/batch-1`, cut from `claude/hba-erp-architecture-55746a` (which holds ADRs 0065–0069, the two mockups and the plan) |
| **Base** | `origin/main` = `origin/production` = `c82785d` (checked 25 October 2026) |
| **Pull request** | https://github.com/yahyaAboamer/hba-platform/pull/125 into `main`, opened 25 October; first CI run not yet read. **Next on resume:** read its checks, fix anything red, record the backend job's duration here, then narrow the CI time limits. |
| **Merged / deployed** | nothing; neither is allowed without the owner's word for each |

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
