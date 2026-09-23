# Visual and interaction review — the checklist

One row per screen, at every width it was reviewed at. Every row has a pair of
screenshots in `shots/` named `<screen>-<width>.png`, one under `app/` and one
under `export/`, and a `.json` digest beside each.

**Matched** — nothing differs but the data.
**Corrected** — differed, and the difference is fixed on this branch.
**Still differs** — real, described below, waiting on a decision.
**Not exercised** — the screen renders but the seeded data does not put it in
the state the export shows, so the comparison would be about the fixture.

The data itself cannot match on one point and it is worth saying once:
**the export is set in November 2026 and the platform runs on the real clock**,
so every pair reads "September" against "November". Each model's start month is
shifted to stand the same distance from the working month as her counterpart.

---

## Admin — 1280 and 1440

| Screen | 1280 | 1440 | Notes |
|---|---|---|---|
| Home | Corrected | Corrected | Currency; the missing *applications awaiting review* notice |
| Models · Active | Corrected | Corrected | Subtitle, terms cell, pager suffix |
| Models · Applications | Matched | Matched | |
| Models · Invitations | Matched | Matched | Empty in this data; the export's fixture has three |
| Models · Inactive | Matched | Matched | |
| Model · Overview | Matched | Matched | Same five tabs, same three summary cards |
| Model · Wardrobe | Not exercised | Not exercised | Nothing shipped in the seed; the panel says so correctly |
| Model · Performance | Matched | Matched | Same columns in the same order |
| Model · Targets | Matched | Matched | Same columns; state words differ, below |
| Model · Payments | Corrected | Corrected | **Was masking the destination**; now the full card |
| Products · Active | Matched | Matched | |
| Products · All products | Matched | Matched | |
| Products · Active requests | Not exercised | Not exercised | No feature request seeded |
| Targets | Still differs | Still differs | State vocabulary, below |
| Payments (working month) | Corrected | Corrected | Applications and not-yet-started models removed |
| Payments · previous month | Corrected | Corrected | |
| Payments · Approved | Corrected | Corrected | |
| Payments · Partly paid | Corrected | Corrected | |
| Payments · Fully paid | Corrected | Corrected | |
| Payments · No transfer due | Corrected | Corrected | Empty-filter sentence |
| Payment detail | Corrected | Corrected | Missing-destination title and sentence |
| Record payment | Still differs | Still differs | A screen of its own, not a panel on the detail — below |
| Settings · Team | Matched | Matched | |
| Settings · Shopify and sync | Not exercised | Not exercised | Nothing connected in this environment |
| Settings · Historical setup | Matched | Matched | Plus the lock panel, which the export has no state for |
| Settings · Brand codes | Corrected | Corrected | Button word and the note's missing clause |
| Settings · Appearance | Still differs | Still differs | Two switches missing, below |
| Settings · Reference | Still differs | Still differs | Audit rows read as event names, below |
| Popup · account menu | Still differs | Still differs | Two extra entries, below |
| Popup · invite a model | Corrected | Corrected | Title and subtitle |

## Model portal — 390

| Screen | 390 | Notes |
|---|---|---|
| Home | Matched | |
| Orders | Corrected | Filter and chip words; *products* not *pieces* |
| Wardrobe | Not exercised | No featured products seeded |
| Targets | Still differs | State vocabulary, below |
| Ranking | Still differs | Other models are anonymised, below |
| You | Corrected | The export's row order and its words |
| Payments | Corrected | Screen title; receipts differ, below |
| Payment details | Still differs | Form wording, below |
| Earnings | Still differs | Line names, below |
| Month picker | Cannot be captured | Native `<select>`; the list is drawn by the OS |

---

## Corrected on this branch

**Currency, everywhere.** `E£1,062.00` → `EGP 1,062.00`, the export's `egp()`
character for character, including the space and the U+2212 minus. Both
formatters changed (`app/core/money.py`, `frontend/src/lib/money.ts`) and a
test now holds them to the same examples, plus the three input labels that
carried the sign in their own text.

