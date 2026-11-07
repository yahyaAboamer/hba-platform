# Where the work is — 7 November 2026 (Batch 4.1 live on staging and production)

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
| **Code on both sites** | `origin/main` = `origin/production` = `32f6936` (PR #158), deployed 7 November on the owner's order ("merge after CI … deploy to staging and production"). This handoff's own docs-only PR follows it on both |
| **Migration head** | `d1b4f0a10025` (Production's tables; the role checks gain Production's four levels), applied on staging and production 7 November. Joins the release gate's migration/rollback rehearsal list; rehearsed up/down/up on a disposable database |
| **Production's data** | Imported on staging and on production 7 November from the 2 November export plus the 4 task confirmations of 6 November read from the live site. Both reconciled count by count and field by field, and compared with the live site's own `/api/state`: every order, task, sample, supplier and product equal, in the same order |
| **Railway settings** | As in the 6 November handoff: `.railway/railway.ts` is the source; run `railway config plan` and read every line before any `apply` |
| **Branches** | none open |

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

## What Batch 4.1 built (ADR 0069, ADR 0076): PRs #156, #157, #158

- **`production-ui/`**: Production's screens from the ChatGPT export, in their
  own Vite build, served at `/production-app/` and shown inside HBA's frame at
  `/production/`. Every edit to the export is listed in `production-ui/CHANGES.md`.
- **`app/modules/production/`**: the old server's requests under
  `/api/production/…` on `production_` tables, behind HBA's sign-in, each
  change audited (department `production`). Its state answer was compared with
  the live site's on 7 November: every field of every order, task, sample,
  supplier and product matched, in the same order.
- **Team and access**: Production viewer, QC, staff, manager. QC is Production's
  alone. Approving a supplier payment is the owner's.
- **The strip**: HBA's sidebar folds to 64 px while Production is open; a thin
  bar on a phone.
- **#157**: the import also takes task confirmations made on the old site after
  the export from its live `/api/state` (who, when to the second, stage,
  progress, the activity line); a later change it cannot date refuses the import.
- **#158**: every text sort in Production's state is byte order (`COLLATE "C"`),
  as the old SQLite was; staging's Postgres sorted the 40 products by language
  rules. Also steadied the frame's address test (it raced on slow CI).
- **`scripts/production_import.py`**: the one-off import with its count-by-count
  and field-by-field reconciliation. Proven on a disposable copy: every count
  and every compared field matched.

## Remaining, in order

1. **Batch 4.1, the rest**, in this order:
   1. **Give the team their levels** in Team and access (production); they
      use HBA's sign-in. The owner checked staging signed in; all 24 screens
      read the same as the old site apart from the editing controls an owner gets.
   2. **Switch-over** when the owner says: the team stops editing on ChatGPT.
      The owner's plan (7 November): anything edited on ChatGPT after today is
      re-entered by the Production team in HBA rather than imported again. If a
      re-import is wanted instead, it must run before anyone edits in HBA:
      read a fresh `/api/state`, run the import with `--replace` (it refuses
      once uploads exist), and reconcile. Then the owner retires the ChatGPT site.
   3. **How the import was run** (the script and the private files are not in
      the image: `scripts/` is in `.dockerignore`): a generator outside the
      repository packs the script and the four private files into one Python
      program, piped to `railway ssh --service <svc> --environment <env> --
      python -`; it unpacks into a temp folder, runs with `PYTHONPATH=/app`,
      prints the reconciliation and deletes the temp folder. The packed files
      are deleted locally after use. The private files stay in
      `evidence/production-export-2026-11-07/import-files/`: `fixture-lists.json`
      (made from the export's `lib/demo-data.ts` by `make-fixture-lists.mts`,
      run with `node --experimental-strip-types` beside a copy of that file),
      `fixture-texts.json` (the sentences `production-ui/CHANGES.md` lists), and
      `live-state-<date>.json` (the old site's `/api/state`).
   4. **Phone check on production** with the owner signed in (staging's was done
      at 746 px in the owner's session; production's screens are the same build).
   5. **Batch 4.1b**: supplier accounts that reach only their own orders.
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

## Batch 4.1: known, accepted differences

- In the activity feed, lines the old site wrote in the same second may sit in
  a different order within that minute (11 lines of 28 October today); the
  old database's order for them was not a sort that can be repeated.
- Three imported orders hold a dash as their dates; they read "—" as before,
  but the hidden ISO copy is empty instead of a dash.
- Uploaded photos now need a signed-in Production holder; the old site served
  them to anyone with the link.
- `update_task` refuses a date that is not one (the old server stored it).
- A confidential document is listed only to Production QC, staff, manager and
  the owner (the old server listed every document to anyone).
- An upload must state its size (`Content-Length`); one that does not is refused.
- The import's `--replace` refuses once Production holds uploaded files.
- Rolling back `d1b4f0a10025` leaves any Production role rows in place behind a
  `NOT VALID` check; revoke them first if the rollback is meant to last.

## Batch 4.1: decisions not to reopen

ADR 0076 in full, in particular: tables not a document; the screens keep
their look and behaviour; HBA's sign-in only; QC kept apart from editing;
money in piastres, payment approval owner-only; supplier accounts are 4.1b.
