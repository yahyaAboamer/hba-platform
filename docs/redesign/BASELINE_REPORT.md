# Phase 00 — Baseline report

Produced 9 September 2026 by the implementation agent, in the connected local
checkout. **No application behaviour was changed.** The only file added outside
this package is this report. Working tree is otherwise clean.

Everything below was run, not recalled. Where something was not run, it says so.

---

## 1 · Where the repository actually is

| Fact | Value |
|---|---|
| Checkout | `D:\Desktop\HBA\HBA Engineering\hba-platform` |
| Branch | `main` |
| HEAD | `63c64c3c82c2b15a685494c635c8a164d8070de5` |
| Package's reviewed baseline | `025d8a8b059978e6c8113d3c998465be80730f91` |
| Local `production` | `025d8a8` |
| `origin/main` | `025d8a8` |
| `origin/production` | `025d8a8` |
| Working tree | Clean apart from `?? docs/redesign/` (this package) and this report |
| Migrations on disk | 32 files, single head `a71f4c9be830` |
| Python | `.venv/Scripts/python.exe` — 3.14.5 (requirement `>=3.12`) |
| Node / npm | v24.16.0 / 11.13.0 (requirement `>=20.19.0`) |

### The remote question is answered — and the answer is the other way round

`START_HERE.md` and `STATUS.md` both record "Remote HEAD verified: **No**" and
warn the remote might hold newer work. **It does not.** From this environment:

```
$ git ls-remote --heads origin
4d501c3…  refs/heads/feat/portal-dark-mode
025d8a8…  refs/heads/main
025d8a8…  refs/heads/production
```

`gh auth status` shows two authenticated accounts (`yahyaAboamer`, active, with
`repo` scope; and `hbaaesthetics-lgtm`). There is **no access limit**. The
package author's 404 was an authentication problem on their side only.

So the true picture is the inverse of the package's worry:

- **The remote is three commits behind the local checkout.** `main` is
  `[origin/main: ahead 3]`.
- Those three commits are **unpushed local work**, not merged pull requests.
  Their subjects say `(#123)`, `(#124)`, `(#125)`, but GitHub's highest PR is
  **#122**; `gh pr view 123/124/125` each return *"Could not resolve to a
  PullRequest"*. The numbers were written in anticipation.
- `main` and `production` are **not level**, contrary to the standing rule in
  `CLAUDE.md` (ADR 0034). `production` sits at `025d8a8`; `main` is three ahead.
- Many `origin/*` remote-tracking refs in this checkout (batch1…batch4, phase2…
  phase5, m1/model-side, etc.) are **stale** — those branches no longer exist on
  the remote. I did not prune them; `git fetch --prune` would, and changes
  nothing else.

**This is the single most important thing for the owner to know before the next
batch.** Three commits of real, tested work exist only on this machine. See §7.

### What those three commits contain

They are not incidental — they implement the item the 4 September handoff calls
*"the big one"*, and they overlap this package's roadmap directly.

| Commit | Subject | Substance |
|---|---|---|
| `1fe55de` | *a month before go-live is approved like any other, and never paid* `(#123)` | **ADR 0036.** `ALREADY_SETTLED_OUTSIDE` becomes a *mode*, not an approval blocker: the month approves, is flagged `settled_outside`, and `_refuse_settled_outside` in `app/services/payments.py` structurally prevents a transfer against it. Adds historical **outcome-only targets** (migration `a71f4c9be830`, `a_target_from_before_the_platform`) — met/missed without fabricated video/story counts. 14 files, +948/−155. |
| `e6db1ee` | *her March reads like her August* `(#124)` | `app/services/portal.py` + `MyMonth`/`MyPayments`: the word "historical" leaves the model's screens; a pre-go-live month renders with sales **and** commission. One line survives, on Payments only, shown only to a model who actually has such a month. 7 files, +336/−40. |
| `63c64c3` | *the pay-history editor, and one screen where pay is set* `(#125)` | The **selected-month terms editor**. `POST /api/affiliates/{id}/compensation` is replaced by `GET`/`PUT /api/affiliates/{id}/pay-history`. New `frontend/src/lib/payHistory.ts` (+ 15 unit tests), `Compensation.tsx` largely rewritten (1148 lines changed). New `compensation.manage` permission usage separated from `affiliates.manage`. 13 files, +2579/−612. |

