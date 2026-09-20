# Batch 2 — data contracts and history

Branch `repair/batch-2`, cut from `repair/batch-1-financial-rules` at
`723022e` rather than from `main`, so every financial fix from Batch 1 and its
two reviews is underneath this work. `main` and `production` are untouched.

The audit sequences this batch as **A02, A06, A08, A09, A11, A12**: the
API-to-view meanings, eligible-month assignment, and the missing product and
receipt data contracts.

**The approved HTML design is the reference, not a starting point.** Where a
figure was bound to the wrong field, the repair is to bind the right one —
not to redraw the screen around it. Each section below names the export it was
checked against.

---

## A02 — the Payments table displayed the wrong amount

> Staging example: Boda showed **E£0.00 in the list**, while opening the same
> month's detail showed an **estimated E£14,224**.

### What it was

`PaymentRow` rendered `row.balance_piastres` for every row, whatever kind of
row it was. That field is *what is left to send*, and the server sets it to
**zero on any month nobody has approved** — deliberately, because an
unapproved month has no agreed figure and presenting one as a debt is the
thing F14 exists to prevent. So every forecast row showed E£0.00 while the
figure it should have shown was already on the wire beside it.

The same zero came back at the other end of a month's life. A fully paid month
has nothing left to send, so a settled row also showed E£0.00 where the export
shows what the month came to with the recorded transfer under it.

**Every number involved was correct and already in the response.** The column
was bound to the wrong one.

### What the design actually specifies

From the approved export (`docs/redesign/designs/Admin Dashboard.dc.html`,
`paymentsVals` → `payRows`):

```js
amount:   this.egp(r.pay.total),
hasPaid:  r.paid > 0 || r.pay.remainderCarried > 0,
paidLine: r.pay.remainderCarried > 0
            ? this.egp(r.pay.remainderCarried) + " deduction outstanding"
            : this.egp(r.paid) + " recorded",
```

and `pay.total` is `max(ent.total - applied, 0)` — the month's entitlement
less any deduction landing on it, where `ent` comes from the snapshot when the
month is approved and from the live calculation when it is not.

So the export's headline is **the month's transfer before payments**, on both
sides of the approval line, with one line under it for whichever of the two
facts applies.

### What it does now

The row renders `required_piastres`, which the server already computed as
exactly that figure — and which the page's own *Funds required* total already
adds up, so the row and the header now agree rather than disagreeing silently.

The second line follows the export: the deduction where there is one, the
recorded transfer otherwise, and nothing at all where neither applies.

**This is not "replace every zero with a forecast".** A month with no sales
still reads zero; so does a month settled outside the platform; so does D04's
valid no-transfer month — which now says *E£2,000.00 deducted* underneath,
because a correct zero with no explanation is indistinguishable from a broken
one.

### The half of it that was on the server

The forecast branch of `_render_balance` reported the **gross** forecast as
`required_piastres`, while the approved branch netted out any deduction
landing on the month. A carry is accepted against a month *before* it is
agreed (F07, F12), so a draft month can already be carrying one — and the
column therefore meant two different things depending on a state the reader
cannot see, which is A02 restated.

`required_piastres` is now the transfer on both sides.
`forecast_piastres` stays gross and keeps answering the other question — *what
is this month worth* — which is what the detail screen and the header's
estimate ask.

### Evidence

Seven rendered-table tests in `frontend/src/screens/__tests__/Payments.test.tsx`,
built from the server's own response shape and rendered through the real
`PaymentRow`, covering every case the audit named: forecast, unavailable,
approved-and-unpaid, partly paid, fully paid, the correction-covered zero, and
a month settled outside the platform.

They assert the **headline and the second line separately**, which matters:
asserting against the whole cell is how the bug passes a test. A settled row
rendering `balance_piastres` shows E£0.00 as its figure and E£2,000.00 on its
second line, and "is E£2,000.00 somewhere in this markup" is satisfied by the
defect.

Rebound to `balance_piastres`, three fail — the forecast row, the part-paid
row and the settled row, which are the three symptoms the audit described.

