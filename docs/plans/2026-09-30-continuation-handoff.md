# Where the work is — 30 September 2026 (data reset, batches Q1–Q3)

**Replaces `2026-09-28-continuation-handoff.md`**, kept for its record of
batches O and P. Its *Release gates* and *Decisions not to reopen* still stand
unless this file says otherwise. Its data follow-ups (Mazen's parcels, #29936,
the ~1,100 in-flight orders, the *earned before return* count) are **moot**:
the data they were about was erased on 29 September (below).

## The exact position

Re-read the remote before describing it (`git ls-remote --heads origin main production`).

| | |
|---|---|
| **Branch** | `repair/batch-2` at `c015066` (Q1 `1c791fd`, Q2 `8e346b8`, Q3 `c015066`), plus this handoff correction |
| **`origin/main`** (staging) | `c015066` — pushed and merged 30 September on the owner's order |
| **`origin/production`** | `c015066` — merged 30 September on the owner's explicit order (it was fast-forwarded to `4be2ae4` on 29 September) |
| **Deploys** | Railway staging `hba-platform-staging` and production `hba-platform` both **SUCCESS on `c015066`** (30 September 13:46 Cairo); `/api/health/ready` 200 on both |
| **Migration head, both databases** | `a6b1c4e20006` (ADR 0052), read back from each; the status check accepts `declined`; no guard trigger disabled; 0 model profiles |
| **Backend** | **89/89 files** through `run-suite.sh` at the final Q3 code (label `q3-final2`) |
| **Frontend** | 560 tests across 34 files; `npm run build` green |

**A release gate was skipped by the owner's order:** `a6b1c4e20006` was
rehearsed up/down/up on a throwaway database, not on a restored copy of real
data, before production. Both databases were empty when it ran, so the risk was
low. Staging acceptance of the Models tab by the owner is still to happen.

## 29 September: both environments emptied (owner's order)

The owner asked to start from zero on **staging and production** so every flow
(approving a model, codes, history, payments) could be mapped with real data.

- Done by `wipe-business-data.sql` (session scratchpad, not in the repo): one
  transaction per environment, guarded by the policy row's month (`2026-08`
  staging, `2026-09` production), the append-only triggers lifted inside it and
  verified re-enabled afterwards.
- **Kept:** staff accounts and roles (one admin, `yahyaaboaamer@gmail.com`, on
  each), `staff_preference`, `policy_version`, `alembic_version`,
  `shopify_connection` (empty on both — Shopify is configured by environment
  variables, untouched).
- **Everything else is empty**, including every model account (the staging
  test model `yousefabooamer@…` too), orders, parcels, targets, payroll,
  payments, audit and jobs. The worker re-queues its recurring jobs, so recent
  Shopify orders reappear unattributed until models and codes exist.
- **The owner chose no fresh backup.** The only way back is the nightly
  `db-backup-staging` / `db-backup-production` runs of 29 September 12:40 in the
  environments' buckets; their upload was not confirmed.

## What shipped (local only), from the admin Models audit

The audit is `docs/design/admin-models-tab-audit-2026-09-29.html` (untracked,
like the earlier audits). The owner approved all five decisions on 29
September, then on 30 September chose a **true erase** and **Reconsider** for
declined applications.

- **Q1 `1c791fd` — twelve bugs.**
  - Payout correction sends only the chosen method's fields (the wallet provider
    is kept; `set_destination` drops other methods' fields for every caller).
  - Historical *Review months from…* confirms before approving.
  - Roster: search resets the page; no *Loading…* beside an error; archived rows
    are always fetched; one invitation row per person.
  - Invitations: a resent link is shown; withdraw confirms; the page is
    read-only without `invitations.send`.
  - A pending house account skips the pay and target steps; the targets step
    ticks.
  - Applying with another model's code is a 409.
  - Pay-term refusals no longer mention reopening; saving terms keeps the
    stored customer discount.
