# Where the work is — 7 November 2026 (Payments refined; Production next)

Supersedes `2026-11-06-continuation-handoff.md`, which superseded
`2026-10-30-continuation-handoff.md` and `2026-10-28-continuation-handoff.md`.
The 28 October handoff's sections *Where the code lives*, *State to know*,
*Owner actions*, *Decisions not to reopen*, *How the work has been done* and
*Corrections* still hold and are not repeated here. Phase 2's plan, with every
batch's *As built* notes, is `2026-10-30-phase-2-frame.md`; the overall
picture is `hba-os-roadmap.md`.

## The exact position

Re-read the remote before describing it: `git ls-remote --heads origin main production`.

| | |
|---|---|
| **Code on both sites** | `origin/main` = `origin/production` = `7d0b6a6` (PR #154), deployed 6 November on the owner's order. This handoff's own docs-only PR follows it on both |
| **Migration head** | `c9e4a7d10024` (Khazenly runs, PR #144), unchanged: PRs #151–#154 add no migration |
| **Railway settings** | As in the 6 November handoff: `.railway/railway.ts` is the source; run `railway config plan` and read every line before any `apply` |
| **Branches** | No work branch open |

## What shipped since the last handoff

All on 6 November, all on staging and production. The full record, with
findings, screenshots and lessons, is
`docs/design-refinement/payments/JOURNAL.md`; the private captures are in
`D:\Desktop\HBA\HBA Engineering\evidence\payments-refinement-2026-11-06.zip`
and `payments-refinement-round2-2026-11-06.zip`, outside the repository.

| PR | What |
|---|---|
| #150 | Phase 2 closed; the 6 November handoff |
| #151 | Payments: approving asks once and says what it fixes; recording says it sends nothing; a future date is refused |
| #152 | Payments: focus returns to *Approve* when the approval question is cancelled |
| #153 | The payments desk on a phone: rows instead of a clipped table, amount first, the next act first (ADR 0074) |
| #154 | Payments refined, two review rounds (ADR 0075): the desk's totals are the server's *Left to send* and *Recorded*; the export's *Total required* and a draft *Total to send* are gone because neither meant what it said; overpaid rows show the approved amount with the excess to settle; new labels (*Ready to send*, *Overpaid*, *Transfer*, *Sent on*); three tiers of message; less repeated text; the shared month picker 44px with 16px text on phones. **InstaPay:** a model may paste InstaPay's whole share message; the platform keeps only the `ipn.eg` link, and links already saved with text around them open cleanly too, without rewriting anyone's stored details. **Open InstaPay** stays everywhere at the owner's word |

Production was checked read-only after the deploy, signed in by the owner:
17 of 17 InstaPay models on the November desk show a clean, openable link; no
console errors; nothing changed.

## Remaining, in order

1. **Batch 4.1 — Production moves in** (roadmap, Phase 4; ADR 0069). The
   owner is exporting the source code, data and files. The export goes in
   `D:\Desktop\HBA\HBA Engineering\evidence\production-export-2026-11-07\`,
   outside the repository, and is never committed. The first session reads it
   in full, reports an inventory, risks and a batch plan, and stops for the
   owner's approval before building. Before exporting, ADR 0069 asks the owner
   to make the ChatGPT site require sign-in.
2. **Phase 3 — Shared records:** one page per order with search across
   departments; a shared customer record and staff profiles when a second
   department needs each.
3. **Owner decisions left from 2.4:** a second owner who also holds the
   operations manager role keeps it locked on their page; the server's
   refusals still say "admin".
4. **Payments follow-ups** (journal §10, none urgent): the model portal's
   Payments screen (`portal/MyPayments.tsx`) given the same pass; the model
   profile (`AffiliateDetail.tsx`) still uses the old state words *Approved*
   and *More sent than due*; the desk keeps the chosen month in page state,
   not the address (shared with other screens); recapture the overpaid states
   in screenshots.
5. **Carried:** a test alert from staging and the monitor green (Batch 1.1);
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
  <short-commit>`, run where `railway status` sees the project: the main
  checkout, not a worktree), and grep the deployment log for "Running
  upgrade" when a migration ships.
- **Railway CLI on Git Bash:** `railway config plan/apply` needs
  `env _="$(cygpath -m <path to railway.exe>)" railway.exe …` (see the header
  of `.railway/railway.ts`), and `npm ci` in `.railway/` first.
- **Auto-merge is not allowed** on the repository: wait for CI (~13 min) with
  one background wait, then merge by hand on the owner's word.
- **Disposable databases** in the Docker Postgres on 5433, as before; never
  bare pytest, never two pytest processes at once. A worktree has no `.venv`:
  point the suite runner's `PYTHON` at the main checkout's
  `.venv/Scripts/python.exe`. If Docker is not running, start
  `D:\Docker\DockerDesktop\Docker Desktop.exe` and wait for `pg_isready`.
- **Disk:** C: filled to 0 MB on 6 November; evidence ZIPs go on D:.
