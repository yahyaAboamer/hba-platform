# Visual and interaction review — the checklist

One row per screen, at every width it was reviewed at. Every row has a pair of
screenshots in `shots/` named `<screen>-<width>.png`, one under `app/` and one
under `export/`, and a `.json` digest beside each.

**Matched** — nothing differs but the data.
**Corrected** — differed, and the difference is fixed on this branch.
**Still differs** — real, described below. Implementation work toward the
approved HTML unless a later explicit instruction from the owner conflicts
with it (24 September; see *The thirteen, re-sorted*).
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
| Models · Invitations | **Still differs** | **Still differs** | Populated 24 Sept with all three states. Two small wording items below; *Withdrawn* as its own state is ours and is better |
| Models · Inactive | Matched | Matched | |
| Model · Overview | Matched | Matched | Same five tabs, same three summary cards |
| Model · Wardrobe | **Matched** | **Matched** | Populated 24 Sept: *Received · 2 pieces · image · title · Size M*, the export's structure and words exactly |
| Model · Performance | Corrected (batch D) | Corrected (batch D) | Table and the order it opens; the code under the name restored in batch E (`9514fd1`) |
| Model · Targets | Matched | Matched | Same columns; state words differ, below |
| Model · Payments | Corrected | Corrected | **Was masking the destination**; now the full card |
| Products · Active | Matched | Matched | |
| Products · All products | Matched | Matched | |
| Products · Active requests | **Still differs** | **Still differs** | Populated 24 Sept. Columns and pager match; *Selling best through codes* is on this tab and is not in the export |
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
| Settings · Shopify and sync | **Still differs** | **Still differs** | Simulated connection, 24 Sept. The export edits the connection in the page; ours is read-only by choice. Below |
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
| Orders | Corrected (batch D, E) | Filters, chips, rows, sentences and row metrics match; header identity and month control corrected in batch E (`9514fd1`, `a8eaab9`) |
| Wardrobe | **Still differs** | Populated 24 Sept including a featured product. Best-sellers counting rule and a missing size, below |
| Targets | Still differs | State vocabulary, below |
| Ranking | Still differs | Other models are anonymised, below |
| You | Corrected | The export's row order and its words |
| Payments | Corrected | Screen title; receipts differ, below |
| Payment details | Still differs | Form wording, below |
| Earnings | Still differs | Line names, below |
| Month picker | Corrected (batch E) | The export's *Nov ▼* and in-page list, captured open (`shots/batch-e/`) |

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

## What the populated pass found, 24 September

Five screens could only be photographed empty on 23 September. The seed now
carries invitations in three states, a visible and a hidden feature request,
three gifts in the three delivery states the wardrobe draws, and the evidence
of a Shopify sync. All five were **re-captured, not reused**, at 1280, 1440
and 390, and looked at as pictures as well as diffed as text.

**The Shopify connection is simulated and cannot reach a store.** The panel
reads an environment setting, so the review app runs with a plainly fake
domain and token **and `WORKER_ENABLED=false`** — with the worker off nothing
leases a sync job, so nothing calls out even by accident. The rows in the
database are the evidence of a sync, not a sync.

### Newly settled

- **Admin model profile → Wardrobe: matches.** *Received · 2 pieces*, then
  `image · title · Size M` per garment, and *Not received yet* below — the
  export's structure and its words.
- **Model portal → Wardrobe: the frame matches**, including *HBA would like
  you to feature · Chosen by the HBA team* with the request's own message.

### Newly found, because the data arrived

1. **Best sellers said a different set on each side.** Ours: *"Sales through
   your code · all time · **delivered orders**"*. The export: *"Sales through
   HBA15 · all time · **delivered and pending**"*. **Fixed on 24 September** —
   see A below. *Correction:* this line first said the server agreed with our
   subtitle. It did not: `best_sellers_for` has counted delivered and pending
   since batch 1 (`0a2ba69`). Only the words were delivered-only.
2. **The featured card drops the size.** Export: *On the way · size M*. Ours:
   *On its way*. The export also shows a second card in a different state —
   *In your wardrobe · size one size* — which our single seeded request cannot
   demonstrate.
3. **Shopify panel: two actions the app does not have.** *Refresh now* in the
   header, and *Update connection* under editable Store domain and Admin API
   key fields. Ours is a read-only list that says *"Set on the server.
   Changing the connection is a deploy, not a form."*
4. **The connection header reports a different fact.** Export: *last
   successful refresh 6 November 2026, 08:15*. Ours: *last order arrived
   24 Sept, 13:10*. Somebody checking a connection wants the first.
5. **An expired invitation offers *Resend*** where the export offers *Send a
   new link*.
6. **The sent date is relative.** Ours: *today at 13:10*. Export:
   *2 November 2026*.
7. **Ours distinguishes *Withdrawn* from *Expired*;** the export writes *Link
   expired* for both. Ours is better and deliberate — `withdrawn_at` exists to
   tell a cancelled link from a lapsed one — and it stays unless you say
   otherwise.

### Still not verifiable, and why

- **Product images.** Both sides draw a placeholder: the export a dashed box
  reading *image*, ours a grey box reading *No image*. Nothing is being
  compared there until real product images are in the seed.
- **The portal wardrobe below the fold.** The export's 844px frame ends
  mid-list, so our *Ordered 4 Sept 2026* line has nothing to be compared to.

---

## The thirteen, re-sorted

Sorted as asked: **(1)** already decided, so it is implementation work and not
a question; **(2)** a genuine conflict between two requirements, quoted; **(3)**
not enough evidence yet, and what is missing.

### 1 — Already decided. Implementation work, not questions.

| # | What | Decided by |
|---|---|---|
| 1 | Settings → Appearance: *Show pop-up notices on Home*, *Weekly reminder to record achieved content* | The export draws both switches |
| 2 | Reference: audit rows as sentences, not `payment.recorded` | The export writes sentences |
| 6 | Portal Targets: *met* / *not met* / *in progress* | The export's words |
| 9 | Portal payment details: *Where HBA should send your payment*, *Method*, *Save details* | The export's words |
| 11 | Recording a payment stays **on** the payment detail | The export keeps it there |
| 12 | **The month grid belongs to terms editing only** — below. **Corrected in batch E** (see the end of this file) | Your request, read against the export |
| — | Expired invitation → *Send a new link*; absolute sent date; featured card shows the size | The export |

