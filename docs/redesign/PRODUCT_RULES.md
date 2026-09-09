# Canonical product rules

This is the current instruction set synthesized from the owner's decisions and final designs. IDs in this file are local to this package; older discovery documents may use different IDs. An HTML calculation, fixture, role label or date is not an approved business rule.

## Scope and design

| ID | Requirement |
|---|---|
| S01 | Redesign the **whole** model and admin experience in the existing application. Admin is primarily laptop; models primarily phone. |
| S02 | Admin top-level tabs: Home, Models, Products, Targets, Payments, Settings. Secondary destinations retain all necessary existing operations without adding top-level clutter. |
| S03 | Model tabs: Home, Orders, Wardrobe, Targets, Ranking. You/account opens profile, payout details, payment history, receipts, help, notifications and theme. |
| S04 | Preserve final Claude black/green design and restrained text. No new dashboard redesign, decorative filler, hardcoded sample metrics or teaser-video inflated numbers. Both themes work. |
| S05 | Owner, marketing and finance describe use cases. Do not create new roles or grant financial access just because prototype labels say Marketing or Finance. Map existing server permissions first. |
| S06 | Loading, empty, search-no-results, unavailable, stale and save-error states have distinct meanings. A failed request must never display as zero earnings, no products or no payments. |
| S07 | Preserve selection, filters, month and useful return location across related pages. Deep links, reload, browser Back and keyboard/mobile interaction work. Approved-month editing cannot be re-enabled by navigating directly to an old route. |

## Owner, marketing and finance

| ID | Requirement |
|---|---|
| A01 | Home shows model-generated sales, expected payout, fixed salaries, commissions, necessary guarantee top-ups/deductions, active model count, top three by generated sales, and content progress needing review. Forecast, approved amount and remaining transfer amount must be labelled distinctly. |
| A02 | Missing content input is not poor performance. Display recorded videos/stories against requirements and last recorded time. A weekly underperformance threshold has not been agreed; do not invent one. |
| A03 | Models is a directory with concise summaries and one shared profile reached from directory, product roster, targets and payments. The profile has Overview, Wardrobe, Performance, Targets and Payments as in the design. Financial subviews have their own visible month context. |
| A04 | Keep invitations, applications, accepting/approving models, code association/verification/replacement, inactive/archive history and house-code administration accessible. Application approval must use existing validated setup, not a fixture status toggle. |
| A05 | Marketing needs phone, contact/email and shipping information, product sizes and optional height/weight. Measurements are supplied optionally at application and edited only by the model later; admins can read them, not change them. Missing measurements do not block submission. |
| A06 | Targets distinguish monthly requirements from cumulative achieved counts updated weekly. Saving requirements does not overwrite achievements. Unrecorded, zero, met, missed and verified are separate facts. Model target views are read-only. |
| A07 | Payments answers total funds required, who receives money, how much and where to send it. Transfers happen outside HBA; opening InstaPay does not mean a transfer occurred. |
| A08 | Authorized payers see complete bank/card details, account holder, wallet provider/number, or InstaPay number **and the exact submitted link**, with working copy controls. Provide Open InstaPay using that link. Keep destination values out of generic logs and unrelated model payloads. |
| A09 | Settings retains relevant team/invite/status controls, Shopify/sync health and retry, historical setup, house codes, appearance, policy/reference and audit/support functions. No fake credential editing or pretend successful connection. |
| A10 | Home remains a business overview. Supporting notices are dismissible pop-ups: temporary hide can return; item-specific mute persists; resolving the issue clears it; neither hide nor mute resolves it. A notice for one record opens that record; a multi-record notice opens a relevant filtered list. |

## Products, orders sent to models, wardrobe

