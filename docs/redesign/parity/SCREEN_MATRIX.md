# Screen matrix — the approved exports against what we ship

**Purpose.** One row per reachable view and per state that changes what is
drawn. A row is not "done" because the feature works; it is done when its
structure, copy, computed styles, rendered result and interactions have each
been checked against the export.

**Sources of truth**

| | |
|---|---|
| Admin export | `docs/redesign/designs/Admin Dashboard.dc.html` — sha1 `aa8794aa…`, 3624 lines |
| Portal export | `docs/redesign/designs/Affiliate Portal v3.dc.html` — sha1 `3f9f150c…`, 1462 lines |
| Design system | `docs/redesign/designs/_ds/nocturne-…/styles.css` — Inter 400/500/600/700, radius 4/8/14 |

Both exports are **unchanged and must stay unchanged**. Every element in them
carries its full style inline, so the export's line range *is* the
specification — read it, do not guess from a screenshot.

**Not product UI.** The export's outer `Complete prototype` header, the
1280/1440 width buttons, the review-scenario buttons, the closing
documentation cards ("Where each journey starts"), and the phone frame in the
portal export are demonstration furniture. Sample names, amounts, months and
images are fixtures, not content.

**Authority order.** 1. Yahya's later decisions (recorded in `docs/decisions/`).
2. The approved HTML, including exact static wording. 3. Existing code — an
implementation to correct, never a competing design.

## Status vocabulary

| Status | Means |
|---|---|
| `Unreviewed` | Nobody has read the export's range for it |
| `Mapped` | Export range read, differences written down in this file |
| `Implemented` | Rebuilt to the export's structure, copy and metrics |
| `Visually verified` | Rendered side by side at 1280 and 1440 (390 for the portal), both themes, and looked at |
| `Functionally verified` | Its controls exercised against the real backend |
| `Blocked` | Needs something we do not have; the row says what |

---

## A. Admin — primary views

The export's wording and tones are bound from its data script (line 1646
onward: `rosterVals`, `catalogueVals`, `ordersVals`, `orderVals` …). Read the
script as well as the markup — three screens were matched on markup alone and
had the wrong filter names.

| # | Export view | Lines | Route / component | Status | Evidence and remaining differences |
|---|---|---|---|---|---|
| A1 | `vHome` | 121–254 | `/` `Overview.tsx` | Implemented · dark checked on staging | Chart added (was missing). Checked at 1536 CSS px, dark. Pending: 1280/1440, light theme |
| A2 | `vModels` | 255–312 + script 2485 | `/affiliates` `Affiliates.tsx` | Implemented · dark checked on staging | Filters corrected to Active/Applications/Invitations/Inactive; invitations as rows. Header overlap and the amber *No update yet* fixed after the staging check |
| A3 | `vProducts` | 313–373 + script 2580 | `/products` `Products.tsx` | Implemented · dark checked on staging | Three filters, coverage bar, Active pill, pager. *All products* and paging exercised on staging |
| A4 | `vTargets` | 465–525 | `/targets` `Targets.tsx` | Implemented · dark checked on staging | §T. Checked at 1536 CSS px, dark; element sizes measured. Pending: 1280/1440, light, a save and a confirm exercised |
| A5 | `vPayments` | 526–597 | `/payments` `Payments.tsx` | Implemented · dark checked on staging | §P. Card 101 vs export 101px, row 82 vs 84px. Pending: 1280/1440, light, Record/Open actions exercised |
| A6 | `vSettings` | 598–786 + script 3515 | `/settings` `Settings.tsx`, `DataPanel.tsx` | Team and Shopify implemented; Historical, Brand codes, Reference mapped | Rail, Team (staff, invite row, pending invitations with Resend) and Appearance switch done. Shopify and sync: store card, Connection card, operations behind *Technical detail*; *Read the catalogue* stands in for the export's *Refresh now*, which has no single backend act. Historical setup lacks the export's *Earliest terms* and *State* columns (not in the roster payload) and its bulk *Review months* button (no such operation). Reference: title renamed *Policy in force*; the version editor and activity filter are kept |
| A7 | `vOrders` | 1060–1091 + script 3010 | `/orders` `Orders.tsx` | Implemented · dark checked on staging | Five columns, counted line, load-more. A row opening its order exercised on staging |