One backend test,
`test_a_forecast_month_reports_the_transfer_not_the_gross_earnings`, covers the
server half: September earning E£3,000 with E£2,000 of August landing on it
reports a forecast of E£3,000, a deduction of E£2,000 and a required transfer
of E£1,000.

**Results:** frontend `tsc` clean, **328** tests passing, build green; backend
`tests/test_payments_api.py` 43 passing.

**Not verified in a browser.** The audit confirmed this one on staging, and
nothing here has been rendered against the export at 1280 and 1440 the way
CLAUDE.md asks for. That check is outstanding for this batch.

---

## A06 — the terms editor started at the first sale, not the start

### What it was

Two defects behind one field.

`_pay_history_payload` returned `joined_month` as `min(sold_in)` — the first
month she **sold** in — and the editor used it as the first selectable month,
falling back to the working month for a model who had never sold.

For every model signed before she made a sale those are different months, and
the gap between them is exactly where a salary belongs: there are no
commissions in those months to stand in for one. A model who joined in January
and first sold in March could not be given January or February pay at all. The
grid did not offer them.

Underneath that, a preservation risk the success message denied. `PUT
/pay-history` **replaces** a model's whole history, so a period left out of the
request is a period deleted — and the screen built its request from the months
at or after its start month. Anything recorded before them was dropped, while
the message afterwards read *unselected months are unchanged*. True of
unselected months inside the slice; false of everything before it.

### What it does now

The server answers **which months are hers to arrange**, as
`arrangeable_from`: her recorded collaboration start, floored at the
platform's first month, falling back to the first sale and then to the working
month so a model with neither still gets a grid rather than an empty one.

Decided on the server rather than in the browser for the reason the money
rules already are: a rule with two implementations is a rule with two answers.
`joined_month` stays exactly as it was and keeps meaning what it says.

The editor sends its **whole month list** to the replacement route, not the
arrangeable slice. `fromServer` already reads every month the server sent, so
the months before the start month are re-stated exactly as they were and
survive the replace.

### Evidence

Six route tests in `tests/test_affiliates_api.py`: joined-January
first-sold-March, a model who has never sold, a recorded start before the
platform existed, no recorded start at all, the January/February commission
into March/April salary case with a zero-sales month inside a run, and the
preservation case.

The last one asserts in **both** directions — sending the whole history keeps
it, sending half of it does not — so the route's replace-don't-merge behaviour
is written down rather than left as something the screen has to remember.

Three library tests in `frontend/src/lib/__tests__/payHistory.test.ts` hold the
reason the screen passes its whole list, including that a zero-sales month
stays inside a run rather than splitting it.

**Results:** frontend `tsc` clean, **331** tests, build green; backend
`test_affiliates_api.py` 113, `test_compensation.py` 55,
`test_browser_journey.py` 10.

**Not verified in a browser.** Same gap as A02.

---

## A08 — the Uses chart had no field to read

### What it was

Model Home showed **37 uses**. Selecting *Uses* on the chart beside it showed
*Not available · this history is not available yet*.

Neither was broken. `PortalYearChart` reads `row.uses`; `my_year` returned
`orders` and no `uses` at all, and `ChartMonth` declared the field
**optional** — so nothing in the type system, the tests or the build had
anything to object to. The chart had a metric with no field behind it.

### What it does now

`my_year` carries `uses`, taken from the month card's own figure rather than
computed a second way. The historical branch of `my_month` carries it too: her
code uses are a fact about her orders, and her orders are in the index either
side of go-live — only the commission was agreed elsewhere (ADR 0014). That
branch was returning "—" for a month it could answer perfectly well.

`ChartMonth.uses` is now **required**. `null` still means genuinely unknown
and still draws *Not available*; what it can no longer mean is that nobody
wired it up.

### Not the order count renamed

The audit was explicit about this and it is the part worth stating. A **use**
is a delivery outcome (D03): every attributed order except one whose delivery
failed, including an order the courier has not answered for yet. The three
counts beside it are **commission** states.

