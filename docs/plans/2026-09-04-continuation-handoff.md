# Where the work is — 4 September 2026

**Written to be the first thing a new session reads.** `CLAUDE.md` says what
the platform is and what may never be broken; this says what is done, what is
next, and what somebody is waiting on.

**The deadline is 30 September 2026** — twenty models onboarded before a real
month is paid through the platform.

---

## Done and live on both environments

Phases 1–5 of the portal redesign, then four batches of corrections from the
business's own walkthrough of staging with real data.

| | |
|---|---|
| **Phase 1** | Portal foundation — `portal-accent.css`, both themes, dark default, the new header and tab bar (Month · Orders · Payments · Year · Grow), errors moved to amber |
| **Phase 2** | Month screen — the closing window, average order, all three arrangements |
| **Phase 3** | Orders filters and expanding rows; Payments says where the money goes |
| **Phase 4** | Year charts readable by tap; Grow |
| **Phase 5** | You screen, reveal payout in full, bank and wallet dropdowns, account-holder check, two notification toggles |
| **Batch 1** | The settle loop (ADR 0035), the overpayment warning |
| **Batch 2** | Month screen rebuilt to the design — headline card, chip, tiles, target bars, block button |
| **Batch 3** | Void orders show what they would have earned; Year drops the month in progress |
| **Batch 4** | Month screen reordered; `.block` styled — it had never reached `portal.css` |

**1558 backend tests, 87 frontend.** Staging and production run the same
build.

## What is left

### 1 · Pre-platform months become ordinary months — **the big one**

ADR 0036, task #17. The business wants a model to open March and see exactly
what she sees in August: sales *and* commission, no "historical", no hollow
chart points. *"I don't want the models to feel that we treated them
differently."*

The data is already there — `attributed_order` covers 2026-01 onward with real
commission bases. Two things block it:

1. **No compensation terms before go-live.** `set_terms` already accepts
   closed backdated periods with differing types (its docstring: *"Backfilling
   earlier history is left alone"*), and the database refuses overlaps. **The
   schema needs no change.** What is missing is the admin screen.
2. **`ALREADY_SETTLED_OUTSIDE` blocks approval.** It becomes a *mode* rather
   than a blocker: the month is approved and marked settled externally, its
   balance structurally zero, never payable. That is a stronger guarantee than
   the blocker it replaces.

**The editor is designed and approved**, with an interactive mockup at
`docs/design/pay-history-editor.html`:

- A fork — new model, or already with HBA.
- If already: "same throughout?" or a month strip. Click one month, shift-click
  for a range.
- Per selection: arrangement, rate, amount, and for guarantee months a
  met/missed toggle per month.
- Consecutive identical months collapse into one period, because that is what
  `set_terms` writes.
- **No paste-a-table import.** The business chose the strip.

Then the model's side: `historical` leaves every screen, and one line on
**Payments only**, shown only to a model who actually has a month before
go-live.

**Historical targets record an outcome, not counts.** The business knows
whether a target was met; it does not have March's video and story numbers, and
inventing them would be fabricating evidence for a figure that decides money.
The Targets card shows an em dash and says the numbers were not kept.

### 2 · The glossary — task #18

Approved: **option B with C's info buttons.** Each entry becomes the question a
model actually asks (*"Why did my figure change after the month closed?"*),
expanding to its answer, with ⓘ next to the figures that link into it. The
current page is eight paragraphs of equal weight jammed against the left edge.

### 3 · Not yet built, from ADR 0037

- **The guarantee ring** on the Year chart — a month where the guarantee
  applied is marked, so a low sales point is not misread as a bad month.
- **Arrangement-aware all-time tiles** — commission: best month and orders;
  salary: best month and salary for the year; guarantee: *"your guarantee
  applied in 4 of 6 months"*, counting **only months on that arrangement**.

Neither is visible until a base-guarantee model exists to show it on.

### 4 · Phase 6 — products under the code

Post-launch by design. Needs Shopify line items, which §10.2's index
deliberately does not store. `read_products` scope is already granted.

## What somebody is waiting on

- **The historical salary and guarantee amounts, with their start months**, per
  model. Commission can be backdated blind because it is static and set at
  approval; a salary cannot be invented. **These get entered through the
  editor once it exists** — nothing is blocked on them today.
- **`C:` on the business's machine is full**, which breaks git, npm and the
  venv. Flagged 4 September.

## Decisions already taken — do not reopen

- **HBA red**, dark by default with a light toggle. Errors are amber.
- **The month-on-month comparison is cut entirely.** No threshold made a
  part-month against a whole one honest.
- **Commission rates are static per model**, set when the application is
  approved. Nothing hard-coded to 10%.
- **No share link.** `?code=` is not how the storefront applies a discount.
- **Two notifications only** — month closed, payment sent. Security mail is not
  gateable.
- **The "old dashboard" line is conditional** — a model with no month before
  go-live never sees it.
- **Models are told about old-versus-new differences before the portal opens**,
  in a message, not by a banner.
- **ECC was considered and declined** for now — a global harness install days
  before payroll, aimed at structure this project already has.

## Two things I got wrong, recorded so they are not repeated

**I claimed the Pay screen caused the original overpayment.** It did not. It
showed *"Already sent, across versions −E£760.00"*, computed the remainder,
pre-filled it, and warned when the full figure was typed over it. Everything
was said — all of it in the same grey. `limits.md` carries the correction under
*"The overpayment was typed, not offered"*. **Check what a screen looks like
before concluding it failed to say something.**

**I reported Phase 2 as having built tiles.** It had not; it added the data and
left the old layout. The business caught it on a phone. **Do not report a
design as built without looking at it.**

## The state of staging

Jana Adel (affiliate 2, code SARAED) is the test model. Her payment history was
cleared on 4 September so the pay flow can be re-walked from clean: August is
approved at **E£4,332** with nothing paid against it. All eleven append-only
triggers were verified back on afterwards via `pg_trigger.tgenabled`.

366 void orders were backfilled with their placed-at value, so a cancelled row
shows its price struck through. **Not by bulk import** — staging and production
share one Shopify shop and Shopify permits one bulk operation per shop.
