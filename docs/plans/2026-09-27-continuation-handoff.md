# Where the work is — 27 September 2026 (batches K and L)

**Replaces `2026-09-25-continuation-handoff.md`**, which is kept with a banner
for its record of batch J, its follow-up, the merge and promotion of 26
September and the list of old branches. Nothing was deleted.

## The exact position

Read on 27 September; re-read the remote before describing it
(`git ls-remote --heads origin main production`).

| | |
|---|---|
| **Branch** | `repair/batch-2` |
| **Last code commit** | `8ed17fb` (batch L). This handoff is committed after it: run `git rev-parse --short HEAD` for the current head |
| **`origin/repair/batch-2`** | `8ed17fb` |
| **`origin/main`** (staging) | `8ed17fb` - level with the branch's code |
| **`origin/production`** | `156e65b` - 6 commits behind `main` (see *Production*) |
| **Migration head** | `d7a2c4e10003` (a model paid outside Egypt, batch K, ADR 0046) ← `d4e7a2c90003` ← `c3d51e7a0002` ← `b1f0a40c0001`; `alembic heads` reports the one head |
| **Backend** | **2,145 tests, 86 files, all passing** through `run-suite.sh` on `8ed17fb` (batch L's own run, recorded in its commit). Re-checked 27 September with `--collect-only`: 2,145 in 86 files. That is a count, not a new run |
| **Frontend** | **492 tests, 29 files, all passing**, re-run 27 September on `8ed17fb`. `npm run build` green in batch L's run; not re-run for this handoff |
| **Where this ran** | this Windows machine; the disposable Postgres in Docker on 5433 (`hba_platform_test`) |

## Standing restrictions

- **Merge and deployment are separate permissions, given each time**
  (`CLAUDE.md`). The instructions that moved `main` on 26 and 27 September
  covered those occasions only; none is standing.
- **Historical finalisation locked.** No production data read.
- **No destructive fixture against staging or production.**

## What shipped since the 25 September handoff

| Commit | What |
|---|---|
| `70d018a` | Docs: the merge and promotion of 26 September, and the branches to delete (recorded in the 25 September handoff) |
| `db65892` | **Backfill attaches every order a code already had.** Continuations shared one dedupe key, so a code's backfill stopped after two batches (1,000 orders) and reported success - on staging HBA10 was attached January to mid-March only. Each continuation now carries a cursor; `ATTACH_ORPHANS` runs hourly and re-queues any code with an orphaned order that would resolve to it. `docs/limits.md` has the entry |
| `af0e6ad` | **Batch K - the way in, in the portal's look** (owner's audit of 26 September, from the mockup he approved). Sign in, invitation, reset, first run, the application and the waiting screen. Password minimum 8 from one constant (three screens still enforced 12). One dark portal frame (`AuthShell`), a two-step bar, the details form trimmed, *In Egypt / Outside Egypt*, the InstaPay guide folded, the waiting screen *In review* with a four-step path. **Outside Egypt now applies** (ADR 0046, migration `d7a2c4e10003`). A filled green button with dark text inside `.auth` only (ADR 0047) |
| `fbdd3bc` | `test_audit_words` reads source as UTF-8 (on Windows it failed on the curly quotes whatever the code did) |
| `6f3e1b3` | `CLAUDE.md`: the suite after batches J and K |
| `8ed17fb` | **Batch L - the model's Home past the export** (owner's decisions of 27 September, ADR 0048). One request, `GET /api/me/home/{month}`; the month once, as a control opening a bottom sheet shared with Orders and Ranking; *Earned* and *Next payment · Around 3 October* in one card; every order outcome, so the parts add up to the uses; a like-for-like comparison worked out on the server in Cairo days; rank, average order and content tiles; *Share your code*; the year as bars; tab icons; her code as a copy chip; Payments opens with *Coming up* |

Each batch's own check, from its commit: K - 82 backend files (2,097 tests),
445 frontend tests, build, a headless walk at 390px against a throwaway
local database. L - 86/86 backend files (2,145), 492 frontend, build, the same
390px walk.

## Staging

- `main` moved to `8ed17fb` on the owner's instructions of 27 September
  (batch K: deploy to staging; batch L: deploy it).
- **Is it live?** 27 September, unauthenticated: `/api/health/live` answers
  200, and batch L's `/api/me/home/2026-09` answers **401** where an unknown
  route answers 404, so batch L's backend is serving. The Railway connector
  lists no projects from here, so the deploy log, the frontend bundle and the
  migration were not read directly.
- **Not yet done on staging:** a signed-in look at batches K and L (Jev
  Browser is now set up for it - see *Tooling*); `SETTINGS_ENCRYPTION_KEY`
  on `hba-platform-staging` - its status is unknown (needed for the
  connection form, runbook `docs/runbooks/settings-encryption-key.md`);
  *Share your code*'s `/discount/<CODE>` link checked once against the live
  shop (ADR 0048).

## Production

`156e65b` since 26 September. It does **not** have `db65892`, batch K, batch
L or migration `d7a2c4e10003` - so **the backfill defect (a code stops after
1,000 orders) is live there**, which bears on the owner's promotion decision.
Promotion is its own permission, and the release gates below have not run.

