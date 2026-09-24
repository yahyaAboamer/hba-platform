# Where the work is — 24 September 2026

**Replaces `2026-09-16-exact-design-handoff.md`** and every handoff before it.
Those are kept, with a banner at the top saying what in them is no longer
true. Nothing was deleted.

## The exact position

| | |
|---|---|
| **Branch** | `repair/batch-2` |
| **Revision reviewed** | The sweep describes `f83b4fc` — *Every screen at both widths, and 390 at last*. **One code change since**: the best-sellers commit on top of `ffde978` (*Best sellers say what they count*), which touches `app/api/affiliate_self.py`, `frontend/src/screens/MyWardrobe.tsx` and tests, and recaptures `portal-wardrobe-390` plus a new `portal-best-390`. **Then** batch C (`1b1bb21`, earnings explanations and per-order commission) and batch D on top of it (Orders against the approved HTML), both below. **Batch D closed at `7bd9650`; batch E** (shared typography, identity headers, month controls) on top of it, in its own section below. |
| **Current head** | run `git rev-parse --short HEAD`. Not written here: a document cannot contain the hash of the commit that adds it, and the last attempt was stale one commit later. |
| **Tree** | clean apart from `.claude/settings.json`, the owner's plugin config, deliberately not committed |
| **`origin/main`** | `6a13958` |
| **`origin/production`** | `6a13958` — **level with `main`**, gap of 0 commits, read from `git ls-remote` on 24 September |
| **Backend** | 2,069 tests, 80 files, all passing through `run-suite.sh` on 24 September, after batch D's corrections; matches `--collect-only`. Batch E changed one backend line (an added `start_month` in `/api/auth/me`); the three files that read that payload pass (158 tests); the full runner was not re-run for it |
| **Frontend** | 403 tests, 19 files; `npm run build` green (24 September, after batch E) |
| **Migration head** | `b1f0a40c0001` |

> **Correction, 24 September 2026.** An earlier version of this table said
> production was *"122 commits behind `main`"*. That was wrong. It came from
> the **local** `production` ref, which nobody had updated and was sitting at
> `025d8a8`; `git ls-remote` shows `origin/production` and `origin/main` both
> at `6a13958`, a gap of **zero**. The memory that records this instruction
> even says to check `origin/production..origin/main` — with the `origin/`
> — and the check was run without it. Read the remote before describing it.

## Standing restrictions, still in force

- **No merge.** And separately: **no deployment.** These are two permissions,
  not one. Being told the repair may merge to `main` does **not** authorise
  promoting to `production` — `main` deploys staging, `production` deploys to
  the people who use it, and the second needs its own yes.
- **Historical finalisation locked** behind `HISTORICAL_FINALISATION_UNLOCKED`.
  The *review* is open and is how the gaps get found.
- **No destructive fixture against staging or production.**

## What is done

**Batch 1 — the financial rules.** F1 repeated-credit release accounting, F2
source/destination cash accounting, F3 one money gate in front of every writer
of a model's money, F4 operation-key identity through `_replay_of`. ADRs 0041
and 0042 record the two rule changes. Report:
`docs/repair/2026-09-19-batch-1-financial-rules.md`.

**Batch 2 — data contracts, A09, A12, and the visual review.** The bulk
historical review and a finalisation safe to repeat and refused by default;
component tests that actually exercise failed requests; and, on 23 September,
the complete visual and interaction sweep. Report:
`docs/repair/2026-09-20-batch-2-data-contracts.md`, ending in the A03 section.

**The sweep itself:** 69 matched pairs in `docs/repair/batch-2/visual/shots/`,
every admin screen at 1280 and 1440 and every model screen at 390, a JSON
digest beside each, and eight interaction checks passing. The reading of it,
row by row, is `docs/repair/batch-2/visual/CHECKLIST.md`.

## What is waiting on Yahya

1. **Five historical facts**, unchanged:
   `docs/repair/HISTORICAL-INFORMATION-NEEDED.md`. Finalisation cannot be
   unlocked without them, and confirming the order import is complete is the
   one that cannot be worked out from the data.
