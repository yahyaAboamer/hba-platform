# Phase 1 — progress and checkpoint

The working state of `docs/plans/2026-10-25-phase-1-foundations.md`. Updated
at each milestone, so that a restarted session resumes from here instead of
redoing finished work. Newest facts first within each section.

## Where things are

| | |
|---|---|
| **Branch** | `phase-1/batch-1`, cut from `claude/hba-erp-architecture-55746a` (which holds ADRs 0065–0069, the two mockups and the plan) |
| **Base** | `origin/main` = `origin/production` = `c82785d` (checked 25 October 2026) |
| **Pull request** | not opened yet |
| **Merged / deployed** | nothing; neither is allowed without the owner's word for each |

## Batch 1 — the safety net

| Workstream | Who | State |
|---|---|---|
| CI workflow (`.github/workflows/ci.yml`, `run-suite.sh` learns `PYTHON`, one-migration-head check) | subagent, Sonnet, medium | running; test DB `hba_batch1_ci` |
| Sentry, backend (`sentry-sdk`, scrubbing, worker failures, `/api/client-config`) | subagent, Opus, high | running; test DB `hba_batch1` |
| Sentry, frontend (`@sentry/react`, scrubbing URLs of their tokens) | subagent, Sonnet, medium | running |
| Owner's setup guide: Sentry, uptime, 2FA, branch protection (`docs/runbooks/monitoring-and-account-security.md`) | orchestrator | **done** |
| Review, local tests, commits | orchestrator | not started |
| Push, PR, first CI run measured | orchestrator | not started |

**Contract between the Sentry workstreams:** `GET /api/client-config`, no
sign-in needed, returns `{"sentry_dsn": str | null, "environment": str | null,
"release": str | null}`. The DSN is the frontend project's (`SENTRY_FRONTEND_DSN`).
Nothing in it is secret: a browser DSN is public by design.

## Owner decisions and actions

| Item | State |
|---|---|
| Repository private | **done by the owner**, 25 October 2026 |
| Error tracking: Sentry | **chosen by the owner** |
| Uptime checker | recommended UptimeRobot; owner creates the account |
| Branch protection on `main` and `production` | **blocked**: GitHub answers *"Upgrade to GitHub Pro or make this repository public to enable this feature"* for both branches and for rulesets (checked 25 October). Needs GitHub Pro (owner's purchase) or nothing. |
| 2FA on GitHub | not readable with the current token (no `user` scope); the owner checks Settings → Password and authentication, for both signed-in accounts (`yahyaAboamer`, `hbaaesthetics-lgtm`) |
| Sentry DSNs set in Railway (staging, production) | waits for the owner's Sentry projects; nothing is sent until set |

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