I ran this editor. It is the month strip from the approved mockup: click a
month, shift-click for a range, hatching for months before she joined or already
approved, a *What will be recorded* preview that collapses consecutive identical
months into periods, and one Save. **That is `UI10` / rules `H04`+`H05`, already
built** — in the maintainer's existing neutral styling, so it needs the visual
pass, not the behaviour.

---

## 2 · Package integrity

```
$ PYTHONUTF8=1 .venv/Scripts/python.exe docs/redesign/evidence/verify-package.py
{ "source_assets_verified": 19, "screen_action_rows": 52,
  "acceptance_checks": 64, "numbered_phase_prompts": 10, "issues": [] }
```

**Zero issues.** One note: the script fails on Windows without `PYTHONUTF8=1`
(`UnicodeDecodeError` from cp1252 reading `PRODUCT_RULES.md`). I did not modify
the script. Run it with that variable set.

---

## 3 · Actual test and runtime results

All of these were run today, in this checkout, at `63c64c3`. **No count below is
copied from a document.**

| Check | Command | Result |
|---|---|---|
| Backend suite | `DATABASE_URL=…/hba_platform_test .venv/Scripts/python.exe -m pytest -q --color=no` | **1589 passed**, 281.09s (4m41s), **exit 0** |
| Frontend unit | `cd frontend && npm test` | **104 passed** (3 files), 3.34s, exit 0 |
| Frontend build | `cd frontend && npm run build` | **exit 0**, 7.04s |
| Dependencies | `cd frontend && npm ci` | exit 0; reports 2 moderate advisories |
| App boots | `uvicorn app.main:app --port 8010` | `/api/health/ready` → `{"status":"ready"}` |

Three corrections to inherited numbers:

- `REPOSITORY_AUDIT.md` cites *"1,558 backend tests and 87 frontend"*. Those are
  from the 4 September handoff and are **stale**. Actual: **1589 / 104**.
- `CLAUDE.md` at HEAD already says 1589 and 104. It is correct.
- The build writes into `app/web/`, which is **gitignored and untracked**
  (`.gitignore:6`). `git status` stayed clean after building, but that proves
  nothing about the bundle — the artefact is simply not in version control. It
  is produced at image build time; the `Dockerfile` is the thing to read for how
  a deploy gets one.

### Database setup, and how identity was verified

The repo's documented dev database is `postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform`
(`docker-compose.yml`, port 5433). `docker compose up -d postgres` started
`hba-platform-postgres-1` from the pre-existing `hba-platform_hba_pgdata` volume.

`tests/conftest.py::_rebuild_schema` runs **`DROP SCHEMA public CASCADE`**, so I
did **not** point pytest at the dev database. I created a separate disposable
one and proved what it was before running anything:

```
CREATE DATABASE hba_platform_test OWNER hba;
db     = hba_platform_test
user   = hba
server = 172.22.0.2:5432
tables = 0
```

Only then did pytest run, as a **single process**, with no concurrent `alembic`
command against it. Nothing else touched that database.

Separately, the pre-existing dev database `hba_platform` was at migration head
`a71f4c9be830` and held **zero rows in every table** — schema only. I seeded it
with the repository's own synthetic fixture, `scripts/seed_demo.py` (which
refuses to run unless `APP_ENV=development`), to get a running app to look at.
**No real, customer or production data was touched at any point.** No Shopify
call was made — the local app reports `shopify: {configured: false}`.

---

## 4 · What the running app looks like today

I ran both halves at `63c64c3` against the synthetic seed, and both design
references from a local static server (`python -m http.server 8765` in
`docs/redesign/designs/`), as `START_HERE.md` describes. The cloud-browser
limitation recorded in the package did not apply here.

**Design references — both render.** The portal reference confirms the target:
dark ground, green accent, five tabs, phone frame. The admin reference is a
Claude Design export driven by a view switch; its complete view set is