2. **Nothing from the sweep, by default.** An earlier version of this line
   said all thirteen differences needed his decision. That was wrong. **The
   approved HTML decides**, so an ordinary difference from it is
   implementation work, not a question. It becomes a question only where a
   **later, explicit** instruction from him conflicts with the HTML — and the
   one such case recorded is the month grid, which he asked for **for terms
   editing** and nowhere else. An internal ADR or a privacy choice we made
   ourselves is not such an instruction; where we keep one, it is written
   down as a divergence with its reason (see the memory *the approved design
   wins over internal decisions*).

## The bounded task that was proposed, and is now done

*Finish the three screens the sweep could not exercise, by growing the seed.*
Done on 24 September, and widened to five: the two wardrobes and the
invitations list were in the same condition. The seed carries invitations in
three states, a visible and a hidden feature request, three gifts across the
three delivery states, and the evidence of a simulated Shopify sync. All five
screens were **re-captured**, at 1280, 1440 and 390, and inspected as pictures
as well as diffed as text. No application behaviour changed.

What it found is in `docs/repair/batch-2/visual/CHECKLIST.md`: two screens
settled as matching, seven new differences that only became visible once the
data was there, and three things still not verifiable with what the seed has.

## Done since: best sellers follow the counting rule (24 September)

The export and ADR 0040 agreed; only the words disagreed. **The server was
already right** — `best_sellers_for` has filtered on `COUNTED_STATES`
(delivered and pending, never a failed delivery) since batch 1, `0a2ba69`.
The checklist's claim that it was delivered-only was mistaken, and is
corrected there.

- *Your best sellers* reads *"Sales through {her code} · all time · delivered
  and pending"*; *All products sold* reads *"Every product sold through {her
  code}, all time. Delivered and pending orders; failed deliveries
  excluded."* — the export's words, her code where it says HBA15.
  `/api/me/best-sellers` now carries `codes` for that; nothing else in the
  payload moved.
- `tests/test_best_sellers.py`, six tests through `upsert_order_index` and
  `upsert_line_items`: a pending EGP 4,500 coat outranking a delivered EGP
  3,000 dress with a failed EGP 9,000 bag excluded; a never-answered order
  counting; pending→delivered staying one sale; pending→failed leaving;
  refunded, cancelled and returned after delivery keeping its full EGP 3,000.
  Four of the six fail if the filter is set back to delivered-only — checked.
- No payroll, snapshot, payment or ledger code was touched.

## Done: batch C — earnings explanations and per-order commission (24 September)

**Batch C — the counting rule in the words and the order rows.** The three
delivered-only displays found during the best-sellers batch, fixed together.
The owner explicitly asked for a pending order's commission on its row.

