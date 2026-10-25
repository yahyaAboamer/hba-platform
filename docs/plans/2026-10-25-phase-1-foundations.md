# Phase 1 — Foundations for HBA OS: plan

**Written:** 25 October 2026, from ADRs 0065, 0066 and 0067.
**Status:** Planned. Nothing here is built. Each batch is its own branch and its
own pull request; **nothing is merged or deployed without the owner's separate
word for each** (`CLAUDE.md`).

## In plain words

Phase 1 changes almost nothing anybody sees. It puts in what the rest of HBA OS
stands on:

1. **A test run on every change (CI).** Today the tests run only when somebody
   remembers to run them. After this, GitHub runs all of them on every pull
   request and shows a red cross before anything broken can be merged.
2. **Alerts when something breaks.** Today an error lives in Railway's logs
   until somebody notices its effects. After this, the owner gets an email
   within minutes, and another if the site stops answering.
3. **Several roles per person.** Today each person holds exactly one role, so a
   mix of jobs needs an invented role. After this, a person can hold several,
   and can do what all of them allow together. Production's move (ADR 0069)
   needs this for its team levels and supplier accounts.
4. **Two-step sign-in.** Anyone who approves or pays money, and the owner,
   confirm each sign-in with a code from an authenticator app on their phone.
   Everyone can see where they are signed in and sign out everywhere.
5. **Department folders.** The code is rearranged so each department's code
   sits in its own folder, with an automatic check that stops one department
   reaching into another's tables. Nothing changes on screen.

**Rough size: two to three weeks of work**, more than the first estimate,
because the role change has to move existing access without anybody gaining
or losing any, and two-step sign-in needs a safe way back for a lost phone.

## Before anything: two things only the owner can do

**A. The GitHub repository is public.** `yahyaAboamer/hba-platform` was
checked on 25 October 2026: anybody on the internet can read every file in
it, including the business rules, the decision records, the handoffs and
`CLAUDE.md`, which names the staging accounts. Recommended: make it private
(GitHub → the repository → Settings → General → Danger zone → Change
visibility). Two consequences to know:

- Railway deploys from this repository through its GitHub app. After the
  change, confirm in Railway (the service → Settings → Source) that it still
  sees the repository. Look only; do not trigger a deploy.
- GitHub's free plan includes a monthly allowance of CI minutes for private
  repositories; public ones are not counted. Batch 1 measures how long a run
  takes, so the allowance can be checked against real numbers.

**B. Nothing describing Production's open data is pushed while the
repository is public.** Commit `8d3f915` (ADR 0069) names the Production
site's address and says that anybody can read its data without signing in.
It is on the branch `claude/hba-erp-architecture-55746a` and has not been
pushed. Before it is: either the repository is private, or ChatGPT has made
the site require sign-in (the prompt for that was given to the owner on
25 October), or both.

## Order, and why

| Batch | What | Can start | Rough size |
|---|---|---|---|
| 1 | CI, error alerts, uptime check | Now: it changes no behaviour of the app | 2–3 days, plus the owner's account setup |
| 2 | Several roles per person | After the release gates in the current handoff | 3–5 days |
| 3 | Two-step sign-in, devices, suspending | After batch 2 | 4–6 days |
| 4 | Department folders | At the first moment no other branch is open | 2–3 days |

- **CI comes first** because it protects every batch after it, and the
  release-gate work too.
- **Roles come before two-step sign-in** because who must use a second step is
  decided by what their roles allow.
- **Folders go last but are not tied to the others.** Moving every file
  conflicts with every branch in flight (the Inbox switch-over, the repair), so
  it waits for a quiet moment; if one comes earlier, it moves up. New code
  never waits for it: Production is built in `app/modules/production` from its
  first line (ADR 0065).
- **Production's move** (ADR 0069) can start once batch 2 is in, and once the
  source export from ChatGPT has arrived and been read.

---

