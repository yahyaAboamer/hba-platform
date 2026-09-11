# Batch report — Phase 07B, owner Home and product analytics

Date: 11 September 2026.

Branch and base/current commit: `phase07b/owner-home-and-analytics`, based on
`main` @ `418d0db`.

Requested scope: **07B.** Sales-ranked peers with permitted uses only;
discount-aware product analytics with stable ids; the owner's sales and pay
forecast breakdown, active count and top three; neutral content progress. Same
totals across list, detail and chart; no house or inactive-history mistakes and
no misleading partial-period growth labels.

Delivered behaviour: **the owner's Home answers A01**, and *what sells through
the codes* is a real figure for the first time — it could not be answered at
all until 07A started reading the contents of attributed orders.

The ranked-peers half of 07B shipped earlier with D03 and is merged.

---

## Review

### Where the money goes, and why the parts always add up

A01 asks for the expected payout **and** its parts: commissions, fixed
salaries, and what a guaranteed minimum added above what was sold.

A month's figure is exact until **one** half-up rounding (ADR 0003, 0004). So
the parts are **carved out of that rounded payout** rather than rounded
separately and added. Three components each rounding up would report a total a
pound away from the payroll screen — on the one screen whose job is to say how
much money to find, and the one comparison somebody will certainly make.

A property test asserts the three always sum to the payout, across all three
arrangements and four deliberately awkward figures.

**Nothing is summed in the browser.** The parts arrive computed and are
rendered. A breakdown assembled client-side would be a second implementation of
what a month is worth.

**A blocked month contributes nothing.** A figure that cannot be approved is
not money to find; it is a row to fix, and the two are counted separately.

### Top sellers, and the tie that would have been cut

The top three reuse the models' own board, so the owner and the models are
never told different things about who is ahead.

**Everybody in the first three places is shown, however many people that is.**
D03 shares a place and skips the next, so three level at the top are 1, 1, 1
and the next is 4. My first version took the first three *distinct* places and
would have shown ranks 1 and 4 — cutting one of three equals and picking a
winner the rule did not. It is `rank <= 3` now.

**A month nobody sold in has an empty board**, not a row of zeroes all sharing
first place. That is arithmetically true and says nothing.

### A bug found in code already shipped

**House accounts were never excluded from the ranking board.** A house code has
real sales and no payee (§8, §17), and it would have appeared on the models'
own leaderboard and taken a place from somebody. It shipped in the D03 batch
and this batch's tests caught it.

Filtered **in the query** rather than after it, so no future caller can forget.

### Content needing a look, split by why

A01 asks for content progress needing review. It is reported **by reason**, not
as one number: `nothing asked for yet`, `nothing recorded this week`, `behind`.

Two of those three are HBA's own work and only the last is about a model
(D08). Adding them together would produce a single accusing figure that is
mostly about whether somebody typed, and the screen says so in a line.

### What sells through the codes — W11

W11 is precise and rules out the easy version:

> Products selling through a code, wardrobe ownership and requested promotion
> are three different concepts. **A model can sell products they never
> received.** Top-seller analytics must use real attributed line items and
> discounts/quantities, not item name/undiscounted price sums.

So this reads `order_line_item` joined to attributed orders, and uses
**`discounted_total_piastres`** — what the customer actually paid after the
model's own discount. Summing list prices would credit the shop with money it
never took: on a ten per cent code, a ten per cent overstatement on every row.

**Grouped by product id, never by name.** A renamed product is the same
product and two products can share a name.

**A product deleted from Shopify has no id to group by.** It is reported as its
own figure rather than dropped, so this screen's total still reconciles with
the sales figures beside it — the prompt's *same totals across list, detail and
chart*.

**Counted orders only**, the same basis every other screen calls sales: a
pending order has not sold anything yet and a failed one never will.

### This was impossible a day ago

Product analytics needs line items on **commission** orders, and until 07A
those were never read — 03E fetched them only for parcels sent to models. The
two batches compose: 07A extended the read to attributed orders, and this turns
it into an answer.

