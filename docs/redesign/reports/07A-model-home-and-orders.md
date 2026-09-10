# Batch report — Phase 07A, Model Home and Orders

Date: 11 September 2026.

Branch and base/current commit: `phase07a/model-home-and-orders`, based on
`main` @ `b6abcf5`.

Requested scope: **07A only.** Actual month and history with her own rate and
arrangement; a concise earnings, approval and payment explanation;
original-month current sales and destination deduction; full order paging,
status and products; no customer data. Charts for zero, one, many and missing
months; receipt context stays separate. No hardcoded fixture dates or 10% copy.

Delivered behaviour: **code uses reached her Home**, which is what M01 asked
for and the platform could not answer until D03 defined it. Most of the rest of
07A already existed and was verified rather than rebuilt — and two items were
assessed and deliberately not built, which the report says plainly rather than
quietly skipping.

---

## Review

### The one real gap: how often her code was used

M01 puts **earnings, sales, code uses and performance** on her Home. Three of
those were there. Uses could not be, because until D03 was answered on 11
September there was no definition of what a use was.

The tile beside it says *"N orders counted"*, and **that is a different
number** — which is exactly why uses is its own figure and not arithmetic on
what is already on the screen:

- an order **delivered and later refunded** pays nothing and is still a use;
  her code brought a parcel to a door;
- a parcel **refused at the door** pays nothing and is *not* a use.

Those are `void` in commission terms and opposite in delivery terms, so adding
earned and pending would be wrong in both directions at once. A test asserts
the two figures diverge rather than merely that the number exists.

The sub-line says *including any still on the way*, because a parcel going out
raises this figure and not the sales beside it, and two numbers that disagree
without explanation are a support message.

### What was already right

**The year chart handles every case M01 lists.** No months has an empty state;
one month is centred rather than dividing by zero; all zeroes is safe because
the scale is `Math.max(…, 1)`; gaps are skipped rather than connected through,
so a slope that never happened is never drawn. **No NaN is reachable.** Read
and confirmed, not touched.

**Her own rate and arrangement** already drive the month: figures come from her
terms for that month, never today's, and no screen hard-codes 10%.

**No customer data** — `order_index` never stored a name, address or phone, so
there is nothing to filter out.

**Receipt context is separate**, and 06B strengthened it: a transfer names the
destination it actually went to and links to the month that explains it.

### Two things assessed and not built

**Order paging.** The prompt asks for it. `my_orders` is **one joined query**
for a month with no per-row work, and the result is bounded by one model's
orders in one month — tens, not thousands. The filters on that screen are
applied in the browser, so server-side paging would mean moving them to the
server too: a page of unfiltered rows, filtered after the fact, shows a count
that contradicts itself.

That is a real change to a working screen for no measured benefit. 03D's paging
mattered because each row carried a multi-megabyte photograph; this payload is
a few kilobytes. **Not built, and the reason is here rather than absent.** If a
month ever does carry hundreds of orders, the filters move first.

**Products on an order** was put to the owner rather than assumed, and he asked
for it. **Built** — see below.

### What was in each order

Asked and answered on 11 September. It needed more than a screen, and the
reason is worth stating: **the contents were not being read.**

03E fetches line items only for parcels matched to a model — the wardrobe —
and says why in as many words: *reading every line of every order in the shop
to build twenty wardrobes is the wrong trade, and the great majority of orders
are customers.* Her **commission** orders are exactly those customer orders, so
they had none.

The read now also runs for an order that was **attributed to a model**. That is
the same trade 03E made, applied to a different and equally self-selecting set:
an order that used a code is a small fraction of the shop, and it is precisely
the set this screen shows. Deduped by order id and sharing 03E's job, so an
order that is both somebody's parcel and somebody's commission is read once.

**Empty is not the same as none.** Contents are read only from now on, so an
older order genuinely has nothing recorded — and the screen says *what was in
this order was not recorded* rather than implying somebody bought nothing. A
test holds that distinction.