**Home had no *applications awaiting review* notice.** The export's first
notice, and the app had no such notice at all: two people who applied through
an invitation link were waiting, and nothing on Home said so. Added with the
export's words and its *Open applications* action.

**The payments desk listed applications.** The export lists
`participants(month)` — not applications, and not months a model had not
started in. Ours listed every non-house affiliate, so two applicants appeared
as *Terms missing*, and the sidebar badge read **22 over a list of 19**. The
rule is now one function (`payments.on_the_desk`) that both the desk and the
badge call.

**The model's profile masked her destination.** The desk showed
`InstaPay · 010 1000 2000` and her profile one click away showed
`InstaPay · …291` — the same fact, to the same person, on the same permission.
The export draws the same card in both. One component now draws it
(`components/DestinationDetails.tsx`), one permission gates it, and ADR 0042
records the addition.

**Words.** Roster subtitle `19 of 22` → `19 active`; roster pager gained the
export's ` matching` suffix; `Not set` → `No terms set`; `Nothing on file yet`
→ `No destination recorded` on the desk and on the detail card, whose quiet
title was blank where the export writes it; the brand-codes note regained
*"and active counts"*; its button reads *Add code* where the export does; the
invitations screen is titled *Invitations · Invite a model and manage
outstanding links*; the portal's order filter and chip read *Delivered* and
*Pending*, and its rows count *products* rather than *pieces*; the portal's
*You* rows are in the export's order with the export's labels; her payments
screen is titled *Payments*.

**An empty filter no longer claims a search failed.** *No transfer due* with
nothing in it said *"No model matches that search."* to somebody who had not
searched. It now names the filter.

**The desk's destination column had three cases and two branches.**
`destination_line` is null both when there is no destination *and* when the
reader may not be shown one (ADR 0042 gates it on `payments.record`), so the
first version of the *No destination recorded* fix printed that sentence to
marketing about a model whose details were on file and perfectly correct. The
masked sentence is what they saw before and what they see now, and three
tests hold the three cases apart.

---

## One change that postdates its screenshot

`payment-record-1280.png` and `-1440.png` were taken while the *Destination
used* field read *Nothing on file yet* - the portal's sentence, on an admin
screen. It now reads **No destination recorded**, like the rest of the admin.
The screenshots are otherwise current; this one word is not in them. Noted
rather than quietly re-shot, because the servers were stopped for memory
before the change was made.

---

## Still differs — each needs a decision

**1. Settings → Appearance is missing two switches.** The export has
*Show pop-up notices on Home* and *Weekly reminder to record achieved
content*; ours has the theme control only. The app has something finer
underneath — each notice can be muted individually, and the mute is recorded
with who set it (A10) — and a weekly reminder that fires from day 5 of the
month. Neither has a switch. Building two global toggles that gate the
existing behaviour is a small job; building two that gate nothing would be
worse than leaving them out. **Say which you want and it goes in.**

**2. Settings → Reference writes audit rows as event names.** Ours lists
`auth.login`, `payment.recorded`, `payroll.approved` with a filter; the export
writes sentences — *"Made a feature request visible on Forest green short
sleeve"*. The export is easier to read and the event names are easier to
search. **A sentence per event type is the fix; it is about forty of them.**

**3. The account menu has two entries the export does not.** Export:
*Team and access*, *Sign out*. Ours adds *Help* and *Appearance*. Both are
real destinations with no other home on that menu. Harmless, and yours to cut.

**4. The roster has a Table/Cards toggle the export does not.** It exists
because a table does not fit a phone; the toggle is a preference and narrow
screens force cards anyway. Nothing in the approved design corresponds to it.

**5. Targets state words.** Export: *In progress*, *Below target*,
*Recorded zero*, *Guaranteed minimum*. Ours: *Met*, *Missed*, *Met ·
confirmed*, *Met · not confirmed*, and *Confirm* / *Take a confirmation back*.
The difference is real and it is not drift: ours carries verification (§15),
which the export was drawn before. **The words can be the export's and keep
the confirmation, if you want them to be.**

