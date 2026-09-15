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
| A2 | `vModels` | 255–312 + script 2485 | `/affiliates` `Affiliates.tsx` | Implemented, not deployed | Filters corrected to Active/Applications/Invitations/Inactive; invitations as rows. Backend test run blocked (see Blockers) |
| A3 | `vProducts` | 313–373 + script 2580 | `/products` `Products.tsx` | Implemented, not deployed | Three filters, coverage bar, Active pill, pager. Backend test run blocked |
| A4 | `vTargets` | 465–525 | `/targets` `Targets.tsx` | Implemented · dark checked on staging | §T. Checked at 1536 CSS px, dark; element sizes measured. Pending: 1280/1440, light, a save and a confirm exercised |
| A5 | `vPayments` | 526–597 | `/payments` `Payments.tsx` | Implemented · dark checked on staging | §P. Card 101 vs export 101px, row 82 vs 84px. Pending: 1280/1440, light, Record/Open actions exercised |
| A6 | `vSettings` | 598–786 | `/settings` `Settings.tsx` | Mapped | Not yet re-read under the script-reading method |
| A7 | `vOrders` | 1060–1091 + script 3010 | `/orders` `Orders.tsx` | Implemented, not deployed | Five columns, counted line, load-more. Backend test run blocked |

## B. Admin — secondary views

| # | Export view | Lines | Route / component | Status | Note |
|---|---|---|---|---|---|
| B1 | `vModel` | 787–1059 | `/affiliates/:id` `AffiliateDetail.tsx` | Unreviewed | Five sections: Overview, Wardrobe, Performance, Targets, Payments |
| B2 | `vInvite` | 1232–1279 | `InviteModel.tsx` | Unreviewed | Not on a route of its own — check entry |
| B3 | `vProduct` | 374–464 | `/products/:id` `ProductDetail.tsx` | Unreviewed | |
| B4 | `vPromo` | 1157–1231 | inside product detail? | Unreviewed | Promotion / feature-request editor |
| B5 | `vShipment` | 1135–1156 | **none** | Unreviewed | No route exists |
| B6 | `vOrder` | 1092–1134 | `/orders/:orderId` `OrderDetail` in `Orders.tsx` | Implemented, not deployed | Route and `GET /api/orders/detail/{id}` are new |
| B7 | `vPayment` | 1280–1402 + script 3171 | `/payments/:month/:affiliateId` `PaymentDetail.tsx` | Implemented · dark checked on staging | New `GET /api/payroll/{month}/statement/{id}`; approval from the page with the 05B fingerprint. Blocked month checked on staging; an approved month with transfers not yet seen on staging data |
| B8 | `vRecord` | 1403–1445 + script 3270 | `/payments/:month/:affiliateId/record` `PaymentRecord.tsx` | Implemented | Returns to B7. Not exercised on staging (no approved month with money owed there) |
| B9 | `vReceipt` | 1446–1461 + script 3314 | `/payments/:month/:affiliateId/receipts/:paymentId` `PaymentReceipt` | Implemented | *Recorded by* left out: the ledger payload does not carry it |
| B10 | `vCorrection` | 1462–1513 | `/payments/:month/:affiliateId/correction` `PaymentCorrection.tsx` | Implemented, not deployed | Order reference and failure date are not in the corrections payload, so the lead line names the month instead. `/reconcile` stays for overpaid months |
| B11 | `vTerms` | 1514–1604 | `/affiliates/:id/compensation` `Compensation.tsx` | Unreviewed | Compensation history and month selection |

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
| D1 | `onHome` | 102–212 | `/` `MyMonth.tsx` | Unreviewed |
| D2 | `onOrders` | 213–256 | `/orders` `MyOrders.tsx` | Unreviewed |
| D3 | `onWardrobe` | 257–327 | `/wardrobe` `MyWardrobe.tsx` | Unreviewed |
| D4 | `onTargets` | 328–377 | `/targets` `MyTargets.tsx` | Unreviewed |
| D5 | `onRanking` | 378–417 | `/ranking` `MyRanking.tsx` | Unreviewed |

## E. Portal — secondary views

| # | Export view | Lines | Route / component | Status |
|---|---|---|---|---|
| E1 | `vYou` | 418–467 | `/you` | Unreviewed |
| E2 | `vEarnings` | 468–512 | `/earnings` `MyCalculation.tsx` | Unreviewed |
| E3 | `vPayments` | 513–554 | `/payments` `MyPayments.tsx` | Unreviewed |
| E4 | `vReceipt` | 555–571 | inside `MyPayments` | Unreviewed |
| E5 | `vPayout` | 572–660 | `MyPayout.tsx` | Unreviewed |
| E6 | `vDetails` | 661–673 | `MyDetails.tsx` | Unreviewed |
| E7 | `vSizes` | 674–689 | part of `MyDetails`? | Unreviewed |
| E8 | `vNotify` | 690–705 | **none** | Unreviewed |
| E9 | `vBest` | 706–724 | **none** — personal top sellers | Unreviewed |
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
| Portal: order expanded | `o.open` | Unreviewed |
| Portal: guarantee explainer | `showGuaranteeInfo` / `guaranteeOpen` | Unreviewed |
| Portal: sign-out confirm | `confirmSignOut` | Unreviewed |
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

## Blockers

- **The backend test suite can't run.** The test database is the
  docker-compose PostgreSQL on port 5433, and Docker Desktop stopped during a
  low-memory kill on 15 September. Commit `da243ff` (Models, Orders, Products)
  is committed locally and not pushed until the suite passes.

## Evidence

Screenshots live in `docs/redesign/parity/shots/`, named
`<view>-<width>-<theme>-{ref,app}.png`. A row may not reach
`Visually verified` without a matched pair in that directory.