| ID | Requirement |
|---|---|
| W01 | Catalogue defaults to active products; All products includes accessible draft/archived products. Keep historical wardrobe items accessible if no longer sold. Use Shopify product/variant IDs; colour belongs in the product name, with size as the variant. No separate colour taxonomy/filter. |
| W02 | Opening a product opens its own model roster. Default groups, in order: Received, Processing, Needs checking, Not sent. Names alphabetical inside groups, with model search. Keep rows concise: model link and Shopify order reference. No collection checklist or unnecessary duplicate status/size/quantity/date columns. |
| W03 | Shipping-address phone identifies the recipient; Shopify customer identity may be Mena's. Do not match against customer phone/email instead. Normalize numbers, report ambiguous/missing matches, and preserve verified historical order links across phone changes. |
| W04 | Once matched, original zero net sales classifies a gift; original positive net sales classifies a personal purchase. A later cancellation must not reclassify a purchased order as a gift. Unknown original value remains unknown. Positive-purchase wardrobe inclusion is D05. |
| W05 | Backfill from January 2026 and perform live matching; a model joining the platform later can acquire links to earlier orders. Read historical matching data once/index or page it; do not assume Shopify supports arbitrary shipping-phone search or fetch the entire store on every profile load. |
| W06 | Store each matched shipment and its line items internally. One shipment may contain many products; its status applies to each. The normal replacement updates the latest relevant shipment for each product/model pair, preserving earlier history. If only pants are resent, a previously failed T-shirt stays Needs checking. |
| W07 | No order creation, editing, cancellation or blocking in Shopify from this app. Multiple orders are allowed. No direct courier integration and no split-shipment workflow in V1. This dashboard monitors Shopify. Do not invent arrival estimates absent authoritative data. |
| W08 | Wardrobe shows Received products with images and sizes, then a compact Not received yet area for processing and failed gifts. Failed products must not look owned. Product and model views use the same records. Inactivation does not erase wardrobe or past performance. |
| W09 | Product feature requests are passive guidance, separate from targets. Marketing can create/update a request and make it visible, hide or remove it. No model Done button, acknowledgement, completion tracking or automatic target change. |
| W10 | A visible feature request is shown to a model only when that model has Received or Processing for that product. Not sent and failed-only models do not see it. Eligibility is evaluated by the server and changes with current shipment state; an empty eligible section disappears. |
| W11 | Products selling through a code, wardrobe ownership and requested promotion are three different concepts. A model can sell products they never received. Top-seller analytics must use real attributed line items and discounts/quantities, not item name/undiscounted price sums. |
| W12 | Backfill incomplete is not proof a product was never sent. Preserve an internal completeness state, show concise incomplete/stale information where needed, and provide a bounded staff path to resolve unmatched data. This is not a new courier/replacement-management product. |

## Sales, compensation and settlement

| ID | Requirement |
|---|---|
| F01 | Shopify is the delivery-status authority: Delivered → Delivered; final failed delivery → Failed delivery; other available delivery states → Pending. Fulfilled/shipped is not Delivered. Do not depend on the cancellation automation to exclude a failed delivery. Null because access/sync failed is a data error, not a trustworthy new status. |
| F02 | Orders attributed through a model's code count in sales and payable commission when Pending or Delivered. Pending → Delivered never earns twice, even after approval/payment. Remove the old late-delivery carry-forward mechanism for the new policy. |
| F03 | Failed delivery is excluded. Display known commission/sales struck through with Failed delivery; missing original figures may be unavailable, never fabricated. Customer personal details are absent from model order payloads, not just hidden with CSS. |
| F04 | Post-delivery returns, refunds and exchanges do not reduce counted sales/commission under HBA's policy. Keep the financial basis needed to maintain this. Historical orders first seen after such changes can lack an authoritative original basis; report that limitation instead of silently inventing one. |
| F05 | Continue the existing order-level commission basis: customer total after discounts minus shipping and tax, bounded at zero. Keep integer piastres and basis-point rates, exact arithmetic, multiply before dividing, aggregate before final rounding. Preserve the repo's whole-pound half-up payout rule unless D02 explicitly changes it. Individual display rounding cannot drive payroll. |
| F06 | Commission-only = commission. Fixed-plus-commission = fixed amount **plus** commission. Guaranteed minimum = max(commission, minimum) when the month's targets qualify; otherwise commission. Only guarantee depends on targets. Unknown qualifying information blocks a final guarantee decision; it is not an assumed failure. Preserve the existing verification requirement until explicitly changed. |
| F07 | Approval is per model/month. It freezes the terms, target outcome/evidence, approved financial basis, earnings and accepted deduction allocations before the external transfer. No reopening in V1. Read-only prior snapshots, transfers and existing audit history remain available. |
| F08 | Payment records what was actually transferred: amount, time/reference, destination snapshot and genuine proof where supplied/required. No fabricated historical transfer, generated payment proof, negative transfer or success based only on opening an external payment link. Reuse existing idempotency, append-only and proof ownership protections. |
| F09 | A failed order after approval creates a correction for staff review, including when a transfer has not yet been recorded. Staff chooses HBA absorbs or carries a deduction forward. Dismissing a notice is not choosing. No automatic deduction before that choice. |
| F10 | Compute the recoverable difference from the **source month's entitlement**, using its frozen terms and qualifying target outcome. Example: commission EGP 2,100 → 1,900, minimum 2,000: recover 100 if targets qualified, 200 if missed. Do not recover the raw 200 in both cases. |
| F11 | Multiple failures for one approved source month must share its cumulative entitlement correction; do not apply the full month-level difference once per order. Used/absorbed/remaining amounts are tracked so retries and later failures cannot double-deduct. |
| F12 | A carry deduction reduces a destination month's payable amount, not its own sales. Fixed pay may be reduced. If earnings 100 and a chosen deduction 200, apply 100, transfer 0, retain 100 to carry later. Remainders persist across years without a four-month limit. Incoming recovery against a destination-month guarantee is D04. |
| F13 | The source month's current sales and sales graph reflect later failed orders. Its approved earnings and recorded payments remain unchanged. Destination month shows its own earnings plus a separate earlier-month deduction. Original order links to the actual settlement month; a proposed allocation must not be labelled already deducted. |
| F14 | Approved amount, current recalculated entitlement, funds still to transfer, actual payments and remaining correction balance are separate fields. Paid status derives from recorded settlement, not approval, a comparison to zero, or the current recalculated amount. |
| F15 | Normal payment day is around the third of the next month, not a guaranteed automatic transfer date. House accounts may have sales but are not models, do not receive compensation and do not enter model rankings. Inactive models can still have historical statements and unpaid obligations. |