1. **My Calculation.** The rule line is the export's sentence: *"Commission is
   10% of net sales on delivered and pending orders. Failed deliveries are
   excluded."* The comment calling pending *05A's preview* is gone. A month
   agreed before ADR 0040 says instead *"{Month} was agreed counting
   delivered orders only: …"* — the earnings payload now carries `policy`
   (the snapshot's own on an agreed month).
2. **Payment detail, *Counted sales*.** Unapproved: *"Delivered and pending
   orders. Failed deliveries excluded."* (the export). Approved under the live
   rule: *"As approved. Failed deliveries excluded."* — the export's, and
   what it already said. Approved delivered-only: *"As approved, on delivered
   orders only — the rule before pending orders counted. …"*. The statement
   now carries `policy`; no figure on it moved.
3. **My Orders.** `_order_commission` in `app/services/portal.py` counts by the
   month's own rule (`counted_states_for(policy)`): delivered and pending
   under the live rule, delivered only on a delivered-only agreement. The rate
   is the month's own — the snapshot's on an agreed month, the terms in force
   for that month otherwise. A valid zero is `EGP 0.00`; no terms for the
   month is `null` with `rate_missing: true`, and the row says *not available*.
   A failed delivery that keeps its base now gets the struck-through
   would-have-been figure the export draws (it printed a dash). Each row also
   carries `counted`. The pending explanation is the export's sentence word
   for word.
4. **The staff order view** (`app/api/orders.py`, order detail) reads the
   same helper, `month_rule`, so an order opened by staff shows the figure
   her row shows. It was the second caller of `_order_commission`, and the
   full suite is what found it.

Nothing in `calculate.py`, payroll, snapshots, payments or the ledger
changed; the month's figure is still one numerator rounded once.

**Checks run.** Nine API tests in `tests/test_portal_api.py` with explicit
amounts (EGP 2,000 pending at 10% → EGP 200; delivered, unchanged, once;
failed → out of the month, EGP 200 struck through; refunded after delivery →
kept; July at 10% unchanged by September's 20%; no rate → not available;
zero base → `EGP 0.00`; pending-inclusive and delivered-only agreements,
the latter born through `approved_before_the_switch`). Four fail against the
old `EARNED`-only rule — checked. They replace
`test_no_figure_is_put_beside_an_order_that_earned_nothing`, which asserted the
retired rule. `test_reading_a_month_of_contents_costs_one_query` allows five
fixed queries, not four: the month's agreement is one more, once. Eleven
frontend tests in `CountingRule.test.tsx`. One API test in
`tests/test_orders_api.py` for the staff view of a pending order. Screens: `portal-orders-390`,
`portal-earnings-390` and `payment-detail` at 1280/1440 recaptured; new
`portal-orders-pending-390` pair and `payment-detail-estimate-1280`
(its `portal-orders-failed-390` is superseded by batch D's captures), from July with one failed order added to the
throwaway database.

## The current batch: D — Orders against the approved HTML (24 September)

The model's Orders, the admin profile's orders table and the order it opens,
compared with `Affiliate Portal v3.dc.html` (`onOrders`, `orderRows`) and
`Admin Dashboard.dc.html` (`mOrders`, `orderVals`). Batch C's commission
rules and snapshot handling are unchanged. Committed in two parts:
`6131d0c`, then the corrections below.

**What differed, and is fixed**

- *Model Orders.* The export's *Failed* filter; chips *Delivered* /
  *Pending* / *Failed delivery*; *no product lines available*; product lines
  with *Size M* and a price; the export's delivered sentence with the
  month's own rate and the server's base; the export's failed and cancelled
  sentences; the straight apostrophe. Local styling now matches the export's
  measured metrics: rows, chips and filters at the normal line height (rows
  were 106px against the export's 92px, now 95px - the rest is font
  metrics), the heading at weight 400, and no hover tint on a touch screen
  (it stuck on the opened row after a tap).
- *Admin profile table.* Status from the server, dates with the year, the
  whole row opens the order, amounts at the row's weight.
- *Net sales, everywhere an order shows it*, from an explicit fact
  (`net_sales_of`), never from a value being zero: `known` (a counted
  order's base - a real zero prints *EGP 0.00*; a failed delivery keeps its
  base), `placed` (a cancelled order's recorded placed-at total), or
  `unavailable` (zeroed and nothing recorded).
- *Admin order detail.* Status from the server; net sales as above; a void
  order's commission *EGP 0.00* (the export's); no rate *not available*;
  otherwise a dash. **Counts towards is decided on the server**
  (`counts_towards`) under the month's own rule and snapshot: *Counted in*,
  *Excluded from*, *Paid after delivery — {Month} was agreed on delivered
  orders only* for a pending order under an older delivered-only approval
  (whose commission is then a dash, not a figure), and *Failed after {Month}
  was approved — for review*. The cancelled note no longer says the amount is
  unavailable when net sales shows it. Back returns to the profile month.
- *The late-failure sentence is neutral.* `failed_after_approval` says only
  that the month's agreement counted an order that has since failed; it does
  not say a deduction was chosen, applied or settled anywhere, and no record
  says that of one order (05C corrections are per month). Her row: *"It
  failed after August 2026 was approved. The approved amount and any payment
  stay as recorded, and HBA reviews the difference."* The earlier wording,
  *"…so the difference is settled in a later month"*, claimed a treatment
  nothing had decided, and is withdrawn.

**One status, derived once** (`order_status`): earned is *delivered*
whatever came after (F04); pending is *pending*; a void order is *failed*
only if the courier failed, else *cancelled*, else *refunded* (in transit).

**Failed versus Not counted — decided.** The void bucket holds a failed
delivery, a cancellation and a refund while travelling; a refund after
delivery is not in it. The filter follows the export (which files its own
cancelled order under *Failed*); the one kept divergence is the chip, which
says *Cancelled* or *Refunded* where no courier failed.

**Kept, with the reason.** A cancelled order whose placed-at total survives
keeps it, struck through. The export's admin order view renders blank in the
served prototype, so the admin detail was compared against its markup and
`orderVals`.

**Visual differences still open — not sample data.** An earlier version of
this section said the remaining differences were only sample data. That was
wrong. Measured against the approved HTML at 390, 1280 and 1440:

| Where | Ours | Approved | Owner |
|---|---|---|---|
| Portal header identity | *HBA ambassador · …* truncated beside the month control | *HBA ambassador · HBA15* in full | **next shared-controls batch** |
| Portal month control | native `<select>`, *July 2026* | a compact *Nov ▾* button | **next shared-controls batch** |
| Admin model header | *Sara Edrees* alone | *Sara Edrees* with *SARAED* under it | **next shared-controls batch** |
| Portal Orders rows | 95px | 92px | font metrics; accepted |
| Prototype status bar | — | *9:41* and a battery | not app content; never reproduced |

Scrolling was checked in a real 390 × 844 touch viewport, not from a
full-page shot (which paints the fixed tab bar over whatever sits at that
height): at the end of the list the note ends at 744px and the bar starts at
788px, so nothing is hidden behind it.

**Checks run.** Backend: the 28 files that touch the changed code, 836 tests,
passing; then the full runner, 80 files and 2,069 tests, all passing. New tests:
net sales known-zero / placed / unavailable / failed-delivery (and a mutation
check - reverting to "zero means missing" fails it); *Counts towards* for a
pending order under the live rule and under a delivered-only approval, with
the amount beside it; the late-failure decision. Frontend: 391 tests, 18
files, and `npm run build`. Browser: every filter, every row opened, the
whole-row click and back link at 1280 and 1440, and the scroll check above.
Current pictures in `shots/app/`: `portal-orders-july-all-390`,
`portal-orders-delivered-open-390`, `portal-orders-july-scrolled-end-390`,
`portal-orders-august-late-failure-390`, `model-performance-july-{1280,1440}`,
`order-late-failure-{1280,1440}`, `order-cancelled-1280`, and the recaptured
`portal-orders-390` pair.

**Checklist**

- [x] Model Orders: filters, chips, rows, expansions, amounts, note, styling
- [x] Actual failed deliveries say *Failed delivery*; nothing else does
- [x] Delivered explanation with the real month, rate and amounts
- [x] Net sales from explicit facts: known zero, placed, unavailable
- [x] *Counts towards* decided on the server; amount and words agree
- [x] Late failure: neutral review wording; approved amount and payments stand
- [x] Admin profile table and order detail; navigation; mobile scrolling
- [x] Portal header identity, portal month control, admin header code —
      done in batch E
- [ ] The export's admin order view cannot be captured (prototype defect)
- [ ] The admin **Attributed orders** list (`vOrders`) was not compared

## Batch E — shared typography, identity headers and month controls (24 September)

Owner's scope, 24 September: typography, the model identity header at 390,
the admin profile header's code, and each screen's own month control.
**Implemented without stopping for approval, as instructed.** Full record,
mapping and evidence: the *Batch E* section at the end of
`docs/repair/batch-2/visual/CHECKLIST.md`; pictures in
`docs/repair/batch-2/visual/shots/batch-e/` (`compare/` is before · after ·
export); the capture script is `shared-controls.mjs` beside `review.mjs`.

- **Type.** The font was not the cause (identical Inter metrics, measured).
  The cause was our CSS: line height 1.5, tabular figures on every digit,
  headings at 600, `var(--font-heading)` misread as weight 500, the agreed
  figure at 500, controls inheriting 1.55, and no 700 face. ADR 0043 amends
  0039 and says what it costs.
- **Portal header.** Edge to edge, held at the top while the screen scrolls,
  the identity line wraps instead of truncating, the code in the line's own
  colour (tap still copies), and the export's *Sep ▼* control opening a list of
  her months with *in progress* / *approved* / *paid* / *settled* - derived
  from `/api/me/payments`, no new endpoint; no words if that read fails.
- **Admin.** `MonthPicker` is the export's *Month* + `<select>` (38px top bar,
  36px profile) over the platform's months (`start_month`, new in the session
  payload, to December of the working year). The profile shows the code under
  the name, 14px after Back, and writes its chosen month to the address so an
  order's Back returns to it (it did not before, grid or select).
