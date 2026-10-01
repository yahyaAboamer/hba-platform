# Where the work is — 1 October 2026 (data reset, batches Q1–Q3, Settings audit, Home and emails audit)

## Latest: targets before her start, and who holds a code (1 October, ADR 0056)

From the owner's staging check after ADR 0055.

- **Targets (ADR 0056):** a month before her known start has no targets.
  - The server refuses creating, changing or counting one there. An
    unchanged re-send is accepted.
  - *Whole year* skips those months with the reason `before_her_start`.
  - The grid row stays but is closed: disabled boxes, *Starts April 2026*,
    and a quiet *Before her start*. A record made earlier stays visible so a
    confirmation can still be taken back.
- **Settings → Shopify and sync, *Discount codes belonging to nobody*:** the
  count was only the unowned orders and read as the code's total (ALI10: 5).
  - Each code now says who holds it, from when, and how many orders are
    credited (`held_by`).
  - The headers read *Orders with no owner* and *Held by*.
- **Verified:** backend 90/90 files (`REV=adr0056-2`). Frontend 576 tests,
  build green.
- **Browser, local throwaway `hba_browser_0056` (now dropped), 1280 dark:**
  closed rows on Targets for January; the Settings row *YADEL · 1 · January
  2026 · Youssef Adel, from March 2026 · 10 orders credited*.
- **ECC review:** 0 high. The medium (records before her start hidden) is
  fixed; three of the four lows are fixed.

**Owner's decisions (same day), done:**
- **Payroll page:** `/api/payroll/{month}` leaves out a model whose start
  (`collaboration_from`, the payments desk's rule) comes after the month. An
  unknown start stays listed.
- **Payroll page:** the month picker stops at the working month.
- **Staging data:** Ali's January to March 2026 targets (4 videos, 8 stories
  each, no counts) were deleted in one guarded transaction. Each has a
  `target.deleted` audit row holding what it was.
- **Released:** `1fe852a` and `111212a` fast-forwarded to `origin/main` and
  `origin/production` on the owner's order.
  - All four deploys (staging and production, app and worker) SUCCESS on
    `111212a`, 1 October ~17:58 Cairo. No migration.
  - `/api/health/ready` 200 on both.
  - Read back on staging: ALI10 is *5 with no owner (2026-01), held by Ali
    Abunahla from 2026-04, 99 credited*.
  - Backend 90/90 (`REV=adr0056-3`); frontend 576, build green.
- **Raised with the owner:** the full suite takes about an hour on this
  machine. Pytest itself is about 15 minutes; the rest is one Python start and
  one database wipe per file, and about 0.4 GB of free memory. Options put to
  him:
  - CI on GitHub Actions (recommended);
  - grouping files per process, which reopens a retired setup;
  - freeing memory.

## Before that: ALI10 and pay-terms months (1 October, ADR 0055) — **released**

| | |
|---|---|
| **Commit** | `2ec5988` on `repair/batch-2`, fast-forwarded to `origin/main` and `origin/production` on the owner's order ("deploy and merge to staging and production") |
| **Deploys** | All four (staging and production, app and worker) SUCCESS on `2ec5988`, 1 October ~13:48 Cairo; logs show `c8d3e6f40008 -> d9e4f7a50009` on both databases; `/api/health/ready` 200 on both |
| **Read back** | Staging: Ali start `2026-04`, ALI10 from `2026-04`, Sara's last run `2026-08` open-ended, two ADR 0055 audit rows. Production: head `d9e4f7a50009`, no models or terms, so nothing changed |


**ALI10 diagnosis (read-only on staging and Shopify).**
- The sync is fine: `order_index` has 104 ALI10 orders from January to
  September, and 99 are attributed to Ali from April to September. That equals
  Shopify's *99 used*; September has 11.
- The *5 January orders* the owner saw are under Settings → *Discount codes
  belonging to nobody*.
- Shopify's ALI10 was **created 4 April 2026**. Its "Active from" (Feb 2025)
  was copied from SARAED when it was duplicated. Her start used "Active from"
  (→ 2026-01), but her code's ownership used the creation date (→ 2026-04).
- **The owner (decision):** the ALI10 orders before April were another
  model's, on the code now named *ALI10 OLD*. A code, and the model holding
  it, start when the code was **created** on Shopify. So Ali starts in April,
  and the five January orders correctly stay under *belonging to nobody*.
