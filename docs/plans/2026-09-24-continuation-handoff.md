# Where the work is — 24 September 2026

**Replaces `2026-09-16-exact-design-handoff.md`** and every handoff before it.
Those are kept, with a banner at the top saying what in them is no longer
true. Nothing was deleted.

## The exact position

| | |
|---|---|
| **Branch** | `repair/batch-2` |
| **Revision reviewed** | The sweep describes `f83b4fc` — *Every screen at both widths, and 390 at last*. **One code change since**: the best-sellers commit on top of `ffde978` (*Best sellers say what they count*), which touches `app/api/affiliate_self.py`, `frontend/src/screens/MyWardrobe.tsx` and tests, and recaptures `portal-wardrobe-390` plus a new `portal-best-390`. **And a second**, batch C on top of `4077b88` — earnings explanations and per-order commission, below. |
| **Current head** | run `git rev-parse --short HEAD`. Not written here: a document cannot contain the hash of the commit that adds it, and the last attempt was stale one commit later. |
| **Tree** | clean apart from `.claude/settings.json`, the owner's plugin config, deliberately not committed |
| **`origin/main`** | `6a13958` |
| **`origin/production`** | `6a13958` — **level with `main`**, gap of 0 commits, read from `git ls-remote` on 24 September |
| **Backend** | 2,054 tests, 80 files, all passing through `run-suite.sh` on 24 September, after batch C; matches `--collect-only` |
| **Frontend** | 378 tests, 17 files; `npm run build` green (24 September, after batch C) |
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

## The current batch: earnings explanations and per-order commission (24 September)

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
`portal-orders-pending-390` pair, `portal-orders-failed-390` and
`payment-detail-estimate-1280`, from July with one failed order added to the
throwaway database.

## Not scheduled — a backlog, not an instruction

Each batch is named by the owner. These are known, decided by the export, and
**not** queued; nothing here is the next batch until he says so.

- The month grid back to the export's `<select>` everywhere except
  `Compensation.tsx`'s terms editing.
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
  what the owner asked for, and the export agrees. Every other month control
  follows the export's `<select>` — item A above. An earlier version of this
  line said the grid was approved everywhere; it was not.
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