## Batch 1 — The safety net

### 1.1 CI on GitHub Actions

A workflow, `.github/workflows/ci.yml`, with two jobs.

**Backend job**
- Ubuntu, Python 3.12, and a Postgres 17 service container: the same version
  as the local test database (`docker-compose.yml`, `postgres:17-alpine`).
- Before the tests, the job marks its throwaway database as disposable, the
  way `docs/repair/batch-1/run-suite.sh` demands (the `hba_test_guard`
  designation). The guard stays; CI satisfies it rather than going around it.
- `alembic upgrade head`, then **a check that there is exactly one migration
  head**, so two branches that each add a migration cannot both merge
  silently.
- The suite runs one pytest process per file, as `run-suite.sh` does. The
  script names the Windows path `.venv/Scripts/python.exe`; it learns a
  `PYTHON` variable (defaulting to that path) so the same script runs in CI
  with `PYTHON=python`. One script, two places, no second copy of the loop.

**Frontend job**
- Node 22, as the Docker build installs it (ADR 0016 pins the toolchain to the
  builder's Node), `npm ci`, `npm test`, `npm run build`. `npm run build` is
  the real type check (`CLAUDE.md`).

**When it runs:** on every pull request into `main` or `production`, and on
every push to `main`.

**What it never does:** touch staging or production, or read any secret. It
needs none.

**Done when**
- A pull request shows both checks, and a deliberately broken test on a
  scratch branch turns the backend check red (then the branch is deleted).
- The first full run's duration is written into this plan.
- The owner has decided on **branch protection**: `main` and `production`
  refuse a merge until CI is green. Recommended. It is a GitHub setting the
  owner changes.

### 1.2 Error alerts

**The owner chooses one of two, before this is built:**

| | Sentry (recommended) | Email only |
|---|---|---|
| What arrives | An email on each new kind of error, with the line of code, how often it happens and since when; the same for errors in the browser | An email per error, throttled, with the error's text |
| Grouping and history | Yes: the same error a hundred times is one issue | No |
| Where error reports go | Sentry's servers (EU region chosen). Nothing personal is sent: no request bodies, cookies, headers, addresses or user details; this is set in code and tested | Nowhere new: the platform's own mail |
| Cost | Free plan to start | Nothing |

Whichever is chosen:
- **What counts as an error:** an unhandled exception in a request; a
  background job that fails for good (`PermanentFailure`, or out of retries);
  the worker loop itself failing (`WORKER_ITERATION_FAILED` in
  `app/core/signals.py`). Anomalies that were prevented (`ANOMALY` lines) stay
  in the logs; they are not alerts.
- Staging and production are told apart in every alert.
- Each alert names the deployed commit, so "since which deploy" has an answer.

### 1.3 Uptime check

An outside service calls production's `/api/health/ready` every five minutes
and emails the owner when it stops answering. Free services do this (for
example UptimeRobot or Better Stack). **The owner creates the account**; this
batch writes down what to set and checks that the first alert arrives.

**Done when** each kind of alert has been seen to arrive once: a test error
on staging, a test job failure on staging, and the uptime check pointed
briefly at an address that does not answer.

---

## Batch 2 — Several roles per person (ADR 0067, decisions 1–3, 7–9)

**What changes underneath**
- `active_role(db, user)` → `roles_of(db, user)`, the set of live
  assignments, and `permissions_of(db, user)`, the union of what they grant.
  `require_permission` checks the union.
- "Is this person staff?" becomes "do they hold any staff role?". Models are
  still recognised by owning a profile (`current_affiliate`), never by a role.
- `can_grant` takes the actor's roles: a role may be given only if everything
  it grants is already in the actor's union.
- A database rule: one person cannot hold the same role twice at once (a
  unique index on live assignments).
- **Giving and taking a role are separate actions.** Today `change_role`
  revokes the live assignment and creates another
  (`app/services/staff.py`); it becomes *add a role* and *remove a role*, each
  audited, each keeping the rules that already exist (nobody changes their own
  access; the last admin cannot be removed; one operations manager at a time).

**Moving today's access without changing it**
- The operations manager's Inbox access stops being part of that role and
  becomes a second assignment. A migration gives every live operations
  manager a `customer_service` assignment, then `operations_manager` stops
  granting `inbox.use`. Before and after, the same people can do exactly the
  same things; a test proves it for every existing role, and the migration
  goes down cleanly.
- **No role is renamed in this batch.** The department levels (viewer, staff,
  manager) arrive with Team and access in Phase 2. Renaming roles now would
  touch invitations, emails and check constraints for no change anybody sees.

**Every place that asks for a role by name**, as found on 25 October 2026:

- **The role check**, `active_role(...)`, called in `app/api/deps.py` (four
  times), `app/api/staff.py` (four), `app/api/affiliates.py`,
  `app/api/applications.py`, `app/api/auth.py`, `app/api/payments.py` and
  `app/services/staff.py` (three).
- **Comparisons with a role's name**, in `app/api/affiliates.py`,
  `app/services/affiliates.py`, `app/services/notifications.py` (an
  invitation's role picks its email, which stays right: an invitation still
  grants one role), `app/services/staff.py`, and `app/api/deps.py`'s
  `require_staff`.
- **The frontend**: `App.tsx` chooses whole screen trees by
  `session.actor.role` (three branches); `Layout.tsx` and `SideShell.tsx`
  print the role under the brand; `Settings.tsx` confirms a change to admin.
  The session gains `roles` (a list). `App.tsx` chooses by permissions held,
  and a model is recognised by owning a profile, which the session says
  outright. The Phase 2 frame replaces this routing altogether; batch 2 only
  makes it ask the right question.

**Settings → Team and access, the minimum:** each person's roles listed;
*Add access* offers only the roles the actor may grant; each role can be
removed. The full page by department is Phase 2 (ADR 0068).

**The audit trail gains a department column** (ADR 0067, decision 7).
`record_audit` fills it from the action's prefix (`inbox.…` → Inbox), so the
callers do not change. Older entries stay empty. Reading by department waits
for Phase 2.

**Done when**
- Tests: the union of two roles; `can_grant` with several roles; a duplicate
  role refused; the last admin protected; the migration up and down; and for
  every existing role, the same routes allowed and refused before and after.
- No user-visible change apart from Settings listing roles and offering
  *Add access*.
- The whole suite and the frontend build pass in CI.

---

## Batch 3 — Two-step sign-in, devices, suspending (ADR 0067, decisions 4–6)

**Two-step sign-in**
- Codes from an authenticator app (the standard six-digit codes, RFC 6238),
  through `pyotp`. The secret is stored encrypted with the existing Fernet key
  (`app/core/secrets.py`, `SETTINGS_ENCRYPTION_KEY`); without a usable key,
  turning it on is refused, as saving a secret is today.
- Signing in becomes two steps for people who use it: the password returns a
  short-lived, single-use, hashed *pending* token and no session; the code
  exchanges it for a session. A code may be used once (the last accepted time
  step is kept), and guessing is throttled (`app/core/throttle.py`).
- Turning it on: Settings → Me shows a QR code, made on the server as an SVG
  (`segno`, pure Python, no network), and the secret as text for typing in.
  It is confirmed by entering one code.
- **Ten recovery codes**, shown once and stored only as hashes, each usable
  once.
- **Who must use it:** the owner (admin) and anyone whose roles grant
  `payroll.approve` or `payments.record`. Today that is admin and
  affiliate_manager. Such a person who has not set it up can, after their
  password, only set it up. Everyone else may turn it on.
- **A lost phone:** a recovery code, or the owner resets it. The reset is
  audited and asks for the owner's own code first.

**Devices**
- Settings → Me → *Signed in on*: each live session's browser, the address it
  came from and when it was last seen (all already in `auth_session`; no
  outside lookup of where an address is). *Sign out everywhere else* uses the
  existing `revoke_all_sessions`.
- The owner sees the same for anybody, on that person's page.

**Suspending** (ADR 0067, decision 6) ends every session and removes every
role at once, audited as one action. Bringing someone back means giving their
access again, deliberately.

**Done when**
- Tests: a code inside and outside the accepted window; a code refused the
  second time; a recovery code used once only; a pending token that expires
  and cannot be reused; the throttle; a person who must use it reaching nothing
  until it is set up; the owner's reset audited; suspension leaving no session
  and no role.
- Tried on a local copy with a real phone and a real authenticator app, from
  setting it up to losing the phone.
- **The rollout is the owner's call:** the owner and the affiliate manager set
  it up on the day it is switched on, and everyone is told the day before.

---

## Batch 4 — Department folders (ADR 0065)

**The layout after the move**

| Folder | What moves into it |
|---|---|
| `app/core/` | Stays as it is: money, periods, permissions, passwords, signals, throttle, secrets |
| `app/shared/` | Identity and sign-in (`auth`, `staff`, invitations, password resets), audit, the job queue and worker, mail and notifications, the Shopify connection and mirror (`app/services/shopify/`, `order_index`, the catalogue) |
| `app/modules/inbox/` | `app/api/inbox.py`, `app/models/inbox.py`, `app/services/inbox/` |
| `app/modules/operations/` | `app/api/order_ops.py`, `app/models/order_ops.py`, `app/services/order_ops/` |
| `app/modules/affiliates/` | Everything about models: profiles, codes, applications, compensation, targets, payroll, payments, payouts, products and gifts, the portal, attributed orders, commission |
| `app/modules/production/` | Empty, ready for ADR 0069 |

Each module keeps `api`, `models` and `services` inside it, and offers a
`public.py`: the only things other modules may call.

**How it is done**
- `git mv` only, plus the import lines that must change, in one pull request
  with **no other change**. The existing tests, unchanged except for their
  import lines, prove nothing moved but files.
- `app/models/__init__.py` keeps importing every model, so Alembic still sees
  all tables. Migrations already written are not edited.
- **import-linter** joins CI with one contract: a module imports `app.core`,
  `app.shared` and other modules' `public` only. Today's cross-department
  imports that break it are listed in the contract as known exceptions, each
  with a line saying why, and the list only shrinks.
- The frontend is not rearranged here. Its department folders arrive with the
  Phase 2 frame, which declares each department once (ADR 0068).

**Done when** CI is green including import-linter, the app starts locally and
answers `/api/health/ready`, and the pull request's diff contains nothing but
moves and import lines.

---

## What Phase 1 does not include

- The new frame, Today, search, the order page and Team and access by
  department: Phase 2 (ADR 0068).
- Moving Production in: its own track, after batch 2 and the export
  (ADR 0069).
- A shared customer record, staff profiles, a reporting schema: when a
  department first needs them (ADR 0066).
- Deciding to buy accounting software rather than build it: not recorded,
  and not needed until Finance.

## Decisions the owner is asked for

1. Make the GitHub repository private: recommended.
2. Error alerts: Sentry (EU, nothing personal sent) or email only.
   Recommended: Sentry.
3. Create the uptime-check account.
4. Branch protection on `main` and `production` once CI exists: recommended.
5. Two-step sign-in required for money and the owner, offered to everyone
   else (as ADR 0067), or required for all staff.
6. Start batch 1 now, ahead of the release gates: recommended, since it
   changes nothing the app does.

## Decisions already made, not to reopen

- One application, one database, departments as folders (ADRs 0065, 0066).
- Roles stay defined in code; several per person; levels by department
  (ADRs 0007, 0067).
- No merge and no deploy without the owner's word for each (`CLAUDE.md`).
