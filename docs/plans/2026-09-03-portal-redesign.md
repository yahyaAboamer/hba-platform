# The model-facing portal, redesigned

**Written 3 September 2026. Supersedes the M2–M4 walkthroughs.**

The business mocked up a redesign in Claude Design and handed over a bundle
(`dashboard-redesign-for-affiliate-platform`). This plan is what it takes to
build it, corrected for the four things the design tool could not know.

The deadline is **30 September 2026** — the twenty models must be onboarded
before a real month is paid through the platform.

The accent is **HBA red**. See [Decided](#decided) for the terms that came
with that.

---

## What is being adopted, and from where

The bundle holds three things, not one:

| File | What it is |
|---|---|
| `Affiliate Portal Redesign.dc.html` | A comparison board. Section 0 rebuilds our five tabs as they are today; section 1 offers four directions plus a critique. |
| `Affiliate Portal v2.dc.html` | **The design being built.** An interactive prototype — a different, later design from all four directions. |
| `_ds/nocturne-…/` | The design system v2 sits on. Dark ground, Inter, 8px radii, compact 0.7× spacing, outlined buttons. |

**Nocturne's structure is adopted; Nocturne's accent is not.** Everything
else — the tonal ramps, the spacing scale, the elevation model, the rule that
the accent is a line and never a flood — is taken as written.

The live preview of the result is `docs/design/portal-redesign-preview.html`,
published for inspection. It is a prototype and is not wired to the API.

---

## What the design tool did not know

It read our real source on 2 September, so section 0 is accurate. But it only
ever saw one kind of model. These are not stylistic disagreements; each one
would be a false statement about somebody's money.

### 1. There are three arrangements, not one

Every screen in the prototype assumes pure commission. `CompensationType`
carries three, and their real names say what they do:

| Type | What is paid |
|---|---|
| `commission` | Sales commission alone. |
| `fixed_plus_commission` | **Both.** `exact = commission + fixed`. The salary does not replace the commission. |
| `base_guarantee` | `max(commission, base)` — and only when targets are achieved *and* verified. A floor, never a bonus and never a cap. |

The middle one is the one most easily got wrong from its name, and it was got
wrong twice: once by the design prototype, and once by the first version of
`docs/design/portal-redesign-preview.html`, which showed the salary alone and
printed "Your sales do not change what you are paid". **The engine has always
been right** — `calculate.py` computes `commission + fixed` and rounds once on
the total. Only the mock-ups were wrong, and both are corrected.

**Consequence:** the Month screen is built from `makeup`, which already
carries whichever lines apply. No screen may hard-code an arrangement, and no
screen may imply that sales are irrelevant to anyone.

### 2. Targets sometimes decide pay

The prototype prints *"These are for HBA's records. What you are paid is your
commission either way."* under the targets. For anyone on a guaranteed
minimum that is false — meeting the targets is exactly what makes the
guarantee apply.

`_targets()` already returns `determines_pay`. The copy is driven by it:

| Arrangement | What the card says |
|---|---|
| `commission` | These are for HBA's records. What you are paid is your commission either way. |
| `fixed_plus_commission` | These are for HBA's records. You are paid your salary and your commission either way. |
| `base_guarantee` (`determines_pay`) | **These decide what you are paid this month.** Your guaranteed minimum applies only in a month where you meet them — otherwise you are paid your commission. |

Neither of the first two may say the targets make no difference *to the sales*
— only that they make no difference to the basis of pay.

### 3. The customer discount stays off the model's screen

The prototype writes *"15% off for them, 15% of the sale to you"*, treating
the customer discount and the commission rate as one number. They are
independent, and flow 1 already agreed the customer discount is never shown
to a model again.

**The Grow tab says only:** "You earn 15% of every sale that counts."

### 4. Nothing existed for a month that is blocked, or that changed

The prototype has no state for "HBA has not set your rate yet", and none for
a figure that moved after the model was told it. Both already exist in the
API — `waiting_on`, `recalculated`, `credited_from` — and all three are
there for reasons that matter more, not less, once real money moves.

**Consequence:** every one of them gets a designed state in Phase 2. None may
be dropped for being ugly.

---

## Corrections to the prototype

Beyond the four above:

- **The share link is removed.** `hbawear.store/?code=HBA15` is not how the
  storefront applies a discount. The code alone, copyable from every screen.
- **Three notification toggles become two.** "Every order that counts" would
  be an email per order.
- **"What sells under your code" is phase 6.** It needs Shopify line items,
  which the platform does not store.

## Already built — not rebuilt

The prototype lists these as new. They are not:

- **Transfer receipts on each paid month.** `GET /me/payments/{id}/proof`
  exists and `MyPayments` already renders the image. Restyle only.
- **Pre-platform months hollow on the line.** `my_year` already returns
  `null` — never `0` — for a month before go-live, with its real order count,
  and `MyYear` already draws them hollow. This closes the item recorded as
  M2/M3 work; it was mostly done.
- **A void order keeps its amount, struck through.**

---

## The colour problem, and how it is settled

HBA red is a well-formed system colour: built on Nocturne's own lightness
scale at our hue, the ramp's 600 step is `#e5001c` against a brand `#e6001c`.

The difficulty is only the dark ground:

| Against | HBA red `#e6001c` | Nocturne `#9184d9` |
|---|---|---|
| Page `#161826` | 3.67 : 1 | 5.45 : 1 |
| Card `#232532` | **3.17 : 1** | 4.71 : 1 |

3:1 is enough to draw a border. 4.5:1 is what text needs. So on the dark
theme the brand red draws lines, borders and the active tab, and **a lighter
step of the red ramp carries any figure that has to be read.** On the light
theme the problem disappears entirely.

### The collision that has to be solved in Phase 1

`portal.css` sets `--refused: #a83224`, and six model-facing screens use
`notice--refused` for errors. With a red accent, an error and a brand element
become the same colour family.

**Errors move to amber.** `tokens.css` already defines `--owed: #b54708` as
"attention, not alarm", void orders are already grey and struck through rather
than red, and that frees red for the brand entirely. The alternative — keeping
red for errors and restricting the accent — would have left two reds one step
apart on the same screen.

---

## Decided

- **Accent: HBA red**, dark by default with a light toggle.
- **The accent must stay cheap to change.** The entire brand decision lives in
  eight declarations in one file:

  ```css
  /* frontend/src/styles/portal-accent.css — the whole decision */
  .affiliate {
    --accent:      #e6001c;             /* chrome: lines, fills, active tab */
    --accent-text: #b20013;             /* the step legible as text (light) */
    --accent-soft: rgba(230, 0, 28, .10);
    --accent-on:   #ffffff;             /* text on a filled accent */
  }
  .affiliate[data-theme="dark"] {
    --accent:      #e6001c;
    --accent-text: #ff968b;             /* lifted, because 3.17:1 cannot be read */
    --accent-soft: rgba(230, 0, 28, .18);
    --accent-on:   #ffffff;
  }
  ```

  Switching to Nocturne after testing is editing those eight lines. **No
  component may name a colour directly** — that rule is what keeps the promise,
  and it is enforced by review, not by hope.

- **Grow ships whole, products included** — in phases. `read_products` was
  added to the Shopify app when it was built, for this.
- **Two notifications only**: a month closed, a payment sent.
- **No share link.**
- **The redesign replaces the M2–M4 walkthroughs.**

## Settled, 3 September

1. **Errors move to amber.** Red is the brand's.
2. **The month-on-month comparison is cut entirely.** A part-month measured
   against a whole one reads as a collapse on the 2nd and a triumph on the
   30th, and no threshold rule made it honest. `compared_to_last` is not
   built. One less field, one less way to mislead.
3. **Sales are shown to everyone, and they matter to everyone.** On
   `fixed_plus_commission` the sales *are* part of the pay — the salary is
   added to the commission, not swapped for it. No screen says otherwise.

No open questions remain. Phase 1 can start.

---

## The phases

Everything is scoped to `.affiliate`. **No maintainer screen is touched by any
phase below** — that isolation already exists in `portal.css` and is why this
is safe to do four weeks before payroll.

Each phase merges to `main`, deploys to staging, and promotes to production,
per the standing instruction to keep both current while no real model is
onboarded.

### Phase 1 — Foundation · *launch-blocking*

The shell everything else sits on.

- `portal-accent.css` (new): the eight declarations above, and nothing else.
- `portal.css`: rewritten onto Nocturne's ramps, spacing (0.7×) and elevation.
  Light and dark, `data-theme` on the portal root, dark as the default, choice
  remembered per device.
- `AffiliateLayout.tsx`: header becomes avatar → **You**, name, and a
  **copy-code button present on every screen**. Tab bar becomes
  Month · Orders · Payments · Year · Grow.
- Errors resolved to whichever answer open question 1 gets.

*Closes the owed flow-1 item "the sign-out and glossary links wrap" — they
leave the header entirely.*

**Done when:** every existing screen renders in both themes with no colour
named outside `portal-accent.css`, and the accent can be swapped by editing
that one file.

### Phase 2 — The Month screen · *launch-blocking*

The screen that answers *how much, and when does it land*.

**Backend** (`app/services/portal.py`):

| Field | What it is |
|---|---|
| `window` | Opens, closes, the words for both, progress %, days left. Derived from `businesstime`; for an agreed month, the date it was paid. |
| `average_order` | Counted sales ÷ counted orders. `null` at zero orders. |

**Frontend** (`MyMonth.tsx`): headline and state tag; progress line from month
start to close; counted-sales and average-order tiles; "On its way"
with its ⓘ; collapsible breakdown built from `makeup` **for all three
compensation types**; targets card with copy driven by `determines_pay`;
`waiting_on` blockers rendered; `recalculated` and `credited_from` notices
designed rather than dropped.

**Done when:** all three compensation types read correctly, a blocked month
says whose move it is, and a month that changed says so.

### Phase 3 — Orders and Payments · *launch-blocking*

- **Orders**: All / Counted / Moving filter with counts; a row expands to show
  the commission that order earned and why. *This closes the owed flow-1 item
  "show the commission figure in the worked example", on the screen where a
  model actually asks the question.*
- **Payments**: "Next payment" leading with amount, window and destination;
  paid months restyled; receipts kept as they are.

### Phase 4 — Your year, and Grow without products

Not launch-blocking, but cheap once Phase 1 lands.

- **Year**: money as a line, orders as bars, tap a month to read it, hollow
  months for pre-platform. Best month and month-on-month tiles.
- **Grow**: the code, large, with copy. This month's asks with progress. No
  share link. The products card is present but marked as coming.

### Phase 5 — You, and notifications

- **You**: reached from the avatar. Payout change as a bottom sheet, with the
  confirmation said out loud. Glossary, policy and sign-out as a list.
- Closes three owed flow-1 items: **a model may reveal their own payout
  details in full**; **a dropdown of Egyptian banks with a sanity check on the
  account-holder field**; **a dropdown of wallet providers**.
- **Notifications** (new): a preference table, two kinds, both on by default,
  read at the single send point in `notifications.py`. One migration.

### Phase 6 — What sells under your code · *after go-live*

The largest item, and the only one that is genuinely new system rather than a
new screen. `order_index` is deliberately thin (§10.2) and holds no products.

1. A line-item table keyed on the Shopify order.
2. Ingestion on the order webhook, plus a backfill for existing orders.
3. An aggregate endpoint: products under one affiliate's code, for one month.
4. The card on Grow.

**No customer data is added.** Products only — the same rule the rest of the
platform already keeps.

---

## Sequence

| | Phase | Blocking? |
|---|---|---|
| 1 | Foundation | **Yes** |
| 2 | Month | **Yes** |
| 3 | Orders and Payments | **Yes** |
| 4 | Year and Grow | No |
| 5 | You and notifications | The screen yes, the toggles no |
| — | *Onboard the twenty* | |
| 6 | Products | After |

Phases 1–3 and the You screen are what must be true before a model is
invited. Everything after can land while the twenty are already using it.

## Still deferred, and still owed

These are admin-side and were agreed during flow 1. The pause on them is not
a decision; they are recorded in `2026-09-02-model-side-first.md` and stand:
removing the customer discount field, the worked-example commission figure,
adding targets from a model's own page, more columns on the affiliates list,
verifying the same-code no-op, and splitting the discount-code copy.

Flows 2 to 6 — attribution, payroll, payments, targets — remain unstarted.

## How each phase is verified

The existing suite is the floor: **1,516 backend tests** passed before this
work began, and no phase merges below that number. Beyond it, each phase adds
tests for the thing it claims:

- Phase 2: one test per compensation type asserting the targets sentence; one
  asserting `fixed_plus_commission` shows **both** the commission line and the
  salary line and totals them; one asserting a blocked month names HBA.
- Phase 3: the expanded order row's arithmetic matches `makeup`.
- Phase 5: a disabled preference stops exactly one message and no other.
- Phase 6: an order with line items adds no customer field to any response —
  the same structural test that keeps `attributed_order` thin.