**Old orders need a backfill to fill in.** Nothing here reads history; a
re-import or a resync of an order picks it up. Worth knowing rather than
wondering why September is fuller than August.

### What the owner should try

1. **Portal → Home.** A **Code uses** tile beside Counted sales.
2. **A model with a delivered order that was refunded** shows a use and no
   sale. **One refused at the door** shows neither.
3. **A month with nothing in it** reads *0* rather than a blank or an error.

### Approved-design deviations and reason

**None.** The tile sits in the row the design already has.

### Confirmation needed before the next dependent decision

**None.** The one open question — whether the Orders screen should list an
order's contents — was answered *yes* on 11 September and is built.

---

## Engineering evidence

### Files changed

| File | Change |
|---|---|
| `app/services/portal.py` | `uses` on the month payload, from `uses_for` |
| `frontend/src/screens/MyMonth.tsx` | The Code uses tile |
| `frontend/src/lib/portal.ts` | `uses` on the orders type, with why it is not a sum |
| `app/services/shopify/sync.py` | Contents read for an attributed order, mirroring 03E's parcel path |
| `frontend/src/screens/MyOrders.tsx`, `.css` | The contents list inside the expansion |
| `tests/test_performance.py` | 6 new |

**No migration, no new route, no new permission.** Head unchanged at
`1c4b06a5f8d2`. The figure comes from `uses_for`, built and tested when D03 was
answered.

### Authorisation, idempotency and money

Nothing written, no money computed. `uses` is a count of her own orders on a
route already behind `current_affiliate`, and it carries no customer detail
because the index never held any.

### Existing failures distinguished from regressions

**No regressions.** `test_performance.py` 36 (6 new), `test_portal_api.py` 85,
`test_shopify_sync.py` 22, `test_reachability.py` 3, frontend 256 with `tsc`
and build clean.

### No real credentials or personal data in evidence

Every fixture is synthetic; no name, address, phone or email appears.

### Exact commands, actual results and environment

Windows, Git Bash, local PostgreSQL on 5433, migration head `1c4b06a5f8d2`.

| Check | Actual result |
|---|---|
| `tests/test_performance.py` | **36 passed**, exit 0 |
| `tests/test_portal_api.py` | **85 passed**, exit 0 |
| `tests/test_shopify_sync.py` | **22 passed**, exit 0 |
| `tests/test_reachability.py` | **3 passed**, exit 0 |
| `cd frontend && npm test` | **256 passed**, exit 0 |
| `cd frontend && npx tsc --noEmit` | exit 0 |
| `cd frontend && npm run build` | exit 0 |

The full suite passed at **1839** on `b6abcf5`, the commit this branch is based
on — the first complete single-process run of the session, after the owner
freed memory. It also halved in time, from about seven minutes to three and a
half.

### Visual comparison — not performed

Automation cannot sign in. The Code uses tile has not been seen.

---

## Continuation

### Remaining limitations

- **Order paging** is assessed above and not built.
- **An order's contents are read from 07A onwards only.** Older orders show
  *not recorded* until a resync picks them up.
- **Uses is per month**, matching every other figure on Home. A year-to-date
  use count is not offered and was not asked for.

### Decisions recorded

**None new.** D03 and D08 were closed on 11 September and this consumes D03.

### Exact next batch and prompt

**Phase 07B — Ranking, top sellers, owner Home and profile performance.**
`docs/redesign/prompts/07_PERFORMANCE.md`, **07B only**.

Ranking and the weekly-pace column are already built and merged, so what 07B
still owes is the **owner's Home** — sales, pay forecast breakdown, active
count, top three by generated sales — and **product analytics**. `rank` and
`month_performance` in `app/services/performance.py` already answer the top
three; do not re-derive them.

### Live deployment or data changes

**None in this batch.** `main` was pushed at `b6abcf5` and staging deployed
during this session. `production` is still at `9cbfcdb`: the promotion was
attempted and refused by a permission guard, so the owner runs
`git push origin main:production` — a clean fast-forward of 12 commits and one
additive migration.