**I had these filed as open questions. They were not.** The design already
answered each one, and asking again was the wrong move.

#### 12, in detail: the month grid was over-applied

You asked for a grid **for editing terms**, and the approved export agrees
with you there — it carries `"Select all editable months in " + year`, which
is the terms grid's own control. That screen is right and stays.

What happened next is the problem. `MonthPicker` — the ordinary *Month*
control — was rebuilt as a grid too, and its source comment justifies that
with *"the owner asked for that and it stays"*. It is now on **eight**
screens: Home, Orders, Overview, Payments, Payroll, Settings, Targets and the
model profile. **The export uses a plain `<select>` for every one of them**
(its `{{ month }}` and `{{ mMonth }}` controls; the file contains five
`<select>` elements in total).

So one instruction about one screen was read as permission to replace every
month picker in the product. Reverting `MonthPicker` to the export's
`<select>` — and leaving `Compensation.tsx`'s terms grid exactly as it is — is
implementation work, and it is in the batch proposed below.

### 2 — Genuine conflicts. Both requirements, and what I would do.

> **How to read this section now (24 September).** The approved HTML decides
> by default, and an ordinary difference from it is implementation work, not
> a question. It is a question only where a **later, explicit** instruction
> from the owner conflicts with the HTML — the month grid for terms editing
> is the one such case recorded. An internal ADR or a privacy choice we made
> ourselves does not make it a question; it makes it a recorded divergence at
> most. The recommendations below stand as the work to do.

**A. Best sellers: delivered, or delivered and pending? — done, 24 September.**

*Not a conflict: the export and ADR 0040 agree.* The panel and *All products
sold* now read *"Sales through SARAED · all time · delivered and pending"* and
*"… Delivered and pending orders; failed deliveries excluded."*, her own code
in the export's HBA15 place. Six tests in `tests/test_best_sellers.py` drive
the rule through ingestion with explicit amounts; the recaptured
`portal-wardrobe-390` and new `portal-best-390` pairs show pending sales
moving *Panel Track Jacket* from fourth to second.

> **The approved export:** *"Sales through HBA15 · all time · delivered and
> pending"*.
> **The platform's own rule, F02 / ADR 0040:** *"A pending order counts.
> Pending and delivered are paid."* `PENDING_INCLUSIVE` is the live policy and
> every approval writes it into its snapshot.

*As first written, kept for the record:* Against both: `best_sellers_for` is
delivered-only *(wrong — see the correction above)*, and our subtitle says so
honestly. **Recommendation: follow the export and the rule — count pending.**
They agree with each other; only this panel disagrees with both. It is the one
place still applying the retired rule, and a model who reads *delivered
orders* on one screen and is paid for a pending order on another has found a
contradiction we put there.

**B. The Shopify connection: editable in the page, or set on the server?**

> **The approved export:** a Store domain field, a masked Admin API key field,
> and an *Update connection* button.
> **ADR 0015 and the deployment model:** Shopify authenticates by client
> credentials held as server configuration; the app is one deployable and a
> credential change is a deploy.

**Recommendation: keep the read-only card, and build *Refresh now*.** An API
key field in a browser form means storing a secret the server can read back,
which is a different security posture from the one the platform was built on —
and the screen already explains itself. *Refresh now* is a different matter:
the export draws it, it has no backend act, and it is the one thing somebody
actually wants from this panel.

**C. The account menu: two items, or four?**

> **The approved export:** *Team and access*, *Sign out*.
> **`test_reachability`:** a route with no way in from the interface fails the
> build.

*Help* and *Appearance* are real destinations and this menu is where they are
reached from. **Recommendation: keep them**, and if you want the export's two,
say where Help and Appearance should live instead — Settings already has an
Appearance tab, so only Help genuinely needs a home.

**D. The roster's Table / Cards toggle.**

> **The approved export:** no such control.
> **Ours:** a preference, and narrow screens force cards regardless of it.

**Recommendation: remove it.** The responsive rule already does the job it was
added for, which makes it a control the design does not have and the product
does not need.

**E. Targets state words, where verification exists.**

> **The approved export:** *In progress*, *Below target*, *Recorded zero*.
> **§15, built after the export was drawn:** a second person confirms the
> recorded numbers, and that is what unlocks a guarantee — so a month can be
> *met* and *not confirmed*, and those are different facts.

**Recommendation: take the export's three words for the states it drew, and
keep *confirmed* / *not confirmed* as the separate thing it is.** They are not
competing vocabularies: one is the outcome, the other is whether anybody has
checked it.

**F. Portal Ranking names the other models, or does not.**

> **The approved export:** every model by name, with code and avatar.
> **Ours:** *Another model* for everybody but her.

This was our privacy choice and it was never put to you — it was also asked in
the 16 September handoff and never answered. **Recommendation: follow the
export.** They are colleagues on one programme and a board is the point of a
ranking. If you disagree, the anonymised version is one line away — but it
should be your call rather than a default we chose quietly.

**G. The fourth order filter: *Not counted* or *Failed*?**

*Done in batch D, 24 September: the filter is the export's* Failed*, as the
export files its own cancelled order there; each row's chip names the real
case - *Failed delivery*, *Cancelled* or *Refunded* - and only a courier's
failure reads *Failed delivery*. See the handoff. The recommendation below is
kept for the record.*

> **The approved export:** *Failed*.
> **The bucket's contents:** cancelled and refunded orders land here too, and
> neither failed.

**Recommendation: keep *Not counted*.** The other three filters now match the
export exactly; this one would be inaccurate if it did.

### 3 — Not enough evidence yet, and what is missing.

| # | What | The comparison that is missing |
|---|---|---|
| 8 | Her payment history has no separate *Receipt →* screen; ours puts the same facts inline | **The export's receipt screen has never been captured.** Until it is, I cannot say whether our inline block is a superset or is missing something. One step, one pair. |
| 10 | Portal earnings line names — *Net sales counted* against *Commission on this month's sales* | **Like for like needs a model on a guaranteed minimum.** The seeded model is salary-plus-commission and the export's is on a guarantee, so part of the difference is the arrangement, not the wording. |
| — | Product images, in both wardrobes and the requests table | Real product images in the seed; both sides currently draw a placeholder. |

