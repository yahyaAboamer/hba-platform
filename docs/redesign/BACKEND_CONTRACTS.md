# Integration contracts and data design

This document specifies required meanings and engineering constraints. New endpoint/table names below are **proposals**, not claims that the current repo has them. The coding agent should adapt names to the inspected app, document the final OpenAPI/schema contract, and avoid duplicate services.

## One data path for each fact

Shopify supplies orders, product/variant identity, product images and delivery facts. The HBA database supplies model identity/contact data, collaboration dates, code ownership periods, compensation terms, target evidence, promotion requests, approvals, correction choices and real payment records. Both dashboards read the same authoritative services. Prototype localStorage/mock arrays are not an alternative source of truth.

Keep these separate:

| Concept | Meaning and owner |
|---|---|
| Attributed customer sale | An order credited to a model's promotional code; commission path; no customer personal details exposed to models. |
| Shipment sent to a model | Recipient phone match and line items; wardrobe path; customer may be Mena. Different from sales attribution. |
| Current sales performance | Current counted sales for the order's original business month. |
| Approved statement | Immutable accepted earnings, terms, targets and deductions at approval. |
| Transfer | Money actually sent outside HBA, with its own amount/date/destination/evidence. |
| Correction balance | Chosen recoverable difference from a source statement and its allocations/absorption/remaining balance. |

## Contract common rules

- Money uses clearly suffixed integer `*_piastres`; rate uses integer `commission_rate_bp`. For editing a decimal input, parse with decimal arithmetic on the server. Never treat the customer's Shopify discount rate as the model's commission rate.
- API status and error codes distinguish loading failures, unknown values, blocked approval, stale version and missing data. Numeric `null` means unknown, not zero. Arrays/totals include pagination metadata and consistent filter scope.
- Return current business month and eligible month lists from the server, including cross-year dates. Use durable IDs, not names/array indexes, for models/products/orders/receipts and routing.
- Sensitive mutations are permission/ownership checked in the service/API, not merely disabled buttons. Use optimistic concurrency/version checks for forms and idempotency keys for retriable financial operations.
- Report success only after commit. A retry after timeout must recover the prior result or safely retry with the same key. No secrets in reports, URLs, browser bundles or broad audit JSON.

## Profiles and monthly terms

Extend the profile via additive migrations for actual collaboration start and optional height/weight; add contact/shipping fields after D07. Preserve identity/account linkage. Do not infer months from signup or first order. If pause/reactivation history exists, retain it; do not erase old eligible months on inactivation.

Proposed selected-month request, following the repo's compensation vocabulary:

```json
{
  "months": ["2026-01", "2026-02"],
  "compensation_type": "commission",
  "commission_rate_bp": 1200,
  "expected_revision": "server-returned-version",
  "idempotency_key": "client-generated-operation-id"
}
```

Salary requests add `fixed_amount_piastres`; guarantee requests add `base_amount_piastres`. Existing validation governs rate limits and permitted fields. Do not copy the prototype's inconsistent “1 to 100” text when fractional percentage rates are supported.

The service must validate the entire month set, eligibility, locks and input **before any change**, lock/version-check conflicting ranges, and perform one transaction. Split an existing January–December period when only March/April change, preserve all other months, and merge compatible adjacent ranges when appropriate. Keep references used by approved snapshots stable. A conflict in one selected month fails the whole edit; do not silently apply a subset or loop independent browser POSTs. Include selected months and before/after terms in appropriate audit records.

Historical setup needs readiness by month, with distinct facts for source completeness, compensation coverage, target outcome and finalization. Outcome-only history can be met/missed/unknown with attribution; it must not manufacture counts. Existing code supports monthly effective periods, so no mid-month prorating feature is implied by this design.

## Shopify ingestion and recipient matching

1. Verify the configured API version (baseline 2026-07), access scopes and actual field availability using a minimal read. Use the existing client/job retry behavior. Catalog and recipient access must not break the established commission ingestion path when a new field is denied.
2. Add paginated catalog/variant/media and order-line-item ingestion keyed by stable Shopify IDs. Cache the required product data locally; don't make a Shopify call per visible row. Preserve title/size/image evidence when a product is archived, renamed or removed. Deleted source media should have an honest visual fallback.
3. Extract `shippingAddress.phone` in a restricted recipient processing path. Do not add raw customer payloads or phones to the commission order index. Prefer normalized matching tokens/links with minimal raw retention; document how staff resolve legitimate unmatched cases and how historical aliases are verified. Do not claim an unkeyed phone hash anonymizes predictable phone numbers.
4. Match one unambiguous model; record provenance, original order ID and classification basis. Missing/redacted phone and shared/ambiguous numbers remain unresolved. A code or Mena's account can help investigation but is not the sole match rule. Phone changes preserve already linked orders.
5. Retain order/product line mappings, size and delivery facts independently of the storefront's current catalogue. Zero-original-net gift classification stays stable after cancellation. Positive purchases await D05 for wardrobe eligibility, without discarding their identity.
6. All live webhook, scheduled reconcile and history ingest paths are idempotent; out-of-order source updates cannot regress newer facts. Support pagination, retries, checkpoints and resumable backfill. Start/approve-model can enqueue a bounded matching job; profile rendering must not await an entire store scan.
7. Use Shopify fulfillment **delivery display/event facts**, not generic fulfilled/success statuses. Shopify may expose multiple fulfillment records even if HBA operationally ships whole orders; retain the tested extraction precedence or explicitly validate changes with real fixtures. No direct courier access.