## B. Admin — secondary views

| # | Export view | Lines | Route / component | Status | Note |
|---|---|---|---|---|---|
| B1 | `vModel` | 787–1059 + script 2870 | `/affiliates/:id` `AffiliateDetail.tsx` | Implemented, not yet seen on staging | Hero, section tabs with the month always beside them, Overview's three figures and *Current terms*; Wardrobe as received pieces and a not-yet list; Performance as her orders (new `GET /api/affiliates/{id}/orders/{month}`); Targets and Payments as month-by-month tables (new `GET /api/affiliates/{id}/record`). Kept: code verification, start month, shipping edit, codes form, corrections panel, rules preview. The embedded Targets editing grid is replaced by the export's read-only table and a link to Targets |
| B2 | `vInvite` | 1232–1279 | `InviteModel.tsx` | Unreviewed | Not on a route of its own — check entry |
| B3 | `vProduct` | 374–464 | `/products/:id` `ProductDetail` in `Products.tsx` | Implemented, not yet seen on staging | Hero with state, sizes and coverage pills; feature request surface with Edit/Hide/Remove or *Ask models to feature this*; coverage groups that fold. The order reference per model the export prints is not in the product roster payload |
| B4 | `vPromo` | 1157–1231 | `/products/:id?view=promotion` `PromotionEditor` | Implemented, not yet seen on staging | Switch, audience, optional message (Save was wrongly disabled without one - D12), dark wardrobe preview with Received / On the way. The export's message presets are not built |
| B5 | `vShipment` | 1135–1156 | **none** | Unreviewed | No route exists |
| B6 | `vOrder` | 1092–1134 | `/orders/:orderId` `OrderDetail` in `Orders.tsx` | Implemented · checked on staging (DOM) | Route and `GET /api/orders/detail/{id}` are new. Screenshot capture failed on that tab; content read from the rendered page instead |
| B7 | `vPayment` | 1280–1402 + script 3171 | `/payments/:month/:affiliateId` `PaymentDetail.tsx` | Implemented · dark checked on staging | New `GET /api/payroll/{month}/statement/{id}`; approval from the page with the 05B fingerprint. Blocked month checked on staging; an approved month with transfers not yet seen on staging data |
| B8 | `vRecord` | 1403–1445 + script 3270 | `/payments/:month/:affiliateId/record` `PaymentRecord.tsx` | Implemented | Returns to B7. Not exercised on staging (no approved month with money owed there) |
| B9 | `vReceipt` | 1446–1461 + script 3314 | `/payments/:month/:affiliateId/receipts/:paymentId` `PaymentReceipt` | Implemented | *Recorded by* left out: the ledger payload does not carry it |
| B10 | `vCorrection` | 1462–1513 | `/payments/:month/:affiliateId/correction` `PaymentCorrection.tsx` | Implemented, deployed, not exercised | Order reference and failure date are not in the corrections payload, so the lead line names the month instead. `/reconcile` stays for overpaid months |
| B11 | `vTerms` | 1514–1604 + script | `/affiliates/:id/compensation` `Compensation.tsx` | Implemented · dark checked on staging | Two surfaces, a year of twelve tiles, *Apply to N months* is the save. Kept: met/missed for a guarantee month before go-live (ADR 0036), the list of months still missing something. An apply not yet exercised on staging |

## C. Admin — routes we ship that the export does not draw

Each needs a decision: fold into the nearest approved pattern, or remove.

| Route | Component | Disposition |
|---|---|---|
| `/payroll` | `Payroll.tsx` | Superseded by `vPayments` — candidate for removal |
| `/payroll/:month/approve` | `PayrollApprove.tsx` | Approval lives inside `vPayment` in the export |
| `/payroll/:month/reopen` | `PayrollReopen.tsx` | Reopening is retired (05B) — candidate for removal |
| `/affiliates/:id/payments` | `AffiliatePayments.tsx` | The export puts this inside `vModel` |
| `/affiliates/:id/payout-destination` | `AffiliatePayout.tsx` | The export puts this inside `vModel` |
| `/glossary` | `Glossary.tsx` | Later addition; keep, place per the shell |

