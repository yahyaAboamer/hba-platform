# The staging walkthrough, and what it changed

**Written 4 September 2026.** Continues
`2026-09-03-portal-redesign.md`, which covered phases 1–5.

The business walked the finished portal on staging with a real model's data —
**jana adel, code SARAED** — across 24 screenshots and three written passes.
This records what that found, what was decided, and what is still open.

Four decisions were large enough to be ADRs and are not repeated here:

| ADR | Decision |
|---|---|
| [0035](../adr/0035-an-adjustment-closes-a-difference.md) | An adjustment closes a difference; it never opens a larger one |
| [0036](../adr/0036-pre-go-live-months-are-ordinary-months.md) | Months before go-live are ordinary months, settled outside — **supersedes [0014](../adr/0014-historical-months-show-sales-only.md)** |
| [0037](../adr/0037-what-you-were-paid-is-not-how-you-sold.md) | What a model was paid and how their sales performed are two numbers |
| [0038](../adr/0038-the-portal-wears-the-brand-the-tool-does-not.md) | The portal wears the brand; the maintainer's tool does not — **amends [0027](../adr/0027-numerals-change-face-when-a-figure-becomes-an-obligation.md)** |

Four failures are recorded in `docs/limits.md`: the settle loop, the reopened
month offering its whole figure again, the missing placed-at value, and
outcome-only targets on backfilled months.

---

## What the walkthrough found

### Money

**The settle loop.** Reconstructed from the database rather than the screen:
August's obligation was E£4,332, transfers were E£4,589, so the true
overpayment was **E£257**. The screen reported **E£5,074** and each press of
*Settle the difference* doubled it. One sign in `balance_for`. ADR 0035.

**Its cause, one step earlier.** August was approved at E£760 and paid; then
reopened, re-approved at E£3,829, and paid **in full again** — because the Pay
button offered the whole new figure and said nothing about the E£760 already
sent. The difference owed was E£3,069.

### The Month screen was never rebuilt

Phase 2 added the redesign's *data* — the closing window, the average order —
and left the old layout around it. The Phase 2 report said "tiles"; there are
no tiles. The figure has no card and no state chip, the targets have no
progress bars, and *See every order* is a text link rather than a block button.

### Everything else

- **Void orders** show no amount, because the placed-at backfill has not run.
- **Your year** plotted the month in progress, so September's part-month
  dragged the line down from August as though earnings had collapsed.
- **Grow and Month** both showed the targets.
- **The You screen** overlapped *Show them in full* with *Change where I am
  paid* — two inline siblings with no layout between them.
- **Payments** showed an overpaid month in settled green under the heading
  *Nothing outstanding*, and never reconciled its own arithmetic on screen.
- **The glossary** is eight paragraphs of equal weight jammed against the left
  edge.

---

## The work

Ordered as it will be done. Money first, then the screen a model looks at
every day, then the rest.

### 1 · Money

- **The settle loop** — sign and cap, per ADR 0035. Rewrite
  `test_a_credit_increases_what_a_later_month_owes`, whose fixture and
  docstring describe different scenarios.
- **Clear the three junk adjustments on staging** (E£4,817 against a real
  E£257). `payroll_adjustment` is append-only, so they are deleted at the
  database. **Production has never had an adjustment recorded.**
- **"Already sent" on the payment screen** — show what has gone out for the
  month, default the amount to the remainder.

### 2 · The Month screen, properly

Figure in a card with its state chip · counted and average as **two tiles** ·
*On its way* as its own outlined box with the ⓘ · targets with **progress
bars** · *See every order* as a block button · the month bar gains its state
sub-label.

### 3 · Orders and Year

- Run the re-import so a cancelled order can show its **placed-at value struck
  through**, and show the would-be commission struck through beside it.
- **Drop the month in progress** from both charts. It also leaves the year
  total, which becomes "across N closed months" — otherwise the visible points
  do not sum to the headline.
- Rename the line chart **"What your sales earned"**, ring the guarantee
  months, per ADR 0037.

### 4 · Grow and You

- **Remove the targets from Grow.** Month keeps them.
- **Fix the overlapping buttons** — the reveal becomes a quiet link above the
  primary button, not beside it.
- Soften the solid-red toggles; the accent is a line, not a flood (ADR 0038).

### 5 · Pay history, and the year made whole

Per ADR 0036. The largest piece, and the one with a mockup already built:
`docs/design/pay-history-editor.html`.

- **The editor.** New model, or already with HBA. If already: same throughout,
  or a month strip where a click sets one month and a shift-click sets a range.
  Arrangement, rate, amount, and for guarantee months a met/missed toggle per
  month. Consecutive identical months collapse into one period, because that is
  what `set_terms` writes.
- **`set_terms` needs no change.** Its docstring already says *"Backfilling
  earlier history is left alone"* — closed backdated periods with differing
  types are accepted today, and the database refuses overlaps.
- **`settled_externally`** on the payroll month: approved, frozen, balance
  structurally zero, never payable.
- **`historical` leaves the model's screens.** One line on Payments, shown only
  to a model who has a month before go-live.

### 6 · The glossary

Option B with C's info buttons: each entry becomes the question a model
actually asks, expanding to its answer, with ⓘ next to the figures that link
into it.

---

## Decided during the walkthrough

- **The accent is HBA red**, chosen over Nocturne's blurple after seeing both.
- **Errors are amber.** Two reds cannot both mean something.
- **The month-on-month comparison is cut entirely** — no threshold made a
  part-month against a whole one honest.
- **Commission rates are static per model**, set when the application is
  approved. Salaries and guarantees change; rates do not. Nothing is
  hard-coded to 10%.
- **The "old dashboard" line is conditional** — a model with no month before
  go-live never sees it.
- **No paste-a-table import.** The month strip is enough.
- **Models are told about old-versus-new differences before the portal opens**,
  in a message, not by a banner. A banner invites an audit of months nobody
  would otherwise have questioned.

## Still open

1. **The historical salary and guarantee amounts, with their start months**,
   per model. Commission can be backdated blind because it is static; a salary
   cannot be invented.
2. **Go-live differs by environment** — staging `2026-08`, production
   `2026-09`. Anything reading it must not assume one and run in the other.
3. **Phase 6, products under the code**, remains post-launch.

## Verification

The floor is **1,548 backend tests and 87 frontend**. Beyond it:

- **ADR 0035** — settling an overpayment leaves the month at zero, and settling
  twice cannot leave it further from zero than once.
- **ADR 0036** — a pre-go-live month can be approved and can never carry a
  balance; a backfilled target records an outcome with no counts.
- **ADR 0037** — the all-time guarantee count uses only months on that
  arrangement.
- **ADR 0038** — already enforced by `accent-isolation.test.ts`, which reads
  the accent file and fails if its values appear anywhere else.