`home · models · products · targets · payments · settings` (top level) and
`product · model · orders · order · shipment · promo · invite · payment ·
record · receipt · correction · terms` (secondary).

**Maintainer app today** — Overview at 1920px: cool neutrals, dense tables, red
reserved for money state, left nav `Overview · Affiliates · Orders · Payroll ·
Payments · Targets · Settings`. Target is `Home · Models · Products · Targets ·
Payments · Settings` — so **Orders and Payroll leave the top level and Products
is new.**

**Model portal today** — tab bar reads `Month · Orders · Payments · Year · Grow`
in HBA red on dark. Target is `Home · Orders · Wardrobe · Targets · Ranking`
with Payments moved behind *You*. So **three of five tabs change and one is new.**

**One screenshot states the biggest financial change better than any prose.**
Nour's Month screen shows:

> Counted sales **E£24,000.00** · **On its way E£4,800.00** — *1 order not delivered yet*

That E£4,800 is a pending order deliberately excluded from her earnings. Under
`F02` it counts. Every headline figure on both halves moves.

**Glossary** (`/glossary`) is still the eight flat equal-weight paragraphs the
handoff describes as task #18 — and two of its entries are now **wrong under the
new rules**: *Carried forward* describes the mechanism `F02` removes, and
*Historical* describes months that `H01`/`H02` and ADR 0036 have already stopped
treating differently. This is stale copy on a live screen, not merely an
unfinished redesign.

### Accent tokens map cleanly — but the isolation rule does not

Both design exports use the *same* green:

| Design token | Light | Dark | Existing token |
|---|---|---|---|
| `--acc` | `#14653A` | `#23A95C` | `--accent` |
| `--acctext` | `#14653A` | `#7BE0A6` | `--accent-text` |
| `--accsoft` | `rgba(20,101,58,.09)` | `rgba(35,169,92,.14)` | `--accent-soft` |
| — | — | — | `--accent-on` (`#ffffff`) |

Three of the four existing declarations map one-to-one. The problem is *scope*,
not colour: `portal-accent.css` defines them under `.affiliate` only, and
**`ADR 0038` — "the portal wears the brand; the maintainer's tool does not"** is
the accepted decision that put them there, amending ADR 0027. The approved
design puts the same green on both halves. `accent-isolation.test.ts` (80 of the
104 frontend tests) walks `frontend/src` and fails on any accent colour outside
that one file — so it will need its expectations updated, and the scoping
decision needs recording as an amendment rather than a quiet edit. **Keep the
isolation mechanism; change what it isolates.** This is engineering work, not an
owner question, but it does supersede an accepted ADR and should be visible.

---

## 5 · All 52 UI rows mapped to current code

`Exists` = the behaviour is implemented and reachable (visual redesign still
owed). `Partial` = some of it exists. `Missing` = no production code.