## D. Portal — tabs

| # | Export flag | Lines | Route / component | Status |
|---|---|---|---|---|
| D1 | `onHome` | 102–212 | `/` `MyMonth.tsx` | Implemented · **visual check blocked** (needs a model session). Export's four states (*in progress / approved / payment recorded / settled*), hero label following them, chart readout of month, figure and what the figure is, and the payment card. Only the ledger may say *payment recorded*; the export's "usually recorded in N days" is not promised on HBA's behalf |
| D2 | `onOrders` | 213–256 | `/orders` `MyOrders.tsx` | Implemented · **visual check blocked**. Commission leads, sale underneath; wrapping filter chips with counts; state pill per row; expansion keeps our contents list and the sentence. Third filter is *Not counted*, not *Failed* — ours folds cancelled and refunded in |
| D3 | `onWardrobe` | 257–327 | `/wardrobe` `MyWardrobe.tsx` | Implemented · **visual check blocked**. Best sellers, feature requests, wardrobe, *Not received yet* in the export's order; the three states now carry their own tone. Subtitle says delivered only (05A) |
| D4 | `onTargets` | 328–377 | `/targets` `MyTargets.tsx` | Implemented · **visual check blocked**. *Content record*, who keeps it and when, the live month on a raised card, history as a list with a state pill. Keeps a third word the export lacks: *not recorded* is not *not met* (§11.3) |
| D5 | `onRanking` | 378–417 | `/ranking` `MyRanking.tsx` | Implemented · **visual check blocked**. Position card and board to the export, without the names, codes and avatars it prints for other models |

## E. Portal — secondary views

| # | Export view | Lines | Route / component | Status |
|---|---|---|---|---|
| E1 | `vYou` | 418–467 | `/you` `MyYou.tsx` | Implemented · **visual check blocked**. Hero, *Your arrangement*, Appearance seg, rows that each open one thing, sign-out behind a question. `GET /api/me` now carries `arrangement` and `since` |
| E2 | `vEarnings` | 468–512 | `/earnings` `MyCalculation.tsx` | Implemented · **visual check blocked**. Month and state pill shared with Home, lines and their total in one card, the amber *why this differs* card, and the rule at the foot — delivered only, with the rate from the server |
| E3 | `vPayments` | 513–554 | `/payments` `MyPayments.tsx` | Implemented · **visual check blocked**. *Approved, payment not yet recorded* card per unpaid month, *Recorded payments* rows titled by the month they paid. Keeps the outstanding figure, the month-by-month reconciliation and *Changes without a transfer*, which the export has no equivalent of |
| E4 | `vReceipt` | 555–571 | the expanded transfer row in `MyPayments` | Difference kept: the receipt opens in place rather than on its own view — every field the export's receipt shows is already on the row, and the screenshot is one press away |
| E5 | `vPayout` | 572–660 | `/you/payout` `MyPayout.tsx` | On its own route now, reached from You. Panel itself unreviewed — it keeps §6.4's two steps and the password at the point of committing, which the export does not draw |
| E6 | `vDetails` | 661–673 | `/you/details` `ShippingAddress` in `MyDetails.tsx` | On its own route now. Fields and wording unreviewed |
| E7 | `vSizes` | 674–689 | `/you/sizes` `Measurements` in `MyDetails.tsx` | On its own route now. Fields and wording unreviewed |
| E8 | `vNotify` | 690–705 | `/you/notifications` `Notifications` in `MyDetails.tsx` | On its own route now. Two switches, not the export's three — an alert per counted order is an email an order |
| E9 | `vBest` | 706–724 | `/best` `MyBestSellers` in `MyWardrobe.tsx` | Implemented, needs a model sign-in to see | New `GET /api/me/best-sellers`: her own delivered sales by product, never programme totals. The export counts pending orders too; that is 05A's preview, not the live rule |
| E10 | `vHelp` | 725–738 | **none** | Unreviewed |

## F. States the export draws separately