- Of 44 codes with 5+ orders, only ALI10 was created after its first order.
  SPONSORSHIPPING (49 orders) is not a Shopify discount code. Production has
  no models.

**Shipped locally:**
- **One date for both:** `start_month_for(created_at)` and
  `model_start_month_for(created_at)`; "Active from" (`startsAt`) is no longer
  used for either.
- **Pay terms, server:** only months from her start (once known) to the
  working month. A start after the working month is refused, and so is a
  change before her recorded start. The run reaching the working month is
  stored open-ended, so each new month inherits it.
- **Pay terms, editor:** says when she started and why (`start_source`,
  `code`). The "Ahead" wording is gone.
- **Migration `d9e4f7a50009`** (data only, audited, idempotent; downgrade is a
  no-op):
  - sets a start taken from the code (audit `"from": "shopify_code"`) to the
    code's creation month, which moves Ali from 2026-01 to 2026-04; typed
    starts are untouched;
  - opens Sara's last run, which ended 2026-10.
  - Rehearsed up/down/up on a throwaway database only.
- **Tests and review:** 8 new backend tests, 5 new frontend tests. The ECC
  reviewer found 0 high; its medium and lows were fixed or documented.
- **Verified:** backend through `run-suite.sh` (`REV=adr0055-3`, after the
  owner's creation-date decision; `adr0055-2` was 90/90 on the first version).
  Frontend 576 tests, build green.
- **Browser, local throwaway `hba_browser_0055` (now dropped), 1280 dark:**
  Youssef (start March) shows the start line, Jan–Feb *Before start*,
  Nov–Dec *Not yet*. October set to 12% saved as *October 2026 onwards*.

**Owner to check on staging:** Ali's terms editor (starts April 2026) and Sara's.

**Not done:**
- `mark_verified` may still move a re-opened period of a returning model (from
  before this change).

## Before that: the Home and emails audit (1 October) — **released**

| | |
|---|---|
| **Commit** | `b122fca` on `repair/batch-2`, fast-forwarded to `origin/main` and `origin/production` on the owner's order ("start the edit and merge and deploy to staging and production") |
| **Deploys** | All four (staging and production, both services) SUCCESS on `b122fca`, 1 October ~05:06 Cairo; deploy logs show `b7c2d5e30007 -> c8d3e6f40008` on both databases; `/api/health/ready` 200 on `hba-platform-staging-staging.up.railway.app` and `affiliate.hbawear.store` |
| **Migration** | `c8d3e6f40008` (`invitation.name`, one nullable column), rehearsed up/down/up on a throwaway database only |

From the owner's staging test with Sara. The audit is
`docs/design/portal-home-salary-and-settled-audit-2026-10-01.html`
(untracked). The owner approved the emails, the Home changes, C ("Paid
directly by HBA") and D (first name on the invite). For A and B he said he
records every model's terms for every month, and the guarantee's target
outcome, **before she is approved**. So nothing is carried back or assumed.

- **ADR 0054** (and `docs/RULES.md`): a settled month (before go-live) that
  has terms recorded is calculated and shown like any other month, without
  approval. Its pill says *Settled*, its payment line says *Paid directly by
  HBA*, `waiting_on` is empty, and it stays off the payments desk
  (`balance_for` is unchanged). With no terms, the big number is her sales,
  labelled *Sales*, with the line *"HBA settled this month with you
  directly…"*. There is no "yet", and she gets an average order.
- **Salary + commission split:** `my_month` returns `split` (salary plus the
  rest as commission, so the two add up to the total). Home shows it under the
  big number.
- **Emails:** `mail_branding.wrap` removed every "\n\nHBA Aesthetics" in the
  body, which is how the invitation came out as "Hi, has set up…". It now
  removes only the trailing sign-off. The invitation greets her by the first
  name (else "Hello,") and says what comes next. Staff invitations have their
  own wording. The approval email says "HBA ambassador" and names her code.
  Each button names its action (`Message.action`). The admin email says
  "applied to be an HBA ambassador".
- **Invite form:** optional first name. Resend keeps it. Accepting the invite
  uses it as the display name when none is sent.
- **Verified:** backend 90/90 files through `run-suite.sh` at `b122fca`.
  Frontend 571 tests / 35 files, build green. Local browser on a throwaway
  `hba_browser` (seed, go-live 2026-06, now dropped): October salary split and
  a settled May at 375 px dark, "How this adds up" for May, the invite form at
  1280, and an invite with a name stored on `invitation.name` and its payload.
- **Not verified on staging by me:** sign-in there needs the owner's password.
  The owner reviews Sara on staging.

## Before that: the Settings audit (30 September, evening) — released

| | |
|---|---|
| **Commit** | `9639497` on `repair/batch-2`, fast-forwarded to `origin/main` and `origin/production` on the owner's order (30 September, 20:48 Cairo) |
| **Deploys** | staging `hba-platform-staging` and production `hba-platform` SUCCESS; migration `a6b1c4e20006 -> b7c2d5e30007` ran on both (deploy logs); `/api/health/ready` 200 on both |
| **`GO_LIVE_MONTH`** | **`2026-10` on both** (was staging `2026-08`, production `2026-09`), set on Railway and read back; both redeployed SUCCESS |
| **Checks before the change** | One read-only query each (`default_transaction_read_only=on`): production and staging had no approved payroll month and no payment; production no model; **no admin invitation ever sent or resent by a non-admin**; the only staff account on each is the owner's admin. The audit log only reaches back to the 29 September reset. |

Months before October 2026 are now settled outside the platform on both
environments. `b7c2d5e30007` was rehearsed up/down/up on a throwaway database,
not on a restored copy (owner's order to release).

The audit is `docs/design/admin-settings-tab-audit-2026-09-30.html` (untracked,
with its screenshots). The owner approved the design, then (same evening):
nothing removed outright; Historical setup hides itself once history is
final; brand codes are added only under Settings; a model's start month comes
from her code's start on Shopify; her code never changes, so the
register/change-code form and routes are removed (ADR 0053).

- **Security (was live on production):** an affiliate manager could invite an
  admin, or resend a pending admin invitation, and so make themselves an
  admin. Now `can_grant` (only access you hold) guards invite, resend and
  withdraw; one live invitation per address; nobody changes or suspends their
  own account.
- **Settings screen rebuilt** to the approved mock: rail shows only what the
  person can use (a content manager used to land on a blank page); Team with
  last sign-in, *What can each access do?*, a confirmation for every access
  change, a row menu for suspend/reactivate, copy-link; pending invitations one
  per address with Remove for lapsed ones; Shopify with *Needs attention* and
  *Tools*, a real date field, trivia removed, identical stopped jobs grouped;
  Historical setup problems first, applicants left out, counts split at
  go-live, auto-hidden when complete (`totals.unknown_start` keeps it while a
  start is unknown); Brand codes with state pills, orders this month and a
  one-row add; Pay policy with a live preview and a month picker that offers
  only months the server takes; Activity log with name search (the old filter
  found nothing by name), model/person/kind filters, sign-ins hidden, day
  headings, *What changed* and *Show older*; My preferences with the theme
  saved to the account (migration **`b7c2d5e30007`**) and a line under each
  switch.
- **ADR 0053** (and `docs/RULES.md`): start month from Shopify `startsAt`
  (else `createdAt`), floored at January 2026, written when the code is
  confirmed and never over a recorded one; `POST /api/affiliates/{id}/codes`
  and `/replace-code` removed; reactivating an archived model restarts her own
  code (with backfill), refused if someone else now holds it.
- **Verified:** backend **90/90 files** through `run-suite.sh` (label
  `settings-audit-2`; the tally also shows the first, since-fixed
  reachability failure); frontend **568 tests / 35 files**, build green;
  browser pass on a throwaway database at 1280 and 390, light and dark, as
  admin, content manager and affiliate manager. ECC Python and React
  reviewers ran; every finding above low was fixed with a test.
- **Not done:** policy versions editable before their month (D4) — needs its own ADR because
  `policy_version` is append-only.
- **New migration for the release gates:** `b7c2d5e30007` (one nullable
  column) joins the list to rehearse.
- **Throwaway databases** `hba_browser_settings` and
  `hba_browser_portal_tabs` can be dropped.

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
4. ~~**Activity feed on long histories**~~ fixed by the Settings audit: `/api/audit` now matches an exact subject (`q=affiliate:12`). Was: `/api/audit` matches the subject as a
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