| ID | Row | State | What is actually there / owed |
|---|---|---|---|
| UI01 | Sign in / out / expiry | Exists | `SignIn.tsx`, `/api/auth/*`, session + CSRF. Reskin only. |
| UI02 | First-run bootstrap | Exists | `FirstRun.tsx`, `POST /api/auth/bootstrap`. |
| UI03 | Invitation accept / reset | Exists | `AcceptInvitation.tsx`, `ResetPassword.tsx`, password-quality endpoint. |
| UI04 | Apply + waiting state | Partial | `Apply.tsx` + `/api/applications`. **Optional height/weight fields do not exist.** |
| UI05 | Invite, applications, approve | Exists | `InviteModel.tsx`, `services/applications.py`, `services/invitations.py`. |
| UI06 | Directory | Exists | `Affiliates.tsx`, `GET /api/affiliates`. Redesign owed. |
| UI07 | Shared profile + month context | Exists | `AffiliateDetail.tsx` already carries local month context. |
| UI08 | Contact / shipping / measurements | **Missing** | `affiliate_profile` has only `id, user_account_id, name, phone, status, account_kind, created_at, archived_at`. Additive migration required. Blocked on **D07**. |
| UI09 | Status, code replace / verify | Exists | `PATCH /api/affiliates/{id}`, `/codes`, `/recheck-code`, `/replace-code`. |
| UI10 | Selected-month terms editor | **Exists (new)** | `GET`/`PUT /api/affiliates/{id}/pay-history`, `payHistory.ts`, `Compensation.tsx`. Built in `63c64c3`. Visual pass owed. |
| UI11 | Historical readiness / finalisation | Partial | `settled_outside` mode and outcome-only targets exist (`1fe55de`). **Per-month readiness diagnostics and a real finalisation operation do not.** Cf. `V09`. |
| UI12 | Product catalogue | **Missing** | No product/variant/media model, API or ingestion anywhere in `app/`. |
| UI13 | Product roster by gifting status | **Missing** | Requires UI12 + recipient matching. |
| UI14 | Open model / shipment from product | **Missing** | No shipment record exists. |
| UI15 | Feature request editor | **Missing** | No promotion resource. |
| UI16 | Profile Wardrobe (admin view) | **Missing** | — |
| UI17 | Model Wardrobe | **Missing** | — |
| UI18 | Eligible feature-request cards | **Missing** | Server-side intersection, per `W10`. |
| UI19 | Top sellers / products sold on code | **Missing** | Needs order **line items**; §10.2's index deliberately stores none. |
| UI20 | Unmatched recipient resolution | **Missing** | — |
| UI21 | Monthly requirements editor | Exists | `Targets.tsx`, `GET`/`PUT /api/targets/{month}`. |
| UI22 | Weekly achieved counts | Exists | Required vs achieved already distinct in `models/targets.py`. |
| UI23 | Verification + outcome-only history | **Exists (new)** | `POST /api/targets/{month}/verify` / `/unverify`; outcome-only historical targets added in `1fe55de`. |
| UI24 | Model target self view | Partial | Target bars render inside `MyMonth`. **There is no Targets tab.** |
| UI25 | Payments month list and totals | Exists | `Payments.tsx`, `Payroll.tsx`, `GET /api/payments/{month}`. |
| UI26 | Approve one model / month | Exists, **basis changes** | `PayrollApprove.tsx`, `POST /api/payroll/{month}/approve`. Currently delivered-only — see `F02` below. |
| UI27 | Full destination + Open InstaPay | Exists | `POST /api/affiliates/{id}/payout-destination/reveal`, `instapay_address_url`, `assets/instapay-link.png`. |
| UI28 | Record external transfer | Exists | `PaymentRecord.tsx`, `POST /api/payments`, `services/proof.py`. |
| UI29 | History / detail / reconciliation | Exists | `AffiliatePayments.tsx`, `PaymentReconcile.tsx`, `payments_state.py`. |
| UI30 | Late failure: absorb or carry | **Missing** | No correction ledger. The largest new financial surface. |
| UI31 | Carried deductions, remaining balance | Partial | `POST /api/adjustments` and ADR 0035's settle loop exist; **shared per-destination allocation capacity does not** (cf. `V07`). |
| UI32 | Profile Payments + terms link | Exists | — |
| UI33 | Model Home headline | Exists | `MyMonth.tsx`, `/api/me/months`, `/api/me/earnings/{month}`. |
| UI34 | Earnings explanation + corrections | Partial | *"How this adds up"* renders today. The earlier-month deduction line has nothing to read. |
| UI35 | Year graph | Exists | `MyYear.tsx`, `/api/me/year`. |
| UI36 | Model Orders + filters | Exists | `MyOrders.tsx`. |
| UI37 | Admin attributed orders | Exists | `Orders.tsx`, `/api/orders/{month}`, `/api/orders/lookup/{n}`. |
| UI38 | Ranking | **Missing** | No ranking service anywhere. Blocked on **D03**. |
| UI39 | Admin Home breakdown / top three | Partial | `Overview.tsx` exists; active-model count and top-three do not. |
| UI40 | Content progress + profile Performance | Partial | Data exists in targets; the neutral presentation does not. **D08** governs any label. |
| UI41 | You: details + measurements | Partial | `MyDetails.tsx` today offers only theme and account info. Measurements need UI08's schema. |
| UI42 | You: payout method | Exists | `MyPayout.tsx`, current-password reauthentication retained. |
| UI43 | You: payment history + receipt | Exists | `MyPayments.tsx`, `/api/me/payments/{id}/proof`. Receipt→month routing is `V02`. |
| UI44 | You: email prefs + theme | Exists | `GET`/`PUT /api/me/notifications`, `lib/theme.ts`. Kinds are `month_closed`, `payment_sent`. |
| UI45 | FAQs / help / policy | Exists, **copy stale** | `Glossary.tsx` + `/api/policy/versions`. Two entries now describe removed rules (see §4). |
| UI46 | Settings: team roster | Exists | `/api/staff/*`, `/api/auth/invitations/*`. |
| UI47 | Settings: Shopify health | Exists | `DataPanel.tsx`, `/api/operations/*`. |
| UI48 | House codes | Exists | `AddHouseCode.tsx`, `services/codes.py`. |
| UI49 | Policy versions / audit | Exists | `/api/policy/*`, `/api/audit`. |
| UI50 | Home notices: hide / mute / resolve | Partial | `GET /api/operations/attention` exists; **no dismissal persistence at all**. |
| UI51 | Cross-cutting states | Partial | Per-screen; assess inside each batch. |
| UI52 | Retired reopen path | **Exists — must be removed** | `PayrollReopen.tsx`, route `/payroll/:month/reopen`, `POST /api/payroll/{month}/reopen`, `GET /api/payroll/{month}/reopened`, and `Permission.PAYROLL_REOPEN`. All four are live today. |