| State | Where | Status |
|---|---|---|
| Targets: `Record achieved` vs `Set requirements` | `tgModeAchieved` / `tgModeRequired` | Mapped |
| Targets: unsaved / discard / saved flag | `tgDirty`, `tgSavedFlag` | Mapped |
| Targets: error banner | `tgError` | Unreviewed |
| Targets: empty search | `tgEmpty` — "No model matches that search." | Mapped |
| Payments: estimated total | `payEstimated` pill | Mapped |
| Payments: settled month | `paySettled` | Unreviewed |
| Payments: empty | `payEmpty` | Mapped |
| Home: hidden notices | `hasHidden` / `unhide` | Unreviewed |
| Portal: month picker open | `showPicker` / `pickerOpen` | Unreviewed |
| Portal: order expanded | `o.open` | Implemented — contents, then the sentence saying what happened to the order |
| Portal: guarantee explainer | `showGuaranteeInfo` / `guaranteeOpen` | Difference kept: the sentence stays in the open on Targets rather than behind an ⓘ |
| Portal: sign-out confirm | `confirmSignOut` | Implemented on You |
| Portal: payout method | `mInsta` / `mWallet` / `mBank`, `instaHelp` | Unreviewed |
| Every list | loading, empty, retry | Unreviewed |

---

## The palette, verbatim from the export

Declared once at the top of `Admin Dashboard.dc.html` on `.ad`, and
byte-identical in the portal export. `tokens.css` already carries the neutral
ramp correctly; the accent names are what drifted.

| Name | Dark | Light |
|---|---|---|
| `--bg` | `#08090A` | `#EFF1EE` |
| `--surf` | `#15171A` | `#FFFFFF` |
| `--raise` | `#1D2126` | `#FFFFFF` |
| `--txt` | `#ECEFEA` | `#101214` |
| `--mut` | `#A7ADA6` | `#4E534E` |
| `--faint` | `#8A918A` | `#5E645E` |
| `--div` | `#23272B` | `#DDE1DC` |
| `--line` | `#2D3237` | `#C9CEC8` |
| `--acc` | `#23A95C` | `#14653A` |
| `--accsoft` | `rgba(35,169,92,.14)` | `rgba(20,101,58,.09)` |
| `--acctext` | `#7BE0A6` | `#14653A` |
| `--amber` | `#E0A458` | `#8A5A16` |
| `--ambersoft` | `rgba(224,164,88,.12)` | `rgba(138,90,22,.1)` |
| `--red` | `#E2705F` | `#9A2F22` |
| `--redsoft` | `rgba(226,112,95,.12)` | `rgba(154,47,34,.1)` |
| `--bar` | `#343A3F` | `#C9CEC8` |

`--acc` is the accent as a **surface, border and focus ring**. `--acctext` is
the accent **as text** — and in dark it is the lighter `#7BE0A6`, not
`#23A95C`. The one exception in the export is `.seg-opt:has(input:checked)`,
which uses `--color-accent` (`#23A95C`) for both its text and its inset ring.

---

## §T — `vTargets`, measured (lines 465–525)

Toolbar — one flex row, `justify-content:space-between`, `gap:16px`, wraps.

* Left group, `gap:9px`: search `<input>` **240 × 38**, `padding:10px 12px`,
  `1px solid var(--div)`, radius **8**, background `var(--surf)`, **13.5px**,
  placeholder `Search model names`.
* Then `.seg` — `inline-flex`, `1px solid var(--div)`, radius 8, overflow
  hidden. Two `.seg-opt` labels, `padding:7px 12px`, **13px**, divided by
  `1px solid var(--div)`. Checked: `color:#23A95C` and
  `box-shadow: inset 0 0 0 1px #23A95C`. Measured: seg 259 × 36, option
  127 × 34. Copy: **`Record achieved`**, **`Set requirements`**.
* Right group, `gap:9px`: when dirty, an amber **12.5px** line then a
  `Discard` button (38 min-height, `padding:9px 13px`, 13px); when just saved,
  a `var(--acctext)` 12.5px line; then **`Save changes`** — 38 min-height,
  `padding:9px 15px`, **13.5px**, radius 8, border and background driven by
  whether it is enabled.

Table surface — `margin-top:16px`, radius 8, `background:var(--surf)`,
`overflow:hidden`. There is no outer border.

* Header row: `padding:10px 18px`, `gap:16px`, **11px**,
  `letter-spacing:.06em`, uppercase, `color:var(--faint)`,
  `border-bottom:1px solid var(--div)`.