---

## The two things you asked me to check specifically

### The month grid — over-applied, and here is the evidence

Covered as item 12 above. In one line: **the terms grid is right and the other
eight are not.** The export has a grid for editing terms and a plain
`<select>` everywhere else; we have a grid everywhere, justified by a source
comment that reads *"the owner asked for that and it stays"*.

### The refunded order — the rule is right; one comment still says the opposite

**The behaviour is correct and tested.** ADR 0025 makes delivery final, and
four tests in `tests/test_commission_attribute.py` hold it:

- `test_a_refund_after_delivery_keeps_the_sale_and_the_commission`
- `test_a_partial_refund_after_delivery_keeps_the_whole_sale`
- `test_an_exchange_after_delivery_keeps_the_sale_and_the_commission`
- `test_a_refund_before_delivery_does_take_the_sale_back`

All four passed in the full run at `f83b4fc`, and nothing under `app/` has
changed since — so they are not re-run for a documentation and screenshot
pass.

**But one comment was missed when this was corrected.**
`app/services/portal.py:756` still reads:

> an order delivered and later refunded **pays nothing** and is still a use

That is the opposite of the agreed rule. Seven hundred lines further down, the
comment that *was* corrected says so in as many words:

> ADR 0025 is that delivery is final, so a refund, a return or an exchange
> leaves a delivered order earning exactly what it earned. An earlier draft of
> this comment said such an order "pays nothing", which is the opposite of the
> rule HBA runs.

Two comments about one rule, contradicting each other, in one file. **Nothing
computes from either** — `commission_state` checks delivery before anything
else — so this is a documentation defect, not a money defect. It is in the
next batch and is deliberately not changed here.

---

## The original thirteen, kept for the record

The list as first written on 23 September, before the populated pass and
before they were sorted. Kept because five of them turned out to be questions
that the approved design had already answered, and that is worth being able
to see. **Read the sorted version above; this one is history.**

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

**13. The portal's fourth order filter is *Not counted*, not *Failed*.** *(Superseded by batch D: now* Failed*, with chips that name the case.)*
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

- ~~**Model · Wardrobe, Products · Active requests, Settings · Shopify and
  sync.**~~ **Done, 24 September.** The seed grew shipments, a feature request
  and a simulated connection, and all five affected screens were re-captured
  rather than reused. See *What the populated pass found* above.
- ~~**The portal's month list.**~~ **Done in batch E**: now the export's
  in-page list, captured open.
- **Printing, and anything behind a Shopify call.** Neither is reachable in a
  throwaway environment with no shop attached.

---

## Batch E — shared typography, identity headers and month controls (24 September)

Captured with `shared-controls.mjs` (headless Chromium, the throwaway
`hba_browser` database, fonts awaited before every shot, the export's frame
clipped below its simulated status bar). Pictures and digests in
`shots/batch-e/before/` and `shots/batch-e/after/`; side by side, before ·
after · export, in `shots/batch-e/compare/`.

### Reference to app

| Reference | Where in the export | App |
|---|---|---|
| Body type: Inter, 15px, `line-height:1.55`, 400 | `_ds/…/styles.css` | `base.css` `body` |
| The one heading element: `h4`, 18px, 500, 1.12, −0.015em | Admin `pageTitle` | `.layout__main > .page__head h1` |
| Every other title and figure: `var(--font-heading)` (family only), 400 | both | `h1`–`h3` base, and the screen rules listed in ADR 0043 |
| Tabular figures on money, counts and ranks only | 30 + 19 inline uses | `.money` and the column classes; no longer on `body` |
| Controls at the browser's `line-height: normal` | every `<button>`, `<select>` | `base.css` `button, select` |
| Admin top-bar month: *Month* 12px + `<select>` 38px, 13.5px | `monthly`, `onMonth` | `MonthPicker` (default size) on Home, Orders, Payments, Payroll, Targets |
| Profile month: *Month* + `<select>` 36px, 13px | `mMonth`, `onMMonth` | `MonthPicker size="section"` on the model profile |
| Profile title: name, code under it at 12.5px, 4px apart; 14px after Back | `titleVals` (`m.name`, `m.code`) | `AffiliateDetail` `page__title` + `page__subtitle` |
| Portal header: edge to edge, 16px inside, fixed while the screen scrolls | `inApp` block | `.phead-bar` (sticky) + `.phead` |
| Identity line: *HBA ambassador · CODE*, 12.5px muted, not truncated | `inApp` | `.phead__since` (wraps) |
| Portal month: *Nov ▼* button, 13px, list under the header with each month's state | `showPicker`, `monthOptions` | `button.phead__month` + `.pmonths` |
| Multi-month grid | terms editing only | `Compensation.tsx`, unchanged |

### What the type difference actually was

**Not the font.** The app's self-hosted Inter and the export's Google Fonts
Inter (v20) measure identically in the same Chromium: a test line at 438.49px
(400), 443.12px (500), 447.7px (600). Nothing fell back. The differences were
line height (1.5 vs 1.55), tabular figures on every digit, headings at
600/1.25/−0.01em, a dozen rules that read `var(--font-heading)` as weight 500,
the agreed figure at 500, controls inheriting 1.55, and no 700 face for
`<strong>`. ADR 0043 records the change and its cost. One Home defect found on
the way: the metric label rule also matched the figure's `<span>`, printing
*Net sales counted* at 12.5px grey instead of 17px ink.

### Checked, and how

| Screen | Widths | Result |
|---|---|---|
| Portal Home (header, month control closed / open / month chosen, scrolled to the end) | 390 | Corrected |
| Portal Orders (September, and July chosen through the new list) | 390 | Corrected; row height below |
| Portal Ranking header | 390 | Corrected |
| Portal header with a long name and code (`/api/me` answered with them) | 390 | Wraps, nothing cut |
| Admin model profile (header, code, month select, month chosen, Back from an order) | 1280, 1440 | Corrected |
| Admin profile with a long name and code | 1280 | Wraps, nothing cut |
| Admin Home, Payments, Targets top bar | 1280, 1440 | Month control identical: 38 × 152px, 13.5px |
| Admin Orders and Payroll top bar | 1280, 1440 | Month control as above; no export pair |