**Older orders have no contents**, so the figures fill in from now on rather
than reaching backwards. Worth knowing before reading a thin August.

### What the owner should try

1. **Home → the month.** Active models, then *What makes up the payout* —
   commission, salaries, and what guarantees added above what was sold.
2. **Top sellers** on Home, and **Selling best through codes** on Products.
3. **Two models level on sales and uses** both appear in the top three, and the
   next place skips.
4. **Content needing a look** names why, and says which of those is ours.

### Approved-design deviations and reason

**None.** Every panel sits on a screen the design already has.

### Confirmation needed before the next dependent decision

**None.** D01, D02, D09 and D10 remain open; none blocks Phase 08.

---

## Engineering evidence

### Files changed

| File | Change |
|---|---|
| `app/services/overview.py` | **New.** The owner's month: breakdown, counts, top three, review reasons |
| `app/services/performance.py` | `top_products`; **house accounts excluded from the board** |
| `app/api/payroll.py` | `GET /api/payroll/{month}/summary` |
| `app/api/products.py` | `GET /api/products/top-sellers/{month}` |
| `frontend/src/screens/Overview.tsx`, `.css` | Active count, the breakdown, top sellers, content needing a look |
| `frontend/src/screens/Products.tsx`, `.css` | Selling best through codes |
| `tests/test_overview.py` | **New.** 19 |

**No migration.** Head unchanged at `1c4b06a5f8d2`. Everything is derived from
rows that already exist.

### Authorisation, idempotency and money

Both new routes are reads behind `affiliates.view`, take no identifier beyond a
month, and write nothing. **No money is computed in the browser**: the payout
parts arrive carved and are rendered.

The product figures are integer piastres throughout and use the discounted
total, so no screen can overstate what the shop took.

### Existing failures distinguished from regressions

**No regressions.** The full suite passed at **1858** before this half of the
batch; the guards and affected files pass throughout. The reachability guard
failed the moment `/summary` existed without a screen and passes now the
Overview calls it — that failing is it working.

### No real credentials or personal data in evidence

Every fixture is synthetic. Product titles are invented; no customer appears,
because the order index never stored one.

### Exact commands, actual results and environment

Windows, Git Bash, local PostgreSQL on 5433, migration head `1c4b06a5f8d2`,
one pytest process at a time.

| Check | Actual result |
|---|---|
| `tests/test_overview.py` | **19 passed**, exit 0 |
| `tests/test_performance.py` | **36 passed**, exit 0 |
| `tests/test_payroll_lifecycle.py` | **48 passed**, exit 0 |
| `tests/test_reachability.py` | **3 passed**, exit 0 |
| Full backend suite | **1864 passed in 210.74s**, exit 0 — 1858 before this half, **6 new** |
| `cd frontend && npm test` | **256 passed**, exit 0 |
| `cd frontend && npx tsc --noEmit` | exit 0 |
| `cd frontend && npm run build` | exit 0 |

### Visual comparison — not performed

Automation cannot sign in. The owner's new panels and the top-sellers list have
not been seen.

---

## Continuation

### Remaining limitations

- **Product figures start from 07A.** Orders indexed before the contents read
  was extended have no line items, so a month before that reads thin. A resync
  fills it in.
- **`month_summary` runs one calculation per model**, which is what the
  payroll screen already costs for the same list. Not free, not duplicated, and
  pinned by nothing — if the Home ever feels slow, that is the first place to
  look.
- **No growth labels anywhere.** The prompt warns against misleading
  partial-period growth, and the safest way to honour that was to show no
  period-over-period figure at all rather than one carefully worded.

### Decisions recorded

**None new.**

### Exact next batch and prompt

**Phase 08 — settings and notifications.**
`docs/redesign/prompts/08_SETTINGS_AND_NOTICES.md`.

### Live deployment or data changes

**None in this batch.** `main` is at `418d0db` with 07A merged and staging
deployed; production was promoted by the owner earlier today and is healthy.