**Totals: 29 Exists · 11 Partial · 12 Missing.** The twelve missing rows are
almost entirely one coherent block — products, recipient matching and wardrobe
(UI12–UI20), plus the correction ledger (UI30) and ranking (UI38).

---

## 6 · Constraints found in the code, not assumed

### The commission basis is the biggest single change

`app/services/commission/calculate.py:329` computes
`commission_numerator(earned_base, terms.commission_rate_bp)` — **only
`EARNED`**. `pending_base` is accumulated and reported but never paid. And
`carried_forward()` (line 179) with `carried_into()` in `services/payroll.py` is
the late-delivery mechanism `F02` says to remove: an order that delivers after
its month closed is paid into a later month at its own original rate.

Changing this touches `calculate.py`, `state.py`, `not_settled_by_another_month`,
`payroll.py`'s carry logic, the portal serialisers and the glossary copy. It is
a Phase 05A change and it moves real money. `MIGRATION_AND_RELEASE.md`'s
requirement that legacy `settled_in` links stay readable as evidence is the part
most easily lost.

### Roles today — the factual half of D10

`app/core/permissions.py` defines exactly four roles. There is no "Marketing"
and no "Finance".

| Role | Holds |
|---|---|
| `admin` | Everything, and **the only role with `payments.record` or `payroll.reopen`** |
| `affiliate_manager` | affiliates view/manage, compensation.manage, all three targets perms, payroll.approve, invitations.send, audit.view |
| `content_manager` | affiliates view/manage, compensation.manage, all three targets perms, audit.view |
| `affiliate` | Empty by design — models reach the portal by owning the record |

The prototype's *Marketing* maps to `content_manager` and needs no change. The
prototype's *Finance* has **no existing equivalent**: recording a payment is
admin-only. That is the real question in D10, and it is the owner's.

The file also records, deliberately, that `content_manager` both verifies
targets and sets compensation — no second pair of eyes between judging a target
met and the guarantee that follows. The business accepted this knowingly. The
redesign should not silently change it either.

### D06 is a genuine semantic conflict, not a label

The column is `payout_destination.bank_account_number` (`String(64)`), but
`frontend/src/lib/payouts.ts:44` validates it as a **16-digit card number**, and
says why: *"Egyptian account numbers vary in length by bank, so no single rule
could check one."* The final design says *account number*. These are different
facts about a real person's money and cannot be relabelled. **Owner decision.**