Measured, after: header 66px on both; list rows 42px vs 41px; the portal
header stays at 0–66px while Home scrolls under it and the last line ends at
744px against the tab bar at 788px; no horizontal overflow at 390; choosing
a month closes the list, changing tab closes it, a secondary view and Back
keep the month; the profile's chosen month survives opening an order and
Back (`?section=performance&month=2026-07`); the chart's month columns work
by tap and by keyboard.

### Batch E's divergences - withdrawn by the follow-up below

Batch E kept two differences with reasons (controls in Inter; the profile
offering every platform month). The owner's answer: *an explanation for a
difference does not approve that difference.* Both are implemented below.
Batch E also listed *Payments: the model's name at 15px/700*. That was a
mis-pairing: the 15px/700 name is our corrections panel's, which the export
does not have; the desk row's name was already 13.5px/400.

---

## Batch E follow-up (24 September)

Pictures and digests in `shots/batch-e/follow-up/`; Batch E · follow-up ·
export side by side in `shots/batch-e/compare-follow-up/`.

| What | Before | Now | Export |
|---|---|---|---|
| Buttons | Inter, inherited | the browser's control font (`font: revert`), ADR 0044 | control font on 146 of 150 buttons |
| Portal Orders row | 95px | **92px** | 92px |
| Portal month list row | 42px | **41px** | 41px |
| Portal header | name 236, month 62×35, 390×66 | same | same |
| Payments row name | Inter 13.5px/400 | Arial 13.5px/400 (control font) | Arial 13.5px/400 |
| Payments state pill | 12px, no vertical padding (leaked `.pill`) | 11.5px, 3px 9px, inline, 22px box | same |
| Profile *Active* pill | 12px (leaked `.pill`) | 11.5px, 3px 9px, 25.8px box | same |
| Profile labels, sizing note | 13px / 12px | 12.5px | 12.5px |
| Admin Home ⋯ and ✕ | bare glyphs | 34px bordered squares, 13px | same |
| Admin Home *Estimated*, *19* | tracked | untracked | untracked |
| Portal Home chips | *0 on the way*, *0 not counted* (all void) | *0 pending*, *0 failed delivery* (courier failures only: `failed_delivery`, decided on the server by the order's own status) | *1 pending*, *0 failed delivery* |
| Portal Home chart | 4 labelled rules, no headroom | the export's plot: 3 rules, 15% / 35% headroom, open points, `viewBox -24 0 324 130`, no axis text | as rendered |
| Profile month control | platform months, 2026-01 to working month | **her months** (`months_for`, in the profile payload) | her months (`started`) |

**The profile's months, and the records outside them.** The rule is the one
her portal already used: her recorded collaboration start, else her earliest
order or payroll record, floored at 2026-01, up to the working month. Admin
reporting screens keep the platform's months. `outside_months.py`
(read-only) lists any model whose orders or payroll records fall outside her
months. On the disposable database: 7 models, each with one or two orders in
2025-11 / 2025-12 - before the platform's first month, put there by the
seed's date shifting, and offered by no control before Batch E either. **No
model has records hidden by a recorded start inside the platform's range.**
Staging and production were not queried (item 9 below).

**Checked.** Portal at 390: Home, Orders (September; July chosen through the
new list), month list open and a month chosen, Home scrolled to the end
(header held at 0-66px, last line at 744px above the tab bar at 788px), a
long name and code, no horizontal overflow. Admin at 1280 and 1440: profile
(her months, *Performance* kept, `month=` written, Back from an order returns
to *Performance · July*), Home, Payments, Targets, Orders and Payroll top
bars, a long name and code at 1280. Fonts awaited before every capture.

---

## Batch F - the owner's three answers, and five presentation items (24 September)

The owner answered the three questions the follow-up asked. Evidence:
`shots/batch-f/` (`checks.txt` is the browser run, at 1280, 1440 and 390;
`compare-chart-390.png` is ours, sales and uses, beside the export).

- **No earlier-month notice on admin Home.** The unused logic is removed
  (`Overview.tsx`: the note, its `lockFor`, and the sync read that existed only
  for it). Payment views keep their own historical explanations; no data moved.
- **Chart axes restored**, from her real figures: three rules labelled in EGP
  with *K* from 1,000 (*0 / 7.3K / 14.6K* for Sara's year), uses in whole
  counts on a whole, even scale (*0 / 3 / 6*), month numbers under each month
  with the month being read in accent. Gaps, an all-zero year (one label,
  flat on the axis) and a single month (centred) are tested
  (`PortalYearChart.test.tsx`); tap and keyboard selection re-checked; the
  widest label fits the 390 frame; no horizontal overflow.
- **The *Agreed months that have changed* panel is gone from Payments.** Its
  way in is now the export's Home notice, which the app never had: one per
  open correction, from the same `open_corrections` the panel used, across
  every payable model. *Late failed order needs a decision · Sara Edrees ·
  order #1013 failed after August was approved.* - the export's words, and
  only where every order the agreement counted and has lost was a courier's
  failure; otherwise *Agreed month changed and needs a decision*.
  *Open correction* opens the month's correction; its Back reads *← Home*.
  Checked: after going to Payments and back the notice is still there and
  still opens it; the model's payment review still links *Open the
  correction*; correction records, resolution routes and their safeguards are
  untouched. Three tests in `tests/test_corrections.py`.
- **Sales/Uses switch** as the export's `.seg`: measured equal (accent and a
  1px inset accent outline on the chosen half, ink on the other, 34.1px,
  Inter).
- ***· So far*** removed from the chart reading.
- **Home notice titles** without a full stop, as the export's; details keep
  theirs.
- **The global `.pill` override in `Compensation.css` is removed** - it was
  unused by Compensation and was restyling every other screen's pills. The
  base `.pill` is now `inline`, as every status pill in the exports is;
  checked against each reference: Payments 11.5px 3px 9px inline 22px =
  export; profile 25.8px block (a flex row) = export; roster and Products
  inline 11.5px 3px 9px (22px against the export's 20px - its row is a
  `<button>`, so its pill is in the control font; row structure, item 12
  below); payment and order views 12px 4px 10px = the export's own style.
  The two local overrides added earlier are gone.

---

## Batch J - Shopify *Refresh now* (25 September)

Owner's scope, 25 September: *Refresh now* and *last successful refresh*,
reusing the existing synchronisation; accepted is not refreshed; running,
success and failure shown accurately; a failure keeps the last success; no
duplicate jobs from repeated clicks; read-only towards Shopify; permissions
unchanged; tested against a disposable database and a simulated shop.

**Reference to code.** Export: `Admin Dashboard.dc.html` lines 651-667
(`syncStore`, `syncState`, `syncTone`, `lastSync`, `refreshSync`,
`refreshLabel`, `syncErrorLine`), script 3551-3560. App:
`frontend/src/screens/DataPanel.tsx` (the top card), `app/api/operations.py`
(`POST /api/operations/refresh`; `refresh` in `GET /api/operations/sync`),
`app/services/shopify/refresh.py` (new).

**What a refresh is.** `JobKind.RECONCILE` - the sweep that already re-reads
every order Shopify changed in the last 48 hours and runs every half hour.
*Refresh now* brings the outstanding sweep forward (`run_after = now`), or
queues one under the same dedupe key when none is outstanding, or joins the
one running. Same payload as the schedule. It sends one GraphQL query per
page; no mutation exists on the path (the simulated shop refuses any, and
none arrived).

- **States**, from the jobs themselves: *Connected* (latest sweep succeeded,
  or none yet - then *no successful refresh yet*), *Refreshing* (queued and
  due, or running under a live lease), *Last refresh failed* (the latest
  finished sweep failed, or a retry is waiting after a failed attempt), and
  *Not connected* (no connection; the button is disabled and the route
  answers 409 with nothing queued). The export draws three; *Not connected*
  is the state it never drew.
- **Last successful refresh** is `finished_at` of the newest *succeeded*
  sweep, in Cairo time, as the export prints it (*25 September 2026,
  11:15*). Accepting a request moves nothing; a failure cannot move or clear
  it. `prune_succeeded_jobs` now keeps the newest success of each kind
  however old, so a month of failures cannot turn it into *never*.
- **The failure line** is written from recognised causes (429, refused
  credentials, refused access, no connection, Shopify 5xx, unreachable),
  never the raw error, and ends *Nothing from this attempt was saved; the
  next refresh reads the same orders again* - true: the worker rolls the
  attempt back and the next sweep reads the same window. The export's
  *continues where it stopped* is not what the sweep does, so it is not said.
- **Duplicate clicks.** The button is disabled from the click until the sweep
  finishes; the server keeps one outstanding sweep regardless (dedupe index
  plus a row lock), so three requests give one job.
- **Permissions unchanged.** `POST /refresh` needs `settings.manage`, as
  *Read the catalogue* and *Import order history* do; the Shopify tab is
  already admin-only. The status block rides on `/sync`, whose permission
  is unchanged and which carries no credential.
- The card's old button, *Read the catalogue*, was a stand-in; the catalogue
  read stays under *Technical detail*. The old *· last order arrived* is
  still there as *Last order synced*. Kept, not in the export: the sentence
  counting work that stopped, shown only when a job has failed for good.
- `Settings.css` used `var(--radius-md)`, which the app never defines, in
  three places (the new button and two result boxes rendered square); now
  `var(--radius)`, the export's 8px.

**Checks run.**

- Backend: `tests/test_shopify_refresh.py` (9, new: accepted-not-refreshed
  then finished; a 429 keeps the last success and shows the line; *Try
  again* brings the retry forward, no second job, then succeeds; three
  clicks one job; a click while running joins it; the scheduled sweep
  brought forward, not duplicated; no connection 409 and nothing queued;
  a marketing role 403 and nothing queued), `test_jobs` (new: the newest
  success of each kind survives pruning), `test_reconcile`,
  `test_operations_api`, `test_shopify_connection`: 154 passing.
- Frontend: `ShopifyRefresh.test.tsx` (6, new); the whole suite 436 tests,
  23 files; `npm run build` green.
- Browser, 1280 and 1440, the app started through `simulated_shopify.py`
  (the real route, worker and sweep; only Shopify's transport simulated)
  against the throwaway `hba_browser` database: arrive; click twice with a
  slow shop - one POST, *Refreshing* / *Refreshing…* disabled, time
  unchanged; finished - time moved; reload - same; shop answers 429 -
  *Last refresh failed*, the line, *Try again*, time kept; reload - same;
  *Try again* with the shop answering - *Connected*, time moved. Button,
  state and time line measured equal to the export's (13.5px, 10px 15px,
  40px high, 8px radius, accent border and fill; state 13px; time 12.5px
  faint). `shots/batch-j/checks.txt`, `app-shopify-*-{1280,1440}.png`,
  `export-shopify-{1280,1440}.png`; script `batch-j.mjs`.

**Found, not fixed (outside this item).** The worker runs inside the web
process's event loop and handlers are synchronous (`app/worker.py`,
`worker_loop` calls `run_one` directly), so **while any job runs, the API
answers nothing**: with the simulated shop set to answer after five seconds,
the status request made during the sweep returned only when the sweep had
finished. A sweep of a few pages is seconds every half hour; the historical
import or a slow Shopify is longer. Recorded as item 19a.