**6. The portal's Targets uses a third vocabulary** — *short*, *not
recorded*, *Short this month* — where the export says *met*, *not met*,
*in progress*. Same decision as 5, on her side of the product.

**7. The portal's Ranking anonymises the other models.** The export shows
their names and codes; ours writes *Another model* for everybody but her. That
was a deliberate privacy choice and it is not in the approved design.
**Your call, and it is a one-line change either way.**

**8. Her Payments screen has no separate receipt.** The export puts a
*Receipt →* link on each recorded payment and opens a receipt screen. Ours
puts the same facts on the row itself — amount, date, reference, where it was
sent, the screenshot if there is one, and a link to why the month came to that
figure. One navigation fewer and the same information. The admin side *does*
have a receipt screen, and it works (below).

**9. The portal's payment-details form is worded differently.** Export:
*Where HBA should send your payment*, *Method*, *Save details*. Ours: *Change
where you are paid*, *How should we pay you?*, *Continue*. Ours reads as a
flow, the export as a form.

**10. The portal's earnings lines are named differently.** Export: *Net sales
counted*, *Of net sales counted*, *Guaranteed minimum not applied*. Ours:
*Commission on this month's sales*, *Your monthly salary*. Partly because the
seeded model is on salary-plus-commission and the export's is on a guarantee —
but the vocabulary genuinely differs.

**11. Recording a payment is a screen of its own.** In the export, *Record
payment* stays on the payment detail — the destination card, the approval, the
transfers and the receipt are all still on screen while the amount is typed.
Ours navigates to `/payments/:month/:id/record`, which shows the form and the
figures it needs and nothing else. Both work; the export keeps more in view.

**12. The month control is a grid, not a dropdown.** You asked for the grid
and it stays; the export draws a `<select>` on the admin and a sheet on the
phone. Recorded so nobody "fixes" it back.

**13. The portal's fourth order filter is *Not counted*, not *Failed*.**
Deliberate: that bucket holds cancelled and refunded orders too, and calling a
cancelled order a failed delivery describes something that never happened. The
other three now match the export exactly.

---

## Actions exercised — 8 of 8 passing

Run by `actions.mjs`, each one changing something and reading it back from the
server on a fresh page load, because a toast is not evidence.

| Action | Result |
|---|---|
| Navigation, all six sidebar destinations by clicking | **PASS** — each lands on its own path with its own heading |
| Saving targets | **PASS** — `Aya Sherif videos required: 4 → 7`, reloaded as 7, then put back |
| Editing terms | **PASS** — Sara Edrees, September `Salary` → `17%`, saved with *Apply to 1 month* |
| Copying payment details | **PASS** — row reads `InstaPay · 010 1000 2000`, clipboard holds `010 1000 2000` |
| Opening the supplied InstaPay link | **PASS** — opens `https://ipn.eg/saraed-2291`, aborted at the browser edge so nothing is fetched |
| The link is the one she submitted | **PASS** — button `href` equals the card's *Payment link, as submitted* |
| The profile shows the same destination | **PASS** — `010 1000 2000`, no ellipsis |
| Viewing a receipt | **PASS** — `/payments/2026-08/1/receipts/1` shows `EGP 13,010.00` |

---

## Not covered, and why

- **Model · Wardrobe, Products · Active requests, Settings · Shopify and
  sync.** Each renders its empty state correctly and the export's version is
  full of fixture rows. Comparing them would be comparing seed data. Say the
  word and the seed grows shipments, a feature request and a fake connection.
- **The portal's month list.** A native `<select>`; its list is drawn by the
  operating system, outside the page, so there is nothing to screenshot.
- **Printing, and anything behind a Shopify call.** Neither is reachable in a
  throwaway environment with no shop attached.