So they part company in both directions. An order delivered and later refunded
is a use and pays nothing. A parcel refused at the door is neither. Aliasing
one to the other would have drawn a chart that disagreed with the card above
it.

### Evidence

Four route tests in `tests/test_portal_api.py`: the year and the card
reporting the same figure, pending-and-delivered counting while a refused
parcel does not, the delivered-and-refunded order that is a use and not a
counted order, and a quiet month reporting zero rather than nothing.

One existing test was corrected rather than deleted:
`test_a_historical_month_counts_its_orders_the_same_way` now expects `uses` in
that shape, with the reasoning written in — all three of its orders are uses
because their delivery is unresolved, while only two are counted orders, and
that divergence is the distinction working.

**Results:** frontend `tsc` clean, **331** tests, build green; backend
`test_portal_api.py` 93, `test_earnings_api.py` 24, `test_performance.py` 36.

**Not verified in a browser.** Same gap as A02 and A06.

---

## A11 — a receipt could be labelled with a month it did not pay

### What it was

`PaymentReceipt` finds the transfer by id, looks for an allocation matching
the month in the URL, and fell back to the transfer's **whole amount** when
that allocation was missing — while still titling the page with the month from
the URL:

```tsx
<Money piastres={here?.allocated_piastres ?? transfer.amount_piastres} />
```

So a stale bookmark, a mistyped month or a link copied from the wrong row
produced a page that looked exactly like a genuine receipt and said this
transfer paid for a month it had nothing to do with. Nothing on it disagreed,
because every fact on it was true except the one the heading implied.

§14 allows one transfer to cover two months, so *which part of this settled
this month* is a real question with a real answer — and the answer is
sometimes **none of it**.

### What it does now

`receiptFor` returns which of three situations this is, because there are
three and the old code had one answer for all of them:

- **settled** — there is an allocation for this month, and the receipt shows
  that part, not the transfer's total.
- **unassigned** — the transfer has no allocations at all. An ordinary state,
  not an error: §14 lets money be recorded before anybody decides which months
  it covers. It is shown, and it is not claimed for this month.
- **elsewhere** — the transfer is allocated, to other months. The page says
  so, names them, and links to one, so a wrong link is a wrong turning rather
  than a dead end.

### Evidence

Five tests in `frontend/src/screens/__tests__/PaymentReceipt.test.tsx`,
including the multi-allocation history the audit asked for: one transfer
covering August and September shows the August part for August and refuses
July outright.

One of them is there for a trap rather than a symptom — a recorded allocation
of **zero** is a decision somebody made, and must not be read as a missing
one. `??` on a number is how that goes wrong, and it is what this replaced.

No new multi-month payment-creation workflow was added, as the audit asked.

**Results:** frontend `tsc` clean, **338** tests, build green.

**Not verified in a browser**, and the audit did not reproduce it by URL
either. Same gap as the sections above.

---

## A12 — wording that stated things the screen could not know

Three places turned a request that never answered into a fact about her money.

### The calculation said "approved" when it could not reach the ledger

`MyCalculation` fetched the settlement separately and swallowed a failure into
`setPayments(null)`. `homeState` then saw no settlement and returned
**approved** — *agreed and not yet paid* — which is a statement about her
money produced by a network error.

`homeState` now takes whether the settlement was actually read.
`settlement === undefined` had two completely different causes — *the ledger
has nothing for this month* and *the request failed* — and the second was
silently read as the first. The parameter defaults to `true`, so every
existing caller keeps its meaning.

A month that never needed the ledger is untouched: an open month and a
pre-platform month are decided by the earnings read alone, so a broken
settlement request costs them nothing.

### The wardrobe turned a failed read into "no sales"

`.catch(() => setBest([]))`. An empty list hides the section — exactly as it
does for a model who genuinely has sold nothing. The two were indistinguishable
on the screen least able to tell them apart.

Now three states: `null` with no error is *still loading*, `[]` is *genuinely
none*, and an error says so and offers another go. One short sentence, not a
paragraph.

### "Nothing has been paid yet" was not this screen's to say