**Cloud-session note.** The export loads React from unpkg, which this
session's network policy refuses; `batch-j.mjs` serves React 18.3.1's own UMD
files from the npm registry copy (`EXPORT_VENDOR`) and fetches Google Fonts
through curl. Unset, it loads the page as before.

## Batch J - Admin Targets (25 September)

**Reference to code.** Export `vTargets` (Admin lines 465-525), `tgRows`
(2753-2785: `state`, `stateTone`, `arrangement`), `mTargetHistory` (2966-2976,
*Below target* for an ended month). App: `frontend/src/screens/Targets.tsx`
(`outcomeWord`, `Outcome`, `Confirmation`, the arrangement label),
`Targets.css`, `app/services/targets.py`.

**§T re-checked against the sweep's `targets-*` pairs first.** Already as the
export: search, the *Record achieved* / *Set requirements* switch, *Save
changes* top right with the dirty count and *Discard*, inputs 56px with *of N*
beside, the arrangement beside the name, the subtitle. So §T's list 1-8 was
mostly done; what remained is below.

- **The Recorded cell's first line is the export's word**, toned as the
  export: *No record yet* (amber), *Recorded zero*, *Target met* (the lifted
  green, `--acctext`), *In progress* while the month runs and *Below target*
  once it has ended - both quiet. Was *Met* / *Missed*, untoned.