## Remaining, in order

1. **Evidence for K and L in the parity documents.** Neither batch added a
   section to `docs/repair/batch-2/visual/CHECKLIST.md`, a row to
   `SCREEN_MATRIX.md`, or committed captures; their evidence is the commit
   messages and ADRs 0046-0048. Add the sections and captures (390, both
   themes) for the sign-in family, application, waiting screen, Home, the
   month sheet and Payments' *Coming up*.
2. **Stale entries in `SCREEN_MATRIX.md`** (not edited on 27 September, to
   keep that change to the hierarchy): its authority line points to
   `docs/decisions/`, which does not exist - the owner's decisions are in
   `docs/redesign/decisions/` (D01-D12) and the ADRs; the kept-differences
   rows *`E£`, not `EGP`* (already marked superseded in CHECKLIST's closing
   table) and *no "payment usually recorded in N days"* (superseded by ADR
   0048's *Next payment · Around 3 October*).
3. **Staging, signed in:** walk batches K and L as the model and the admin.
4. **Implementation carried from 25 September:** item 14, the export's *More
   actions* card on the profile; item 15a's remainder, future months' terms
   and the 2027 year button (needs terms past this year to compare).
5. **Verification items 20-29**, unchanged: *Attributed orders* layout, the
   export's blank order view, receipts, earnings line names on a guarantee,
   images, printing, staging exercises, real data, devices, old
   `payment-record` shots.
6. **Release gates** (below).
7. **Order-import completeness on real data** (31a): needs the owner's
   go-ahead for production and a working route into Railway.
8. **The 13 old remote branches** the owner asked to delete are all still on
   `origin` (checked 27 September). Tips are in the 25 September handoff.
   Deletion needs the owner on GitHub, or the owner's explicit go-ahead to a
   session that can.

## Release gates

Neither has run; do not describe the repair as releasable.

1. **Reconciliation against an authorised restored copy of real data.**
   `docs/repair/batch-1/reconcile.py` has only run against the test database.
2. **Migration/rollback rehearsal** for `b1f0a40c0001`, `c3d51e7a0002`,
   `d4e7a2c90003` and `d7a2c4e10003`, with the `SETTINGS_ENCRYPTION_KEY`
   cases (`docs/runbooks/settings-encryption-key.md`, *Rehearsal*). The first
   three are already applied on production (promoted 26 September without the
   gates, by the owner's choice); `d7a2c4e10003` is additive (one boolean with
   a default; its downgrade drops it).

## Tooling

- **Jev Browser** (`.mcp.json`): `npx -y @jkudish/jev-browser` (0.8.0 on
  npm). Its tool is **`jev_navigate`** - a task and a start URL, and its own
  agent clicks and types; there are no separate click/type tools and that is
  not a fault. Sign-in: `password_env: "JEV_PASSWORD_STAGING"`, filled only on
  `JEV_BROWSER_PASSWORD_ORIGIN` (the staging host), never in the model's
  context. Both variables are set on this machine (presence checked, value
  never read). Staging only, unless production is explicitly authorised.

## Decisions not to reopen (added in K and L)

- **Password minimum is 8**, one shared constant, server and screens.
- **A model abroad applies without a destination** (ADR 0046):
  `payout_abroad` records why nothing is on file, and the first destination
  saved clears it. How HBA pays abroad is *not* decided.
- **The sign-in family and onboarding use the portal look for everyone**, and
  a filled green button with dark text **inside `.auth` only** (ADR 0047).
  Everywhere else the export's hairline primary stands.
- **The model's Home goes past the export exactly as ADR 0048 names**; the
  export stays the reference for everything it does not name.
- **The comparison is like for like**, same days of the month before, Cairo
  days, on the server.
- **An ended month nobody approved reads *Awaiting approval***.
- **A use is every order but a failed delivery** (D03, unchanged); Home shows
  all five outcomes so they add up.
- **Better than the export is welcome** (owner, 27 September) - through a
  mockup the owner approves and an ADR recording the divergence. It is not licence
  to diverge without both.
- The 25 and 24 September handoffs' lists all stand.

## Needs the owner

- **Currency: the rule is written, its provenance is not.** The owner chose
  `E£` on 12 September (`docs/redesign/reports/10C1-design-parity-admin.md`;
  the design prompt said *Keep E£ as I approved*). The 23 September sweep
  (`f83b4fc`) switched to the export's `EGP 1,062.00`, and `docs/RULES.md`
  (24 September) records EGP as the rule and calls `E£` "ours, not the
  design's". No decision record shows the owner reversing `E£`. `RULES.md` is
  the current written rule and was not changed; the owner should confirm EGP
  (then record it) or restore `E£` through an ADR.

## What went wrong, so the next session does not repeat it

- **The handoff went stale across two deployed batches.** `CLAUDE.md` kept
  pointing at 25 September and `AGENTS.md` at 24 September while K and L
  shipped to staging. A batch that reaches `main` ends with the handoff
  replaced.
- **Evidence stayed in commit messages.** K and L were verified, but nothing
  in the parity documents says so; the next reader of the matrix sees neither.