`MyPayments` reads the platform's ledger, which **begins at go-live** — and
HBA paid models before it existed (ADR 0036). An empty ledger means there is
no record *here*. It now says that.

### Evidence

Seven tests in `frontend/src/screens/__tests__/UnknownStates.test.tsx`: the
unknown settlement against the genuine empty one, a recorded payment still
reported, open and historical months unaffected by a failed ledger read, and
the wardrobe's three states rendered apart — failed, genuinely empty, and
still loading.

**Honest limit.** The audit asked for these to be driven by *actual rejected
API requests*. This project has no DOM test environment — no `jsdom`, no
`@testing-library/react` — so a component's effect cannot be run in a test at
all, and adding both was scope this batch did not have. What is tested instead
is the seam the defect lived in: the decision functions and the render props,
with the failure and the emptiness passed in as the distinct values they now
are. The swallow itself is gone from the source, but nothing yet re-runs a
rejected fetch through the component.

**Results:** frontend **347** tests, build green; backend `test_portal_api.py`
93, `test_wardrobe.py` 34.

### One thing this turned up about the checks themselves

`npx tsc --noEmit` **checks nothing**. The root `tsconfig.json` is a solution
file containing only `references`, so bare `tsc` compiles no files and exits 0
whatever is broken — it passed a JSX syntax error and an import of a type that
does not exist, both of which `npm run build` (`tsc -b`) caught immediately.
Recorded in CLAUDE.md, because a green typecheck has been quoted as evidence
in this repair more than once.

---

## A09 — historical readiness compared two dates

A09 asks for several things, and they are not all code. This section does the
code half and says plainly what the other half still needs.

### The code defect: "Covered from the start" proved nothing of the kind

Settings' *Historical setup* column decided readiness like this:

```tsx
if (row.earliest_terms_month > row.collaboration_start_month) return "Months before her terms";
return "Covered from the start";
```

Two dates. That answers *do her terms begin early enough* and nothing else:

- **A gap in the middle passes.** Terms from January to March and from June
  onwards, starting in January, reads *Covered from the start* while April and
  May cannot be calculated at all.
- **A guaranteed month with no recorded outcome passes.** It blocks the figure
  exactly as completely as missing terms (F06), and this column could not see
  it.
- **"Start month not recorded" was reported as a verdict.** It is a real fact
  and worth showing (H01), but a model whose start nobody wrote down still has
  eligible months derived from her orders and can be perfectly ready across
  every one of them.

H06 is explicit that a first terms record does not prove readiness. Neither
does an early one.

### What it does now

The roster carries `historical_setup`: how many of her eligible months are
ready, how many are blocking, and the first month that cannot be calculated.
The column says *"All 9 months ready"* or *"2 of 9 months cannot be
calculated"*, and the fix link goes to the first gap rather than the top of
the grid.

**One rule, in one place.** The per-month decision was pulled out of
`setup_readiness` into `month_gaps`, and both the profile screen's payload and
the new roster summary call it. The column having its own rule is how A09
happened.

`roster_readiness` answers for the whole roster in four queries rather than
three per model — the loop this file already warns about (03D).

### Evidence

Five tests in `tests/test_setup_readiness.py`: the gap in the middle that the
two-date comparison called covered, a guaranteed month with no outcome, the
fully covered case, a model with no recorded start judged on her orders, and
the whole roster answered in one pass.

### What A09 still needs, and it is not code

The audit asks for verified start dates, terms and guarantee outcomes to be
**populated**, order completeness **verified**, and historical reconstruction
**finalised idempotently**. None of that is a code change and none of it has
been done:

- No real or restored data has been touched. The staging gaps the audit found
  — Jana starting January with terms from August, other profiles with no
  recorded start — are still there.
- Order completeness has not been verified against Shopify.
- There is no historical finalisation step, idempotent or otherwise. The
  column now measures readiness honestly, which is what makes the remaining
  work visible rather than what completes it.
- The approved bulk historical review entry is still absent.

A06 was its stated prerequisite and is done.

**Results:** frontend **347** tests, build green; backend
`test_setup_readiness.py` 19, `test_affiliates_api.py` 113.