- **Confirmation kept, separately** (decision E): *Confirmed* on any
  confirmed record, *Not confirmed* on a met one - its own line, because
  *Target met · not confirmed* (160px) is wider than the export's 140px
  column. **Kept divergence, with its reason:** with D08's pace line
  (standing) under it, a row with all three is 84px where the export's is
  57px. Both lines are the owner's later instructions; the export predates
  them.
- **Column widths.** The export's 150/150/140/120 are *content* widths
  between 16px gaps; ours were set as cell widths including padding, so every
  column was narrower and *Last updated* had 94px of the export's 120 (a
  September date wrapped to two lines). Now measured equal: 150/150/140/120
  at 1280 and 1440.
- **The guarantee label** reads *Guarantee needs this record* only while no
  record exists (the export's `!targetKnown`), then *Guaranteed minimum*.
  Ours said it on every guarantee row.

**Defect found by the browser check, and fixed.** Saving the grid sends
every row; `record_actuals` cleared the confirmation of any row it was
handed, changed or not, and moved its *Last updated* to today, and
`set_requirements` audited unchanged requirements. So **saving one model's
count silently un-confirmed every other confirmed month on the grid** - and a
confirmation is what releases a guaranteed minimum. Seen live: after changing
two models at 1280, every row at 1440 read *Not confirmed*. Now the same
numbers again are a no-op (after the same recordability check), so only a
row whose numbers changed loses its confirmation. Test:
`test_saving_the_grid_leaves_every_unchanged_row_as_it_was` (fails without
the fix - checked).

**Checks run.** Backend: every file that touches targets (13 files, 482
tests) passing. Frontend: `TargetsWords.test.tsx` (4, new); suite 442 tests,
24 files; `npm run build`. Browser at 1280 and 1440 (`shots/batch-j/`,
`checks.txt`): columns and tones measured against the export; a non-number
refused with the typing kept; a stale revision (another tab saved first)
refused with the typing kept; reload shows the stored value; 2 of 4 saved
reads *In progress*, survives a reload, put back reads *Target met*; only the
re-recorded row lost its confirmation; August reads *Below target*.

**Not changed.** The pace line on an ended month (*On pace · 12 of 12* in
August) is D08's as built; the checkbox before an unconfirmed name is how
*Confirm* chooses (standing).

## Batch J - Record payment (25 September)

**The item's premise was wrong, and the approved HTML decides.** Item 10 said
the export keeps *Record payment* on the payment detail. It does not: the
detail's *Record payment* button (`openRecord`, Admin line 3249) pushes a
`record` view onto the stack, titled *Record payment* with *{name} ·
{month}* under it and Back to the model (line 2365); `vRecord` (1403-1443) is
that screen. The sweep's `payment-record` pair put our record form beside the
export's *detail*, because its reference step stopped before pressing the
button, and #11 was read off that pair. So recording stays a view of its own,
as the export draws it; moving it inline would have diverged from the
approved design. **If the owner wants it inline regardless, that is a new
instruction against the HTML and his to give.**

Against the real `vRecord`:

- Subtitle *{name} · {month}* (ours had the month alone) - fixed.
- The note is the export's one sentence; ours added *{name} sees the
  receipt* - removed.
- Everything else already equal, measured at 1280 and 1440: the due line,
  the five fields and their labels, the dashed receipt box, *Record payment*
  (14px, 12px 18px, 44px, accent fill) and *Cancel*, the amount input (14px,
  12px 13px, 44px, 8px radius), the refusal and over-amount lines.
- Kept, not in the export: the *Why is it different from what is
  outstanding?* field, required when the amount is not the balance - the
  platform's rule for a partial or over payment.

**Checks.** Browser (`shots/batch-j/`, `export-record-*`, `app-record-*`):
0 refused with the export's line; over the balance warns with the export's
line; EGP 500 with a reference and reason saved, back on the detail, the
reference and EGP 500.00 there after a reload, the outstanding down from
EGP 10,512.00 to EGP 10,012.00. Frontend suite and build.

## Remaining work - the one list (reconciled 24 September)

Reconciled against: the 24 September handoff (*What is waiting on Yahya*,
the backlog, batch D's table), this checklist (the sweep tables, the
populated pass, *The thirteen, re-sorted*, *Not covered*),
`docs/redesign/parity/SCREEN_MATRIX.md` (its kept differences, §T, §P and
route list, written 12 September and partly superseded), `CLAUDE.md`'s
release gates, and `docs/repair/HISTORICAL-INFORMATION-NEEDED.md`. Nothing
from those is dropped: each is below, or in *Closed, with evidence*.

### Implementation - approved differences still to build

Portal (390)

1. ~~**Wardrobe featured card** shows the size~~ - **done, batch G**.
2. ~~**Targets words**: *met* / *not met* / *in progress*~~ - **done, batch G**
   (live month *in progress* / *targets met*; past *met* / *not met*).
   *not recorded* waits on exception (f); the pay sentence is item 6.
3. **Ranking** names the other models, with code and avatar, as the export
   does (F; ours writes *Another model*).
4. ~~**Payment details form** in the export's words~~ - **done, batch G**:
   *Where HBA should send your payment*, *Method*, *Save details*; our extra
   lead sentence removed. **Finished in batch H**: the export's *Method*
   segment (*InstaPay · Wallet · Bank*) and *Back* / *Save details*; the
   password is asked after *Save details* (decision h).
5. **Home order chips** are links in ours, plain pills in the export
   (matrix, kept for a preference only).
6. **Targets guarantee sentence** stands in the open; the export puts it
   behind an ⓘ (matrix, preference only).
7. ~~**You screens: buttons still set to Inter**~~ - **done, batch G**:
   sign-out, leave, the detail rows, notification rows and the reveal
   button take the control font. `portal.css`'s `.affiliate .block` still
   resets it, and no screen was found rendering it - to confirm and remove.

Admin (1280 / 1440)

8. ~~**Invitations**~~ - **done, batch G**: *Awaiting application*,
   *Link expired* (red), *Send a new link*, and the date in full on the
   invitations page and the roster. Still different: the roster's invitation
   row keeps its own *Resend* / *Withdraw*, where the export's row opens the
   invitation instead.
9. ~~**Targets state words** and matrix §T~~ - **done, batch J**: the
   export's words, confirmation kept separately, the export's column widths,
   and the guarantee label's rule; §T re-checked (see *Batch J - Admin
   Targets*). The confirmation-clearing defect it found is fixed.