- **Chart.** The *Inspect chart month* select under the portal chart, which
  the export does not have, is replaced by tap/keyboard columns, as the
  export's `hits`.
- **Kept, with reasons in the checklist:** controls stay in Inter where the
  prototype falls back to the browser's control font (Arial here, SF on an
  iPhone) - which is also the whole of the 95px vs 92px Orders row; the
  profile offers every platform month rather than only hers.
- **Not claimed:** the admin *Attributed orders* list is still unreviewed,
  and matching these controls says nothing about the rest of any screen.

## Not scheduled — a backlog, not an instruction

Each batch is named by the owner. These are known, decided by the export, and
**not** queued; nothing here is the next batch until he says so.

- The differences batch E found and left, listed with their locations at
  the end of `docs/repair/batch-2/visual/CHECKLIST.md` (*Still differs, not
  in this batch*), and the admin **Attributed orders** list, still unreviewed.
- The comment in `app/services/portal.py` saying a delivered-then-refunded
  order *"pays nothing"*; the code and tests already have it right.
- The small wordings: *Send a new link*, the absolute sent date, the size on
  the featured card, *met* / *not met* / *in progress*, the payment-details
  labels.
- *Refresh now* and *last successful refresh* on Settings → Shopify — held
  back by the owner's instruction of 24 September.