Alongside it: `payout_destination` supports `instapay` (with the exact submitted
`instapay_address_url`, plus a fallback phone), `bank` (name, holder, number) and
`wallet` (provider, phone) — and the code comments name **Vodafone Cash, Orange
Money, Etisalat Cash and WE Pay**. `V15` is right that the prototype's shorter
wallet list would drop a working method.

### Collaboration start has no column

`app/services/portal.py:185 months_for()` derives a model's first month from
*"the earliest month they have an order in or a payroll snapshot for"*. `H01`
says explicitly that a code's first order is **not** interchangeable with a
collaboration start. There is no `collaboration_start_month` on
`affiliate_profile`. This needs an additive migration in Phase 02, and it is the
schema half of **D01**.

### Shopify

`shopify_api_version = "2026-07"` (`app/config.py:73`, `client.py:70`) — matches
the package's baseline. `REQUIRED_SCOPES = {read_orders, read_all_orders,
read_discounts}`; `read_all_orders` is required and commented as the reason the
60-day window is escapable. **`read_products` is not in that set** — the 4
September handoff says it is granted on the shop, but nothing in this code
requires or verifies it yet, and neither does anything request protected
customer data (needed for `shippingAddress.phone`, `W03`). **I did not verify
live Shopify access:** the local app runs with `shopify.configured = false`, and
verifying it means talking to the one shop staging and production share. That
check belongs to whoever runs it against the real credentials, deliberately.

### Append-only and money invariants — intact

`payroll_snapshot`, `payment_transaction`, `payment_allocation`,
`payroll_adjustment`, `payout_destination` and `policy_version` remain
trigger-guarded; `conftest.empty_the_database()` has to set
`session_replication_role = replica` **`SET LOCAL`** to truncate past them, which
is itself evidence the guards are on. Integer piastres, basis-point rates,
multiply-before-divide and one final rounding are unchanged. 38 ADRs;
`docs/limits.md` is 2,553 lines.

### The ratchet tests

`test_reachability.py` asserts every capability has a way in, that the interface
never calls an unserved route, and that its own exemption list is still honest.
`test_affiliate_access.py` holds the model-boundary guarantees (every refusal is
403 and never 404; one model cannot reach another).
`accent-isolation.test.ts` is 80 of the 104 frontend tests.
**Removing the reopen route (UI52) will fail `test_reachability.py` until its
exemption list is updated in the same commit** — that is the test working.

### Infrastructure

- **`C:` has 1.9 GB free of 98 GB (99% full).** This is the blocker flagged on
  4 September and it is **still present**. It did not stop `npm ci`, pytest or
  the build today, but Docker images, the npm cache and the venv all live there.
  `D:` has 176 GB free.
- No `.github/` — **there is no CI**. Every check is local and manual.
- `railway.json` sets only healthcheck and restart policy; deployment topology
  (two Railway services, separate databases, one shared Shopify shop) was **not**
  re-verified against Railway in this phase, as no deployment action was
  authorised.

---

## 7 · What I did not do, deliberately

No application behaviour change. No Shopify call, write or import. No financial
edit. No push, no branch promotion, no deployment. No invitation or email. The
seed data is the repository's own synthetic fixture in a local Docker database.

---

## 8 · Decisions needed before the next batch

**Only two things actually block Phase 01A**, and one is not a policy question.

### Blocking — owner

**B1 · The three unpushed commits.** Work that exists on one laptop, on a
machine whose system drive has 1.9 GB free, is one disk failure from gone, and
Phase 01A will build on top of it. `main` is also three commits ahead of
`production`, which `CLAUDE.md` says should not persist. I need you to choose:

1. **Push `main`, then fast-forward `production` to it** — the documented rule
   while no real model is onboarded (ADR 0034). Deploys to both staging and
   production.
2. **Push `main` only**, leaving `production` at `025d8a8` — staging gets it,
   production waits.
3. **Push nothing yet**, and I keep working locally.

I recommend **(2)** for now: it gets the work off this machine and onto staging
today, without a production deploy that this handoff explicitly does not
authorise. Promoting `production` can be a separate, deliberate act once you
have walked the staging build. I will not push anything until you say which.

### Blocking — engineering, and mine to resolve

**B2 · ADR 0038's scope.** The approved design puts the same green on the
maintainer's tool, which the accepted ADR 0038 says it should not wear. I will
write a superseding ADR recording that the design decision changed, keep the
one-file accent mechanism and the isolation test, and change only what they
isolate. No owner input needed — flagged because it overturns an accepted
decision rather than an implementation detail.

### Not blocking yet — resolve at their own phase

- **D10** (Phase 01 permission map) — I can record the factual mapping now
  (*Marketing* → `content_manager`; *Finance* has no equivalent). The only
  question needing you is whether anyone actually needs `payments.record`
  without full admin. Answer it during 01B, not now.
- **D01, D02, D04, D05, D06, D07, D08, D09, D03** — unchanged, each due at the
  phase `DECISIONS.md` names. D06 in particular is now confirmed as a real
  card-vs-account-number conflict (§6), not a naming choice, so it needs a real
  answer before Phase 02B.

### Things I resolved myself, and am not asking about

Remote access (works), test counts (measured), role inventory (read from code),
Shopify API version (2026-07, in config), collaboration-start schema gap
(additive migration, Phase 02), stale remote-tracking refs (informational).

---

## 9 · Refined first implementation batch — Phase 01A

The roadmap's 01A is *"tokens/components"*. Refined against what is actually
here, and deliberately kept small:

1. **Re-scope the accent.** Move the four declarations in
   `frontend/src/styles/portal-accent.css` from `.affiliate` to a shared root,
   substitute the approved green (`#14653A` / `#23A95C` light/dark, `--accent-text`
   `#14653A` / `#7BE0A6`, `--accent-soft` at `.09` / `.14`), keep `--accent-on`.
   Rename the file if it is no longer portal-only.