10. ~~**Record payment on the payment detail**, not a screen of its own~~ -
    **premise corrected, batch J.** The export records on its own view too
    (`openRecord` pushes `record`, Admin lines 2365 and 3249; `vRecord`
    1403-1443). Thirteen #11 compared our record form with the export's
    *detail*, because the sweep's reference step never pressed *Record
    payment*. Against the real `vRecord`, two words differed and are fixed.
    See *Batch J - Record payment*.
11. **Settings**: Appearance's two switches (*Show pop-up notices on Home*,
    *Weekly reminder to record achieved content*) (#1); Reference's audit rows
    as sentences, about forty event types (#2).
12. **Roster and Products rows as buttons** (control font, so their pills
    measure 20px as the export's); the roster's **Table / Cards** toggle
    removed (D).
13. **Admin Home chart**: axis label outside the plot, as the export (matrix,
    kept for a preference only).
14. **Admin profile body** (Overview): the Contact panel as the export's
    editable form - **a separate task, as the owner set out on 24 September**:
    field permissions, validation, saving, and contact email against sign-in
    identity (D07's *Signs in with* is his later instruction). Also in that
    body: Sizing values at 15px (ours 12px), the start value at 12.5px, and
    the *Discount codes* panel, which the export does not have.
15. **Terms editing: buttons still set to Inter** (`Compensation.css` `.fork`,
    `.mo`, `.kinds`, `.seg`, `.comp__clear`), with its screen's review.
16. **Products**: the per-model order reference the export prints on a
    product (not in the roster payload); the feature request's message
    presets (matrix B3, B4).
17. ~~**Settings → Shopify: *Refresh now* and *last successful refresh***~~
    - **done, batch J** (25 September). The reconciliation sweep brought
    forward; see *Batch J* below.
17b. ~~**Settings → Shopify: the editable connection**~~ - **done, batch I**
    (ADR 0045): *Store domain*, *Client ID*, *Client secret* (the owner's
    choice of fields, 25 September), *Update connection*; admin only;
    secret encrypted, never returned, logged or audited; tried against
    Shopify before saving; a refusal changes nothing. **Before it can be used
    on an environment, `SETTINGS_ENCRYPTION_KEY` must be set there** (item
    30a) - without it the form refuses to save, by design.

Code hygiene (no behaviour)

18. ~~The *"pays nothing"* comment in `app/services/portal.py`~~ - **done,
    batch G**; it now states ADR 0025's rule.
19. `/payroll/:month/reopen` (`PayrollReopen.tsx`): reopening is retired
    (05B); the route is a candidate for removal, with `test_reachability`.

19a. **The worker blocks the web server while a job runs** (found in batch
    J): `worker_loop` calls the synchronous `run_one` inside the event loop.
    Candidate fix: run `run_one` in a thread (`asyncio.to_thread`). Not
    started - it changes how every job runs and wants its own review.

### Verification - still to run

20. **Admin *Attributed orders* list (`vOrders`) - layout not reviewed.**
    Only its month control has been checked.
21. **The export's admin order view renders blank** in the served prototype;
    our order detail was compared against its markup only.
22. **The export's receipt screen was never captured**, so whether our inline
    receipt is a superset is unknown (#8).
23. **Earnings line names** need a seeded model on a guaranteed minimum to
    compare like for like (#10).
24. **Product images** and **the portal wardrobe below the fold**: nothing to
    compare yet (placeholders; the export's frame ends mid-list).
25. **Printing, and anything behind a Shopify call**: unreachable without a shop.
26. **Staging**: an approved month with transfers (matrix B7) and a terms
    apply (B11) have not been exercised on staging data.
27. **Real data**: `outside_months.py` (read-only) against staging and an
    authorised restored copy; only the disposable database has been checked.
28. **Devices**: the control font on an iPhone, on Android and in Firefox.
29. **`payment-record-*` screenshots** predate the *No destination recorded*
    wording.
30a. **Deploying the connection form** needs `SETTINGS_ENCRYPTION_KEY` (a
    Fernet key) set on each environment, kept out of the database; and the
    new migration `c3d51e7a0002` applied. Not done - no deployment is
    authorised.
30. **Before merge**: the full backend runner (`run-suite.sh`), the frontend
    suite and build. Not re-run for this batch; the focused files are.
31. **Release gates** (`CLAUDE.md`): reconciliation against an authorised
    restored copy of real data (`reconcile.py` has only run on the test
    database), and a migration/rollback rehearsal for `b1f0a40c0001`. Neither
    has run; the repair is not releasable while they are open.

31a. **Order-import completeness, on real data.** Two read-only tools, both
    proven locally and neither run on staging or production:
    `order_import_compare.py` (Shopify's order IDs for the period against
    the imported IDs; every page of the listing accounted for; access limits
    such as a missing `read_all_orders` recorded - six tests in
    `tests/test_import_completeness.py`) is what can show completeness;
    `order_import_report.py` gives clues only - **a gap in the order numbers
    is something to investigate, not proof of a missing import**. Blocked on:
    the owner's go-ahead for production (not given), and `railway ssh`,
    which from this machine reaches Railway's account endpoint instead of
    the service. Item 32's confirmation is asked for only after he has
    reviewed the comparison.

### Information needed from the owner

32. **Historical terms** (`HISTORICAL-INFORMATION-NEEDED.md`): each model's
    start month; her terms each month - commission rate, fixed salary,
    guaranteed amount - **not** what was transferred (old payment records
    were not imported, by agreement, and are not needed); the target outcome
    for guaranteed months; confirmation the order import is complete - **after
    you have reviewed the import report** (item 31a); and which environment
    to unlock and when. The rest of this list does not wait on these.
    Historical finalisation stays locked until they are in.
33. ~~Exceptions a-h~~ - **decided by the owner, 25 September, and
    confirmed.** No longer questions; each is recorded under *Owner decisions
    standing* below with where it stands.

34. **Permissions**: merging to `main` and promoting to `production` are two
    separate decisions; neither is given.

### Owner decisions standing (not open)

**Exceptions a-h, decided 25 September** - his words, summarised; each was
a question in item 33 and is not one any more.

| | Decision | Where it stands |
|---|---|---|
| a | Keep *Withdrawn* separate from *Link expired* | As built (`InvitePage.tsx`); nothing to do |
| b | Build the export's editable Shopify connection in Settings: authorised staff only; credentials protected and never in responses, logs or audit text; a failed update must not destroy the working connection; no editing of Shopify orders or products. Fields: *Store domain*, *Client ID*, *Client secret* (his answer, 25 September) | Done, batch I (ADR 0045) |
| c | Account menu = *Team and access*, *Sign out*; Help and Appearance keep their own places | Done, batch H: Appearance is Settings' tab, Help is Settings → Reference and the glossary links |
| d | No SKU or size count under the product name; no substitute; sizes stay in wardrobes and product/model details; SKU data stays in storage and integrations | Done, batch H |
| e | Remove the admin *Selling best through codes* panel; keep the model's *Your best sellers* | Done, batch H: panel and its only route removed; `top_products` and the model's best sellers untouched |
| f | *Not recorded* where no achievement record exists; never read a missing record as zero or a miss; *met* / *not met* / *in progress* where records support it | As built (batch G; `lib/targets.ts` keys *not recorded* on no record) |
| g | *Usually recorded around [date]*: the 3rd of the following month, an estimate not a promise; none for paid months or months settled outside; once passed, never moved forward or shown as upcoming | Done, batch H (`expectedRecording`) |
| h | Keep the password confirmation, after *Save details*; a failed confirmation saves nothing and discards nothing | Done, batch H; tested |

Also standing: the month grid for terms editing only; Targets' *Confirm*,
*Whole year* and the D08 pace line; the payer sees the whole destination
(ADR 0042); pending orders count (ADR 0040); *Signs in with* (D07); no
earlier-month note on Home; chart axes from real figures; corrections reached
from Home's notice, not Payments; Payments' *Settle difference* for an
overpaid month (a real state the export never drew).

### Closed, with evidence

| Item | Where it came from | Closed by |
|---|---|---|
| Month grid only in terms editing (#12) | Thirteen, handoff | `9514fd1` |
| Portal header identity, portal month control, admin header code | Batch D table, matrix *month picker open* | `9514fd1`, `a8eaab9`; `shots/batch-e/` |
| Type: line height, figures, weights | Batch E | `9514fd1`, ADR 0043 |
| Buttons in the control font; Orders rows 92 = 92; month rows 41 = 41 | Batch E kept divergence | `a8eaab9`, ADR 0044 |
| Profile offers her months | Batch E kept divergence | `a8eaab9` |
| Home chips *pending* / *failed delivery* | Batch E list | `a8eaab9` |
| Profile labels and *Active* pill; Home ⋯ ✕ and spacing; Payments name and pill | Batch E list | `a8eaab9`; pills finished here |
| Chart axes, switch, *· So far*, Home titles, `.pill` leak, corrections panel, Home note | Follow-up list, owner's answers | `900aa21`; `shots/batch-f/checks.txt` |
| Wardrobe size, Targets words, payment-details words, Invitations words and dates, You buttons' font, the refund comment | Items 1, 2, 4, 7, 8, 18 | `1b0a240`; `shots/batch-g/checks.txt` |
| Decisions c, d, e, g, h: account menu, product list line, top-sellers panel, the usual recording date, the password after *Save details* | Owner, 25 September | `52ab988`; `shots/batch-h/checks.txt` |
| Decision b: the Shopify connection edited in Settings | Owner, 25 September | batch I (the commit that adds this row); ADR 0045; `tests/test_shopify_connection.py` (11), `ShopifyConnection.test.tsx` (4); `shots/batch-i/checks.txt` |
| Record payment: premise corrected; subtitle and note as `vRecord` (item 10, #11) | Thirteen | batch J; `shots/batch-j/export-record-*`, `app-record-*` |
| Admin Targets words, widths, guarantee label; unchanged rows keep their confirmation (item 9) | Thirteen E, matrix §T | batch J; `test_targets_api` (+1), `TargetsWords.test.tsx` (4) |
| *Refresh now* and *last successful refresh* (item 17) | Admin export, handoff | batch J; `tests/test_shopify_refresh.py` (9), `ShopifyRefresh.test.tsx` (6); `shots/batch-j/checks.txt` |
| Portal order filter *Failed*, chips naming the case (G, #13) | Thirteen | `6131d0c` |
| Net sales and *Counts towards* from facts | Batch D | `7bd9650` |
| Earnings explanations, per-order commission | Batch C | `1b1bb21` |
| Best sellers count delivered and pending (A) | Populated pass #1 | `4077b88` (server right since `0a2ba69`) |
| Five empty screens populated and recaptured | *Not covered* | `ffde978` |
| Currency `EGP`, the Home applications notice, desk applications removed, profile destination unmasked, words | Sweep *Corrected on this branch* | `f83b4fc`, `8456045` (ADR 0042) |
| Matrix *E£ not EGP*, *masked destination*, *Not counted*, *Resend/Withdraw with no invitation view* | Matrix kept list | superseded by the rows above and by `vInvite` |
