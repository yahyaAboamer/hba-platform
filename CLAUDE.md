# hba-platform

Commission and payroll for ~20 Egyptian beauty models at **HBA Aesthetics**.
FastAPI + SQLAlchemy + Postgres, React + Vite, on Railway.

**Read `docs/plans/2026-09-04-continuation-handoff.md` first** — it says where
the work is right now. Everything below is the part that does not change.

---

## The two halves

| | Who | Look |
|---|---|---|
| **Maintainer** | 2 people, laptop, month end | Cool neutrals, dense, colour only for money state |
| **Affiliate portal** (`.affiliate`) | ~20 models, phone, arriving from an email | Dark by default, HBA red, Nocturne's ramps |

They share `tokens.css` and nothing else. `portal.css` is scoped to
`.affiliate`, which is why the portal could be redesigned three weeks before
payroll without touching a maintainer screen. **Keep that isolation.**

## Rules that must not be broken

- **Money is integer piastres.** Never a float. Multiply first, divide once
  (ADR 0003), round once on the total (ADR 0004).
- **Nothing about money is calculated in the browser.** The server sends the
  figure; a second implementation is a second answer waiting to disagree in
  front of the one person guaranteed to check.
- **An agreed month is read from its snapshot**, never recalculated. A live
  recalculation under the word "paid" presents a working number as a debt.
- **No component names a colour directly.** The portal's accent lives in
  `frontend/src/styles/portal-accent.css` — eight declarations — and
  `styles/__tests__/accent-isolation.test.ts` fails the build if those values
  appear anywhere else.
- **No customer data.** `order_index` and `attributed_order` hold no name,
  address, phone or email, and a test keeps it structural.
- **Append-only tables stay append-only**: `payroll_snapshot`,
  `payment_transaction`, `payment_allocation`, `payroll_adjustment`,
  `payout_destination`, `policy_version`. Guarded by triggers.
- **Three compensation types, not one.** `commission`,
  `fixed_plus_commission` (**both** are paid — the one most often got wrong),
  `base_guarantee` (`max(commission, base)`, only where targets were met *and*
  verified). No screen may hard-code an arrangement.

## Where the reasoning lives

- **`docs/adr/`** — 38 ADRs. The index is generated from the files. 0014 is
  superseded by 0036; 0027 is amended by 0038.
- **`docs/limits.md`** — every failure met, what it looked like from outside,
  and the fix. **Read this before debugging anything.**
- **`docs/plans/`** — what is being built and why.
- **`docs/specs/`** — the original design.
- **The code comments.** This codebase explains its own decisions; a docstring
  that says "and this caught us once" is describing a real incident.

## How the business works with us

- **Answer every question before implementing.** They walk the product on a
  phone, write up what they saw, and expect the questions answered and the
  choices laid out *before* anything is built. Then they approve, then build.
- **Give a recommendation, not a survey.** They ask for options and pick fast.
- **Ship in batches**, each merged and promoted on its own.
- **Push to both branches.** `main` deploys staging; `production` is a
  fast-forward of `main` and deploys production. Both stay current while no
  real model is onboarded (ADR 0034). Staging and production are **separate
  Railway services with separate databases** — but they **share one Shopify
  shop**, so never start a bulk import from staging.
- **Never claim something works without running it.** They test on a real
  phone with real data and will find it.

## Verification

- Backend: `.venv/Scripts/python.exe -m pytest -q` — **1558 passing**, and no
  change merges below that. It takes 5–15 minutes; run it in the background.
- Frontend: `cd frontend && npm test` (87) and `npm run build`.
- The suite is the ratchet. `test_reachability.py` fails when a route has no
  way in from the interface; `accent-isolation.test.ts` fails on a hard-coded
  accent; the writable-routes guard fails when anybody adds a route a model
  can call. **These failing is them working.**

## Environment

- Windows, Git Bash. Use `.venv/Scripts/python.exe`, not `python`.
- `GO_LIVE_MONTH` differs: staging `2026-08`, production `2026-09`. Never
  assume one while running in the other.
- Staging database access: `railway ssh --service hba-platform-staging
  --environment staging` and run Python inside the container — the
  `DATABASE_URL` host only resolves in Railway's network.
