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

## A06, A08, A09, A11, A12

Not started.