Official references checked 9 September 2026: [Order query and historical access](https://shopify.dev/docs/api/admin-graphql/latest/queries/order), [protected customer data and phone/address access](https://shopify.dev/docs/apps/launch/protected-customer-data), [Fulfillment display status](https://shopify.dev/docs/api/admin-graphql/latest/enums/FulfillmentDisplayStatus). These document the access/status constraints, not HBA's granted permissions. Validate the deployed API version before changing queries. The workflow requires read access; do not request Shopify order-write access just to read older history.

## Wardrobe and feature requests

Suggested resources: catalogue list/detail; product-to-model roster; model/self wardrobe; matched shipment detail; product feature-request mutation. Exact routes can follow existing naming conventions.

Roster rows identify model, derived group, latest relevant order reference and internal history link. Counts cover the same eligible population and filters as the rows. The active operating roster may differ from a historical profile; it must not delete that profile's wardrobe.

The model response contains only that model's wardrobe and eligible requests. Request visibility is an intersection of enabled product request and that model's Received/Processing relationship. Filtering only in the browser would still expose requests to ineligible models through the API. When processing becomes failed-only, remove that request from that model's response; when the replacement enters Processing, show it again. Removing a request never removes ownership or targets.

Top sellers use attributed line items for counted orders. Respect quantity and after-discount values, and define allocation where order discounts span lines so totals reconcile. Do not reuse sum-of-listed-item-price prototype logic. Use product IDs to avoid combining distinct same-named products.

## Targets

Reuse monthly required, achieved and verification data. Separate patches for requirements and achieved totals; the UI may use a batch request but must communicate actual commit outcomes. Preserve null counts until recorded; zero is an intentional record. Save cumulative counts rather than adding last week's total again. An unknown guarantee target blocks final calculation, not commission-only/fixed compensation. Do not add a duplicate approval process if existing verification already serves that role.

Changes to targets used by an approved statement cannot rewrite its frozen outcome or create a hidden reopen. For later source-month recovery, use the frozen qualifying outcome. Historical met/missed evidence without counts is a distinct input mode.

## Financial calculation and correction records

Expose a single month view contract with at least these separate concepts:

```text
month / model / eligible / source completeness
performance: counted sales, delivered/pending/failed counts, code uses definition
current entitlement: commission, fixed amount, guarantee top-up, exact/final money
approval: snapshot ID/version, approved earnings, approved deductions, approved payable
settlement: amount actually paid, remaining transfer amount, settlement state
corrections: source month/order, decision, recoverable/applied/absorbed/remaining money
```

Field names are illustrative. Do not send peer sales in the ranking payload. The browser may format/chart authoritative values, but cannot recalculate payroll from an orders page which may be paginated.

Approval locks/rechecks source revision, terms, targets and selected correction allocations. Commit statement + chosen allocations together. If data changed since preview, refresh and show the changed facts before final approval; no silent acceptance of a different amount. Existing already-approved statements remain immutable.

A correction must have stable identity and source snapshot, contributing failure IDs, observed source revision, original and revised entitlement, staff decision, allocated/applied/absorbed/remaining amounts and audit provenance. Its financial difference is source-month-level; several contributing failed orders cannot each consume the same guarantee top-up. Unique constraints and transactions enforce this, not a front-end disabled button.

Allocation must share **one capacity per model/destination statement** across all corrections. Two deductions of 80 against earnings of 100 can apply at most 100 total, retaining 60. Never let each correction independently consume 80 and silently discard the extra after clamping the transfer to zero. Allocation ordering should be deterministic and documented; FIFO by approved decision/source chronology is an engineering proposal to review if it changes outcomes.

Keep draft/proposed allocations separate from committed approved allocations. A zero-transfer month can finalize as no transfer due; it does not create a payment row. Remainders survive indefinitely until applied or absorbed, including December→January and inactive/departed models awaiting a decision. Source correction reversals require D09 and compensating records after use, never edits to settled history.

At transition, old late-delivery allocations remain read-only evidence. New pending orders included in approval must not be queued into another month's earnings later. Do not clear legacy settled-in links wholesale; reconcile their meaning for each affected historical month.

### 05A implemented contract — read-only, not activated

`GET /api/affiliates/{affiliate_id}/earnings/{month}?rules_preview=true` adds
`financial_rules_preview`; without the flag the response is unchanged. The
existing `affiliates.view` permission applies; models cannot call this staff
endpoint. The staff model profile exposes the preview with a month selector.

- `performance`: source-month counted sales and delivered/pending/failed/
  unavailable counts. Legacy carry links never remove the source's sales or
  add them to a destination's own sales.
- `current_entitlement`: that month's terms, shared exact commission/fixed/
  guarantee calculation, rounded candidate payout and blockers. Pending counts
  once; no incoming late-delivery commission is added by this path.
- `source_complete` and per-order `issues`: missing delivery facts, uncertain
  original post-delivery basis and reversed failures needing D09 review.
  Incomplete figures are candidates, never approval instructions; the UI hides
  incomplete sales/earnings behind an explicit missing-information message.
- `approval`: existing active snapshot ID/version and frozen obligation, or
  null. `settlement`: recorded payment allocations, existing ledger state and
  explicitly named `legacy_balance_piastres`. Historical classification does
  not hide actual allocations or invent new transfer rows.
- `legacy_allocations`: source month, allocated month, order and snapshot IDs,
  for both ends of old carry. `requires_transition_reconciliation` flags them.
  Allocation is not labelled proof of payment. No links are reset or deleted.
- `orders`: raw source diagnostics, including state, known display basis (null
  when unavailable), completeness issues and legacy settled links. No per-order
  commission is computed or consumed by the preview screen. Order-screen
  earned/forgone presentation remains owned by `portal.py::_order_commission`;
  it is not reimplemented here. No customer identifiers/contact details.
- `can_approve=false` and `activation_blockers=[live_transition_not_enabled]`
  are unconditional. `calculate_month` has no source-orders parameter; only
  the separately named `preview_calculation` can select the pending-inclusive
  path through private shared arithmetic. Approval does not accept this mode.
  05B/05C and D01 still own immutable pending-inclusive approval, correction
  handling and activation.

The staff model-detail response sends `platform_start_month` from the server's
`PLATFORM_START_MONTH`. The preview's MonthPicker window combines that floor
with the model's collaboration start and the server's current month; there is
no hard-coded platform start date in the profile component.

Ingestion now retains a known base when an in-flight order becomes void; both
policies still exclude it by state. This preserves evidence, not entitlement.
Already-lost historical bases are not fabricated. No schema migration in 05A.

## Payment destinations and proof

The payment detail may request full destination through the existing audited, permission-gated reveal endpoint as part of opening the explicit payout view. This follows the owner's latest preference to see complete details there. It does not authorize every roster API to expose bank details or marketing roles to record payments.

Use the exact submitted validated InstaPay URL, including its path/query. Do not construct a payment link from a phone or account name, and do not treat visiting it as payment success. Parse/validate supported URL schemes/hosts through the established service. On laptops retain copy/link behavior even if no native app handles the link.

Record the actual external transfer against the correct approved statement and destination version. Account changes between approval and recording require the UI to record what was actually used; never rewrite older receipts to today's destination. Duplicate clicks/timeouts use the same operation key. Failed/abandoned uploads are not proof; upload succeeded/record-save-failed can be retried without another transfer. Preserve existing amount-overpayment handling and audit policy; do not silently rewrite actual sent amounts to fit a due balance.

Reuse the existing InstaPay instructional asset; supplying that image is frontend asset work. Payout validation/persistence and secure receipt retrieval are backend work. Product images similarly require both upstream ingestion and proper frontend rendering.

## Notices, settings and operational support

Use durable notice identity from the affected issue plus relevant revision. Store temporary dismissal separately from persistent item mute; avoid browser-only behavior if the chosen persistence is account-wide. Resolved issues vanish; a new distinct issue must not inherit an unrelated mute. Preserve the original attention service's permission checks.

Model notification kind labels adapt to existing `month_closed` and `payment_sent` events. A payment email follows a recorded transfer event, not a button click; retry/idempotency must not send it twice. Policy/security mail behavior remains separate.

Settings displays real connection/scopes/job state without placing API secrets in the browser. Existing staff role/status/invitation and policy/audit functions remain reachable with their permissions. Prototype weekly-reminder and role-composer controls are not additional approved backend products.