* Columns: Model `flex:1;min-width:190px` · videos **150** · stories **150** ·
  Recorded **140** · Last updated **120**.
* Body row: `padding:10px 18px`, `gap:16px`, `border-bottom:1px solid var(--div)`.
* Name is a **button**, 13.5px, `color:var(--txt)`; the arrangement follows it
  **on the same line**, 12px, `var(--faint)`.
* Each number is an `<input>` **56px wide**, 36 min-height, `padding:8px 9px`,
  radius **4**, `background:var(--bg)`, centred, 13.5px — with `of N`
  **beside** it, `gap:8px`, 12.5px `var(--faint)`.
* Recorded: one line, 12.5px, tone from state.
* Last updated: one line, 12.5px, tone from state.
* Empty: `padding:34px 18px`, centred, 13.5px `var(--mut)`,
  **`No model matches that search.`**

Page subtitle for this view is **`{month} · recorded weekly`**.

**What we ship instead** (staging, 12 September):

1. `Save changes` sits at the **bottom left**, not top right.
2. A `Choose whose numbers to confirm` button and a three-sentence paragraph
   sit below the table. Neither is in the export.
3. Both modes are shown at once — there is no `.seg`; the export has one grid
   and a mode switch.
4. Number inputs are full-column width with `of N` **underneath**.
5. The Recorded column carries **three stacked lines**; the export has one.
6. A `1 model is held up this month.` line sits where the export puts
   `Save changes`.
7. The arrangement is missing beside the model name.
8. No search, no dirty count, no Discard.

## §P — `vPayments`, measured (lines 526–597)

Three cards — `display:flex`, `gap:14px`, wrap. Each is
`flex:1 1 240px`, `padding:16px 18px`, radius 8,
**`background:var(--surf)`** — three separate surfaces, not one strip.

* Label 12.5px `var(--mut)`. Value `font-family:var(--font-heading)`,
  **27px**, `margin-top:8px`, `font-variant-numeric:tabular-nums`.
* Card 1 `Total required`, with an optional `Estimated` pill —
  `padding:2px 8px`, radius 999, `1px solid var(--amber)`, 11px, amber.
* Card 2 `Recorded so far`, value in `var(--acctext)`.
* Card 3 `Remaining to send`, value tone by state.
* **No sub-line under any card.**

Filter row — `margin-top:18px`, space-between, wraps. Filter buttons
`gap:7px`, 36 min-height, `padding:8px 13px`, 13px, radius 8, border /
background / tone by selection. Search input on the right, **240 × 38**,
placeholder `Search model names`.

Table surface — `margin-top:14px`, radius 8, `background:var(--surf)`.

* Columns: Model `flex:1;min-width:180px` · To receive **130** ·
  Destination **210** · State **150** · Next action **130**.
* Row `padding:11px 18px`, `gap:16px`.
* Model is a button, 13.5px, with terms **below** it — `display:block`,
  12px, `var(--faint)`, `margin-top:3px`.
* To receive: 13.5px tabular; when something is recorded, a second line
  `display:block`, 12px, `var(--acctext)`, `margin-top:3px`.
* Destination: 12.5px `var(--mut)`, ellipsised, then a `Copy` button —
  30 min-height, `padding:5px 8px`, radius 4, 11.5px, `color:var(--faint)`.
* State: a **pill** — `padding:3px 9px`, radius 999, `1px solid` the state
  tone, 11.5px, same tone.
* Next action: a button, 34 min-height, `padding:7px 11px`, radius 8,
  transparent, 12.5px, tone by state.
* Empty: `padding:34px 18px`, centred, 13.5px `var(--mut)`.
* Settled month: a bordered note, `margin-top:14px`, `padding:14px 16px`,
  13px `var(--mut)`.

**What we ship instead** (staging, 12 September):

1. One flat strip with vertical dividers, not three rounded surfaces.
2. Each card carries an invented sub-line
   (`E£0.00 approved · E£22,347.00 forecast.`, `Actual transfers in this
   month's ledger.`, `0 models are waiting.`).