## History, profile and model-facing analytics

| ID | Requirement |
|---|---|
| H01 | Model history starts January 2026 or their later real collaboration start month. Months before collaboration cannot be selected; legitimate zero-sales months after starting remain visible. Invitation date, code first order and platform signup are not interchangeable with collaboration start. |
| H02 | Recalculate old months with the same business rules and actual historical rates/arrangements. Old months look like new months. Admin enters rates, fixed amounts/minima and historical target outcomes; Shopify cannot establish those outcomes. If counts were not kept, show unknown counts rather than fabricating videos/stories. |
| H03 | Existing pre-platform months were already settled externally. Do not import scattered historic transfer proofs, manufacture payment rows, create opening debt or double-pay those months. Payments may say “No payments recorded here for this month.” Preserve any real existing platform transfers separately. Actual boundary/cohort is D01. |
| H04 | Edit terms using a month grid with year choice and Select all editable months. Save selected months together, stay in the editor, then allow another selection/type. January/February commission, March/April salary-plus-commission, etc. Unselected months unchanged. Mixed selections explicit. |
| H05 | Monthly term assignment is one validated transaction. Split/merge stored effective periods as needed while retaining approved references and immutable evidence. Live approved months are locked even if unpaid. Historical setup months remain editable until finalization; settled externally and approved live are not the same edit policy. |
| H06 | Historical readiness checks every eligible month for term coverage, required target outcomes and data completeness. A first terms record or a clicked Reviewed button does not prove readiness. Finalization is idempotent with an audit trail and no invented receipts. |
| M01 | Home shows this month's earnings, sales, code uses and performance over the eligible year. Charts handle no months, one month, all zeroes, gaps and long histories; empty values are not NaN, missing facts not zero. Do not ship the prototype's fixed 2026 calendar or 10% assumption. |
| M02 | Ranking order is determined server-side by sales. Peer values shown are uses, not sales, commission or salary. Explain the sales ranking basis briefly without promising that matching another model's uses guarantees matching their rank. Code-use definition/ties/period are D03. |
| M03 | Profile changes persist only after successful validation/save. Cancel discards drafts. Keep current-password reauthentication for payout changes. Map contact email versus login identity deliberately; do not silently rename login credentials. |
| M04 | Model payment history and proof are self-owned. Open the selected payment's month/snapshot, including when another month is selected on Home. Preserve multiple/partial real transfers. Old receipt destination does not change when today's payout destination changes. |
| M05 | Two existing model email preferences: month approved/closed and payment recorded/sent. Map UI labels to existing backend kinds. They never disable security emails. Theme persists; FAQs/policy text must match the new rules. |

## Explicit exclusions

No month reopening; no deferred commission paid again on delivery; no Shopify order writes; no courier integration; no collection checklist; no model promotion completion workflow; no fabricated historical data; no automatic new team/role system; no automatic transfer initiation; no new advances, multi-month transfer UI, debt collection or full replacement-management module. Existing historical records of older workflows remain auditable.

## Superseded repository choices

Old portal red/old tab names → final black/green designs. Delivered-only payment → F02. Pending-to-delivered carry-forward → removed for new policy. Reopening workflow → removed. Effective-start-only terms editor → selected-month operation. History sales-only → full same-screen reconstruction with external settlement. Old global no-recipient-PII query design → retain PII-free commission index while adding separately protected shipping-recipient matching. Old deployment assumptions must be verified; this planning request is not permission to push both main and production.