2. **Update `accent-isolation.test.ts`** to the new values and the new scope, so
   it still fails on a hard-coded colour. Do not weaken it.
3. **Write the superseding ADR** for 0038, referencing the approved exports.
4. **Reconcile `tokens.css`** with the exports' surface/divider/muted ramps for
   both themes — read the two `.dc.html` files, do not eyeball the screenshots.
5. **Verify:** `npm test`, `npm run build`, and a side-by-side of both halves in
   both themes at 390 and 1440 against the design references. `pytest` should be
   untouched by this batch; run it anyway to hold the 1589 line.

Explicitly **not** in 01A: navigation changes (that is 01B, and it needs the
route/permission map), anything touching money, and anything Products-shaped.

**01B** should then take the route and permission map, including the retirement
of `UI52` in the same commit as its `test_reachability.py` exemption update.

---

## 10 · Commands the next session needs

```bash
# database (dev data, synthetic)
docker compose up -d postgres

# disposable test database — verify identity before pytest, it drops the schema
docker exec hba-platform-postgres-1 psql -U hba -d postgres \
  -c "CREATE DATABASE hba_platform_test OWNER hba;"

# backend suite: one process at a time, never with a concurrent alembic
DATABASE_URL="postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform_test" \
  .venv/Scripts/python.exe -m pytest -q --color=no > /tmp/pytest.txt 2>&1; echo $?
tail -5 /tmp/pytest.txt

# frontend
cd frontend && npm ci && npm test && npm run build

# a running app to look at
APP_ENV=development DATABASE_URL="postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform" \
  .venv/Scripts/python.exe scripts/seed_demo.py
APP_ENV=development GO_LIVE_MONTH=2026-09 WORKER_ENABLED=false \
  DATABASE_URL="postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform" \
  .venv/Scripts/python.exe -m uvicorn app.main:app --port 8010
# owner@example.com / a-long-enough-password — models: nour@, layla@, sara@,
# malak@, habiba@ (same password). Synthetic; no real data.

# design references
cd docs/redesign/designs && python -m http.server 8765

# package integrity (needs UTF-8 on Windows)
PYTHONUTF8=1 .venv/Scripts/python.exe docs/redesign/evidence/verify-package.py
```

---

## Next step

**Phase 01A**, as refined in §9 — after you answer **B1** (what to do with the
three unpushed commits). Nothing else is blocked.
