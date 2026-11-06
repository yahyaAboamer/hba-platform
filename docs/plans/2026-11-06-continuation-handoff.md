# Where the work is — 6 November 2026 (Phase 2 complete)

Supersedes `2026-10-30-continuation-handoff.md`, which superseded
`2026-10-28-continuation-handoff.md`. That older handoff's sections *Where the
code lives*, *State to know*, *Owner actions*, *Decisions not to reopen*, *How
the work has been done* and *Corrections* still hold and are not repeated
here. Phase 2's plan, with every batch's *As built* notes, is
`2026-10-30-phase-2-frame.md`; the overall picture is `hba-os-roadmap.md`.

## The exact position

Re-read the remote before describing it: `git ls-remote --heads origin main production`.

| | |
|---|---|
| **Code on both sites** | `origin/main` = `origin/production` = `f9963c7` (PR #149), deployed 6 November on the owner's order |
| **Migration head** | `c9e4a7d10024` (Khazenly runs, PR #144) on staging and production. It joins the release gate's migration/rollback rehearsal list |
| **Railway settings** | `.railway/railway.ts` (PR #148) was applied to staging and production on 6 November after a read-only `railway config plan` showed only the expected changes; the root `railway.json` was deleted (PR #149). Production's service now holds its health check (`/api/health/ready`, 300 s) and restart policy (ON_FAILURE, 5) itself. Before any later `railway config apply`, run `railway config plan` and read every line: anything missing from the file is deleted. Staging's plan always shows `restartPolicyType null → "ON_FAILURE"`; that is how Railway shows its default, not a pending change |
| **Railway billing** | The HBA_Server workspace is on Hobby; the owner paid the overdue invoice on 6 November (deploys had been refused as "trial expired" on 5 November). The stray staging copy was removed; the offline projects cost only their volumes |
| **Branches** | No work branch open |

## What shipped since the last handoff

| PR | What |
|---|---|
| #142, #144 | Operations: the Khazenly bulk-confirm file from the Active Orders export, and a history of every run; customer service holds the tab (ADRs 0071, 0072) |
| #143 | A Today order test that broke on the first of the month |
| #145 | 2.3 — Settings split: Me, Integrations, Company; department settings into their departments; the activity log by department |
| #146 | The content manager invites models (ADR 0073) |
| #147 | 2.4 — Team and access by department (frame 5), the two-step reminder; contract and *As built* in `2026-11-04-batch-2.4-contract.md` |
| #148, #149 | Railway Config as Code moved to `.railway/railway.ts` before Railway's 1 December cutoff |

2.4's staging check (6 November): the owner's account gave the test account
Inbox staff and took it back; both confirmations named what changes, the page
showed the new permissions, and the activity log reads "Gave … Inbox staff
access" / "Took Inbox staff access from …". Signing in as the test account to
see its sidebar change was skipped, as for 2.3, at the owner's word.

## Remaining, in order

1. **Batch 4.1 — Production moves in** (roadmap, Phase 4). Recommended ahead
   of Phase 3 because the ChatGPT production site has no sign-in until it is
   retired. It waits only on the owner's export of the source code, data and
   files; read it in full from a folder outside the repository and never
   commit it. Batch 1.2, which it also waited on, is complete.
2. **Phase 3 — Shared records:** one page per order with search across
   departments; a shared customer record and staff profiles when a second
   department needs each.
3. **Owner decisions left from 2.4:** a second owner who also holds the
   operations manager role keeps it locked on their page; the server's
   refusals still say "admin".
4. **Carried:** a test alert from staging and the monitor green (Batch 1.1);
   the reconciliation rerun after the first payroll approval (Batch 1.0);
   retiring the n8n order-confirmation project (export its workflows first);
   the old handoff's remaining items.

## Working notes

- **Owner's word twice:** stop before merging, and again before deploying.
  A Railway `config apply` to production is a production change and needs the
  same word.
- **Deploy:** `git merge-base --is-ancestor origin/production origin/main`,
  then `git push origin origin/main:refs/heads/production`; watch with
  `D:/claude-tmp/p2/wait-deploy.sh` (`RENV=<env> RSVC=<service> bash …
  <short-commit>`), and grep the deployment log for "Running upgrade" when a
  migration ships.
- **Railway CLI on Git Bash:** `railway config plan/apply` needs
  `env _="$(cygpath -m <path to railway.exe>)" railway.exe …` (see the header
  of `.railway/railway.ts`), and `npm ci` in `.railway/` first.
- **Auto-merge is not allowed** on the repository: wait for CI (~13 min) with
  one background wait, then merge by hand on the owner's word.
- **Disposable databases** in the Docker Postgres on 5433, as before; never
  bare pytest, never two pytest processes at once.