- The Appearance switches, the audit sentences, and recording a payment on
  its detail — each its own batch. The checklist's "conflicts" B–G are
  implementation work toward the export, not questions.

## Decisions not to reopen

- **Pending orders count.** `PENDING_INCLUSIVE` is the live policy, written
  into every snapshot approval agrees (`app/services/commission/calculate.py`
  names it *"the live counting rule"*; `payroll._payload` sets
  `body["policy"]`). **Two documents said the opposite and sat in the tree
  together for eight days**: the 16 September handoff's *"pending orders are
  not counted by the live rule"*, and `CLAUDE.md`'s *"05A is a read-only rules
  preview … the normal calculation and approval still need verified
  pending-inclusive activation."* Both described 05A's preview and were left
  behind when the code path moved. Both are removed; ADR 0040 is the rule.
- **The payer sees the whole destination** — ADR 0042, amending 0028, on the
  owner's explicit instruction. Masking still governs every *record*.
- **An agreed month is never unmade** (05B); a difference after approval is a
  correction (05C).
- **The month grid is for editing terms only** (`Compensation.tsx`). That is
  what the owner asked for, and the export agrees. Every other admin month
  control is the export's `<select>` (done in batch E), and the portal's is the
  export's *Nov ▼* button and list. An earlier version of this line said the
  grid was approved everywhere; it was not.
- **Type follows the exports, ADR 0043**: body 1.55, proportional figures
  except money/counts/ranks, one heading weight (the admin page title), no
  heavier agreed figure. It is not the font file - that was measured.
- **The reviewing browser is Playwright**, headless, in its own process. Not
  the Chrome extension, and not the window-resizing script.

## What I got wrong, so the next session does not repeat it

- **Changed a helper's signature and ran only the files I expected to use
  it.** `_order_commission` had a second caller in `app/api/orders.py`; the
  focused run missed it and the full runner caught it. Grep for callers
  before choosing the focused set.

- **Described code from its label.** The checklist said `best_sellers_for`
  was delivered-only because the subtitle said so; the function had counted
  pending for five days. Read the query before describing it.
- **Filed ordinary design differences as owner decisions.** The HTML decides
  unless a later explicit instruction conflicts with it.

- **Ran a second pytest against the test database while the suite was
  running**, twice. Both times it produced failures that looked exactly like
  regressions — `test_affiliates_api` reported six failures and passed alone
  minutes later. Use a second database (`hba_probe`) or wait.
- **Polled immediately after starting a background `sleep`**, which measures
  nothing, and concluded the suite had stalled when it was fine.
- **Wrote a digest that joined text nodes with a space**, which reported two
  differences that did not exist (`1 – 12 of 19` against `1–12 of 19`). It
  uses `innerText` now.
- **Collapsed two cases into one** when fixing the desk's empty-destination
  sentence: `destination_line` is null both when there is no destination and
  when the reader may not see one, and the first fix would have told marketing
  that a model with perfectly good details had none. Three tests hold the
  three cases apart now.
- **Invented rationale in code comments** — a claim about why the design uses
  `EGP` that was mine, not the design's. Trimmed to what is true.
