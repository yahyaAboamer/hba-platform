# Where the work is — 30 October 2026 (Phase 2: batches 2.0–2.2 live; 2.3 next)

Supersedes `2026-10-28-continuation-handoff.md`. Its sections *Where the code
lives*, *State to know*, *Remaining* items 2–7, *Owner actions*, *Decisions
not to reopen*, *How the work has been done* and *Corrections* still hold and
are not repeated here. Phase 2's plan, with every batch's *As built* notes, is
`2026-10-30-phase-2-frame.md`; the overall picture is `hba-os-roadmap.md`.

## The exact position

Re-read the remote before describing it: `git ls-remote --heads origin main production`.

| | |
|---|---|
| **Code on both sites** | `origin/main` = `origin/production` = `2e1f094` (PR #140), deployed 30 October on the owner's order; browser-checked on staging and, read-only, on production |
| **Migration head** | `b2d7f4a10023` (Today's three indexes) on staging and production. It joins the release gate's migration/rollback rehearsal list |
| **Branches** | No work branch open. Batch 2.3 starts from `origin/main` as `claude/phase-2-2.3-settings` |
| **Config** | Unchanged since 28 October |

## What Phase 2 has shipped so far

| PR | What |
|---|---|
| #136 | 2.0 — frontend department folders (moves only) |
| #137 | 2.1 — departments declared once, the sidebar, the phone layout, department addresses with redirects |
| #138 | 2.2 — Today (`GET /api/today`), the sidebar's numbers from the same read; someone with two or more departments starts on Today |
| #139 | "Asked to change their order" counted as Confirmations' Change card counts it (was Chats' all-time view, showing 100 on production) |
| #140 | Payments waiting for approval only in months that have ended (owner's decision, 30 October): one Today row per ended month, the running month never; the Payments badge uses the same count |

Each had an independent review before its PR; findings above Low were fixed.

## Remaining, in order

1. **Batch 2.3 — Settings split** (plan section *Batch 2.3*): Me,
   Integrations (frame 6), Company; today's sections moved as the plan's table
   says; `/api/integrations`; the activity log filtered by department; old
   `/settings?section=…` links redirected. Me and Company have no frame: show
   the owner screenshots before the PR.
2. **Batch 2.4 — Team and access by department** (frame 5), with a security
   review of the access rules.
3. At the end of Phase 2: replace this handoff.
4. Then the old handoff's *Remaining* 2–7 (Production moves in, retiring
   n8n, reconciliation rerun, carried items).

## Working notes from this phase

- **Owner's word twice:** stop before merging, and again before deploying.
- **Deploy:** `git merge-base --is-ancestor origin/production origin/main`,
  then `git push origin origin/main:refs/heads/production`; watch
  `hba-platform` (production) or `hba-platform-staging` (staging) with
  `railway status --json` until the commit reaches SUCCESS, and grep the
  deployment log for "Running upgrade" when a migration ships. A helper doing
  this lives outside the repository at `D:/claude-tmp/p2/wait-deploy.sh`
  (`RENV=<env> RSVC=<service> bash … <short-commit>`).
- **Auto-merge is not allowed** on the repository: wait for CI (~9–12 min)
  with one background wait, then merge by hand on the owner's word.
- **Disposable databases** in the Docker Postgres on 5433: `hba_p2` (pytest;
  the whole suite with `OUT_DIR=D:/claude-tmp/p2/suite
  PYTHON=../../../.venv/Scripts/python.exe DATABASE_URL=…/hba_p2 bash
  docs/repair/batch-1/run-suite.sh 540`) and `hba_browser_p2` (local browser
  checks). Local background schedulers overwrite seeded Bosta/Shopify data.
- **Browser checks:** `playwright-cli` session `hbacheck`, run from
  `D:/claude-tmp` so `.playwright-cli/` is not written into the worktree;
  on production use `waitUntil: "load"` plus a short wait (some pages never
  reach network idle).
- **Today's rule:** every number on Today comes from the same function the
  department's own screen uses; departments expose `today_look` through
  `public.py`, and import-linter enforces it.