- **Q2 `8e346b8` — ADR 0052**, a model's life.
  - `declined` status (migration `a6b1c4e20006`), and a table of allowed status
    moves.
  - Pause, archive and decline each carry a reason.
  - Pause keeps sign-in, code and earnings. The model portal's banner used to
    say new sales were not counted, which was never true.
  - Archive; reactivate clears `archived_at`.
  - Decline releases the code; Reconsider returns the application to review.
  - Approval needs pay terms for the working month (paid accounts) and asks for
    confirmation first.
  - Erase is admin-only, and only for a model with no order, payroll, payment,
    adjustment, parcel or proof. Never a staff account, never one's own.
  - Pay terms up to twelve months ahead, with a before/after review.
- **Q3 — the audit's UI.**
  - **List:**
    - *Needs you* counts that filter (applications, unconfirmed codes, no
      terms, no payout details).
    - Blockers under each name.
    - Month and sort controls.
    - Select several and export a CSV (formula-safe, UTF-8 BOM).
    - Search by email.
    - A first-run explainer.
    - Phone cards with code, sales and content, twelve at a time.
    - *Joined, hasn't applied* with *Remind her* (new `application.reminder`
      email).
  - **Profile:**
    - *Her details*, read-only, with a sign-in email change: 409 when the
      address is taken, 400 when malformed.
    - *Where to pay her* on Overview and Payments, with **Pay on InstaPay**.
      The number shown is `instapay_phone`, never her contact phone.
    - Code timeline, an *Activity* tab from the audit feed, and a link to
      `/affiliates/:id/payments`.
    - House accounts show only Overview, Performance and Activity.
  - Browser-checked at 1280 and 390 on a throwaway database with the harness's
    seed; the review database was dropped afterwards.

ECC's code reviewer went over each batch; every high and medium finding was
fixed with a test. The one low left open is below.

## Remaining, in order

1. **Owner acceptance on staging** of the Models tab: list, Needs you, a
   model's page (Her details, Where to pay her, Activity), pause/archive,
   decline/reconsider, erase, and pay terms ahead. Not browser-checked on
   staging by this session (the Jev browser did not connect; staging was empty).
2. **`a6b1c4e20006` on a restored copy** was skipped by order (above). If a
   restored copy is ever rehearsed for the other gates, include it.
3. **Admin sidebar at phone width** (pre-existing, not Q3): at 390px
   `layout__sidebar` is 521px wide and every admin page scrolls sideways by
   131px. The admin is designed for 1280/1440; fix or accept it deliberately.
4. **Activity feed on long histories:** `/api/audit` matches the subject as a
   substring with a limit of 200, and the profile keeps exact matches. A
   low-numbered model with a very long history can lose her oldest entries.
   An exact-subject option on the endpoint fixes it.
5. **Map the flows with real data** (the owner's reason for the reset), then
   continue the admin audit tab by tab. Payments is next, where recording a
   payment lives.
6. Everything still open from the 27 and 28 September handoffs that the reset
   did not make moot. That includes the release gates: reconciliation against
   a restored copy, and the `SETTINGS_ENCRYPTION_KEY` cases.

## Decisions not to reopen (added 29–30 September)

- **ADR 0052 as written:**
  - Pause does not stop earnings.
  - Erase is a true delete through a transaction-scoped guard exception, not a
    remove-and-keep-trail.
  - Declined returns only through Reconsider.
  - Approval needs working-month terms for a paid account.
- **The InstaPay number is `instapay_phone`,** the phone she gave for InstaPay,
  and the payment link is `instapay_address_url`. Never her contact phone.
- **Pay on InstaPay** on the model profile. The payments desk keeps the
  export's *Open InstaPay* wording.

## Corrections worth knowing

- The model portal's paused banner was wrong for as long as it existed (it
  said sales stopped counting). It now matches the platform.
- `MyWardrobe.tsx` passed the best-sellers path through a variable, which the
  reachability guard cannot read. The guard failed from batch P onwards. It is
  now written literally, with no behaviour change.
- `docs/repair/batch-1/run-suite.sh` keys passes by `REV`. After changing code
  without committing, run it under a new `REV=` label, or earlier passes are
  trusted for code they did not test.