3. Value size and face do not match (heading face, 27px).
4. The search sits in its own bordered panel labelled `Find a model`; the
   export has a bare input labelled `Search model names`, and it is on the
   **right of the filter row**, not below it.
5. State is two lines of prose — `Forecast — not agreed` plus
   `Review the moving figure before it becomes money HBA owes.` The export
   draws a single pill.
6. The action reads `Review and agree`; the export's are `Review`,
   `Record payment`, `Open`.
7. Terms line and recorded line are present but their sizes and tones differ.

---

## Differences kept on purpose

Each one is a later decision or a real state the export's sample data never
reached. Nothing else is a legitimate difference.

| Screen | Kept | Why |
|---|---|---|
| Targets | *Confirm* button and a tick in the Model column | Target confirmation is an approved later capability |
| Targets | *Whole year* checkbox beside Save | Owner, 11 September 2026: targets are fixed across a year |
| Targets | A second, quieter pace line under Recorded | D08, asked for after the export was drawn |
| Payments | *Settle difference* action | Overpaid months exist; the export never drew one |
| Payments | The list shows the masked destination; *Copy* and the payment view's *Show where to send it* fetch the real value | ADR 0028: the full number is gated on recording payments and every reveal is audited. The export prints it outright |
| Home | Chart axis label inside the plot | Real totals are wider than the export's gutter |
| Models | Table/Cards switch, *Add a house code* | §12.3 asked for the toggle; house codes are a real account kind |
| Models | Resend/Withdraw under an invitation's date | No invitation view exists yet to hold them |
| Orders | *Cancelled* status; Enter looks an order up in any month | Shopify cancels orders; support asks by number |
| Products | Size count under the name instead of a SKU | A SKU belongs to a size, not a product; search still finds SKUs |
| Products | Top sellers panel, below the catalogue | Built later from the owner's question; **open: confirm it stays** |
| Everywhere | `E£`, not `EGP` | Owner decision |
| Portal Home | The order chips are links into a filtered Orders list | The question a chip raises is *which ones*, and the answer is one screen away |
| Portal Home | No "payment usually recorded in N days" | The export's schedule is its demo's; HBA has promised no date, and a portal that invents one is a support message |
| Portal Orders | Third filter is *Not counted*, not *Failed* | Ours folds cancelled and refunded in with failed delivery; calling a cancelled order a failed delivery describes something that never happened |
| Portal Targets | The sentence about her pay stays in the open, not behind an ⓘ | On a guaranteed minimum it says whether these two numbers are about to decide her pay |
| Portal Targets | A third word for a month: *not recorded* | §11.3. A month nobody has counted is not a month she missed, and it is the state that holds a guarantee up |
| Portal Ranking | Other models are unnamed — no name, code or avatar | The export prints all three for everybody; a leaderboard that names twenty colleagues is a public table none of them agreed to |
| Portal Wardrobe, Best sellers | Delivered orders only, and the subtitle says so | 05A's pending-inclusive counting is a read-only preview, not what she is paid on |
| Portal You | *Payment details* keeps its two steps and the password | §6.4, the highest-risk change she can make. The export saves it in one press |
| Portal shell | Back returns where she came from, not to Home | Always-Home threw away her place coming out of All products sold and the payment detail |
| Portal Payments | The receipt expands in the row instead of opening its own view | Every field the export's receipt view shows is on the row already; a second screen would be a navigation step to see the same four lines |
| Portal Payments | *Month by month* and *Changes without a transfer* kept | §11.5 and 05C: a write-off or a carried correction is where a month settles without a transfer, and a model who cannot see it cannot close her own arithmetic. The export's sample data has neither |

## Blockers

**Every portal row is built and none has been seen on screen.** Checking one
means signing in as a model, and doing that in this browser signs the admin
out of the session the maintainer screens were verified in. What is needed is
a second browser profile signed in as a test model, or word that signing the
admin out here is fine. Until then the D and E rows say *visual check
blocked*, and they are not claimed as verified.

The docker-compose test database that stopped on 15 September was restarted
the same day; the full suite has run since.

## Evidence

Screenshots live in `docs/redesign/parity/shots/`, named
`<view>-<width>-<theme>-{ref,app}.png`. A row may not reach
`Visually verified` without a matched pair in that directory.
