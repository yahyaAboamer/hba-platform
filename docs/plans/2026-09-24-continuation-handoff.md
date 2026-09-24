# Where the work is — 24 September 2026

**Replaces `2026-09-16-exact-design-handoff.md`** and every handoff before it.
Those are kept, with a banner at the top saying what in them is no longer
true. Nothing was deleted.

## The exact position

| | |
|---|---|
| **Branch** | `repair/batch-2` |
| **Revision reviewed** | The sweep describes `f83b4fc` — *Every screen at both widths, and 390 at last*. **One code change since**: the best-sellers commit on top of `ffde978` (*Best sellers say what they count*), which touches `app/api/affiliate_self.py`, `frontend/src/screens/MyWardrobe.tsx` and tests, and recaptures `portal-wardrobe-390` plus a new `portal-best-390`. |
| **Current head** | run `git rev-parse --short HEAD`. Not written here: a document cannot contain the hash of the commit that adds it, and the last attempt was stale one commit later. |
| **Tree** | clean apart from `.claude/settings.json`, the owner's plugin config, deliberately not committed |
| **`origin/main`** | `6a13958` |
| **`origin/production`** | `6a13958` — **level with `main`**, gap of 0 commits, read from `git ls-remote` on 24 September |
| **Backend** | 2,045 tests, 80 files, all passing through `run-suite.sh` on 24 September, after the best-sellers change (was 2,039 / 79) |
| **Frontend** | 365 tests, 16 files; `npm run build` green (24 September, after the best-sellers change) |
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

### Still delivered-only, found while checking — not fixed in that batch

1. **My Calculation's rule line** (`frontend/src/screens/MyCalculation.tsx`,
   the `portal-calc__rule` paragraph): *"… of net sales on delivered orders.
   An order on its way counts the day it arrives"*. The export (line 509 of
   the portal): *"Commission is 10% of net sales on delivered and pending
   orders. Failed deliveries are excluded."* Its source comment still calls
   pending *05A's preview*.
2. **Payment detail's counted-sales line** (`PaymentDetail.tsx`, the
   *Counted sales* `StatementLine`): *"Delivered orders. Failed deliveries
   excluded."* for a month not yet approved, whose figure includes pending.
3. **Her orders list gives a pending order no commission**:
   `app/services/portal.py`, the per-order worked example returns `None`
   unless the state is `EARNED`, so the row prints *—* for an order the month
   is paying on. Needs checking against the export's orders rows before it
   is changed; it is a money display.

## The next small implementation batch, proposed

Everything below is already decided — by the approved export or by an explicit
instruction from you — so it is work, not a question. Nothing here changes a
business rule and nothing needs a new ADR. It is deliberately small.

**A. Take the month grid back off the seven screens it was never asked for.**
`MonthPicker` returns to the export's `<select>`; `Compensation.tsx`'s terms
grid is not touched. Home, Orders, Overview, Payments, Payroll, Settings,
Targets and the model profile all follow from the one component.

**B. Fix the comment that contradicts the refund rule.**
`app/services/portal.py:756` says a delivered-then-refunded order *"pays
nothing"*. It is a comment; the code and four tests already have it right.

**C. The five small wordings the export decides.** Expired invitation reads
*Send a new link*; the sent date is absolute; the featured card carries the
size; the portal targets use *met* / *not met* / *in progress*; the portal
payment-details form uses the export's three labels.

**D. Build *Refresh now* on Settings → Shopify and sync**, and report *last
successful refresh* rather than *last order arrived*. The read-only connection
card stays — see conflict B in the checklist.

**E. The three delivered-only sites above.** Wording for the first two; the
third after comparing with the export.

Held back deliberately, and why: the Appearance switches and the audit
sentences (items 1 and 2) are each a day's work with persistence behind them
and belong in their own batch; recording a payment moving onto the detail
(item 11) is a route change. The checklist's "conflicts" B–G are
**implementation work toward the export** under the rule above, not
questions; *Refresh now* and connection editing (B) are held back by the
owner's instruction of 24 September, not by a pending decision.

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
