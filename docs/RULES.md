# The rules — one shared source, for every agent and every person

**This file is the single current statement of how HBA's platform must behave.**
`CLAUDE.md` and `AGENTS.md` both point here and neither repeats it, because two
copies of a rule are two rules the moment one is edited.

Everything below was moved here **verbatim** from `CLAUDE.md` on 24 September
2026. Nothing was reworded, relaxed or added. The move was a workflow reset,
not a rule change.

## How to change a rule

You do not change one here first. A rule that needs to move needs an **ADR**
saying what is being traded and what it costs (`docs/adr/README.md`), and then
this file follows it. A superseded ADR is never deleted; it is marked and left
in place, and so is the sentence here that it replaced.

## What this file is not

- **Not the workflow.** How to run the tests, which branch to push, how to
  take a screenshot: `CLAUDE.md`.
- **Not the reasoning.** Why a rule exists, in full: `docs/adr/`.
- **Not the specification.** What the system does:
  `docs/specs/2026-08-22-hba-platform-v1-design.md`.
- **Not the failure register.** What has broken and what it looked like:
  `docs/limits.md`.

---

## The two halves

| | Who | Look |
|---|---|---|
| **Maintainer** | Owner, marketing and finance teams on laptops | Laptop-first; match the approved Admin HTML structure and styling |
| **Affiliate portal** (`.affiliate`) | Models on phones | Dark by default, denser, phone-shaped |

**One palette across both, since ADR 0039** — HBA green, both themes, defined
once in `tokens.css` with the accent alone in `accent.css`. `portal.css` is
still scoped to `.affiliate`, but it now isolates *layout* rather than colour:
the phone's spacing, its tab-bar clearance, its furniture. **Keep that
isolation** — it is why the portal could be redesigned three weeks before
payroll without touching a maintainer screen.

## Rules that must not be broken

- **Money is integer piastres.** Never a float. Multiply first, divide once
  (ADR 0003), round once on the total (ADR 0004).
- **Nothing about money is calculated in the browser.** The server sends the
  figure; a second implementation is a second answer waiting to disagree in
  front of the one person guaranteed to check.
- **An agreed month's *money* is read from its snapshot**, never recalculated.
  A live recalculation under the word "paid" presents a working number as a
  debt. **Her sales and order counts are the opposite** (F13, ADR 0040): they
  describe what happened in the month, so a parcel refused in November
  corrects September's sales and chart while September's agreed total does not
  move. A difference after approval is settled as a correction (05C), never by
  restating the agreement.
- **A pending order counts** (F02, ADR 0040). Pending and delivered are paid;
  a failed delivery is not. Approval settles every order it counted, and
  `carried_into` now pays only what a *delivered-only* approval left out — a
  backlog that shrinks and is never added to.
- **No component names a colour directly.** The accent lives in
  `frontend/src/styles/accent.css` — eight declarations, now covering both
  halves (ADR 0039) — and `styles/__tests__/accent-isolation.test.ts` fails the
  build if those values appear anywhere else.
- **No customer data.** `order_index` and `attributed_order` hold no name,
  address, phone or email, and a test keeps it structural.
- **A correction settles money that moved; a balance is money that has not**
  (ADR 0041, amending 0035). Carrying a difference into a later month recovers
  it **there** — taking it off the source month as well recovers it twice, and
  reported E£800 still to send on a month agreed at E£2,000 with E£1,000 sent.
  Absorbing records an **`accepted`**, always: a `writeoff` means *we are not
  sending the rest* and still reduces a balance, which is the opposite of HBA
  taking a loss. Absorbing takes the whole remaining difference, so carry what
  is recoverable first.
- **One gate in front of every writer of a model's money**
  (`app/services/money_gate.py`). `approve_month`, `corrections.resolve` and
  `record_payment` all take it **before reading anything they decide on**, not
  before writing. It locks the *affiliate* row rather than a month because
  approval and `resolve` need the same two month rows in opposite orders, and
  one lock has no order to get wrong. It re-reads on the way in.
- **The payer sees the whole destination** (ADR 0042, amending 0028). The
  approved design puts the real number on the payments row, and the full
  details plus the submitted InstaPay link on the detail card **and on the
  model's profile**, with no reveal step - the owner asked for that
  explicitly. One component draws it (`components/DestinationDetails.tsx`) and
  one permission gates it (`payments.record`), because the screen that drifted
  was the second copy. `mask_destination` still governs every *record*: audit
  rows, logs, notices, change confirmations.
- **Money reads `EGP 1,062.00`**, with the space and a U+2212 minus - the
  approved export's `egp()`, character for character. It said `E£` on every
  screen until 23 September; that was ours, not the design's. Two formatters
  render it, `app/core/money.py` and `frontend/src/lib/money.ts`, and
  `money.test.ts` holds them to the same examples. Two implementations of a
  *format* are safe in a way two implementations of an *amount* are not - but
  they still have to agree.
- **The payments desk is a list of people on the programme** - not
  applications, and not months somebody had not started yet
  (`payments.on_the_desk`, the export's `participants(month)`). The sidebar
  badge counts through the same function: they were computed separately once,
  and the sidebar said 22 over a list of 19.
- **Historical finalisation is locked** until `HISTORICAL_FINALISATION_UNLOCKED`
  is set on that environment. The *review* is never locked - it is how the
  gaps are found. What HBA must supply first is listed in
  `docs/repair/HISTORICAL-INFORMATION-NEEDED.md`.
- **Append-only tables stay append-only**: `payroll_snapshot`,
  `payment_transaction`, `payment_allocation`, `payroll_adjustment`,
  `payout_destination`, `policy_version`. Guarded by triggers.
- **Three compensation types, not one.** `commission`,
  `fixed_plus_commission` (**both** are paid — the one most often got wrong),
  `base_guarantee` (`max(commission, base)`, only where targets were met *and*
  verified). No screen may hard-code an arrangement.

## Where the reasoning lives

- **`docs/adr/`** — 42 ADRs. The index is generated from the files. 0014 is
  superseded by 0036; 0027 is amended by 0038; **0035 is amended by 0041**, in
  one clause — a *write-off* closes a debt and a *credit* does not.
- **`docs/limits.md`** — every failure met, what it looked like from outside,
  and the fix. **Read this before debugging anything.**
- **`docs/plans/`** — what is being built and why.
- **`docs/specs/`** — the original design.
- **The code comments.** This codebase explains its own decisions; a docstring
  that says "and this caught us once" is describing a real incident.

---

## In force during the audit repair, and not a business rule

These are the owner's standing instructions for this branch, kept here because
an agent reading only the rules must still not do them:

- **No merge and no deployment.** Repair work stays on its branch. The
  build-phase instruction to push `main` and `production` together is
  **paused**, not retired - `CLAUDE.md` says by what and when it resumes.
- **Historical finalisation stays locked** behind
  `HISTORICAL_FINALISATION_UNLOCKED` until HBA supplies and verifies the five
  items in `docs/repair/HISTORICAL-INFORMATION-NEEDED.md`, and confirms order
  completeness for those months. The *review* is never locked.
- **Never run destructive fixtures against staging or production.** The test
  runner refuses any database that has not said inside itself that it is
  disposable; that guard is not to be worked around.
