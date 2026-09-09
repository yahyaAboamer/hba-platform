# Decisions and inputs still needed

The agent owns technical investigation and routine implementation choices. The owner owns consequential business policy and actual historical facts. Do not ask the owner to redesign schemas, supply fake values, or repeat decisions already in `PRODUCT_RULES.md`.

Resolve a question when its dependent batch is about to begin. If an answer is missing, complete independent work and identify the exact blocked operation. The suggestions below are **not silent approvals**.

| ID | Question / input | Why it matters | Resolve before | Suggested handling until resolved |
|---|---|---|---|---|
| D01 | What is the first month whose payments will be recorded under the new process? Which existing statements/transfers are already real, and which model/months are externally settled? Supply actual collaboration start months and historical terms/outcomes through the setup UI. | Prototype LAUNCH=March and old repository production GO_LIVE=September are not authoritative for this release. Incorrect boundaries can double-pay old months or suppress real debts. | Phase 02 history design; final mapping before 08 rehearsal/release | Inventory existing records read-only. Use an explicit per-model/month transition manifest; never change GO_LIVE_MONTH to January just to expose history. Preserve actual old platform transfers. |
| D02 | Keep existing whole-EGP half-up rounding for final payouts, or change to two-decimal payouts? | The prototype prints decimal totals and uses JavaScript rounding; the repo rounds the total to whole pounds. This affects actual money. | Phase 05A financial acceptance | Preserve existing exact-arithmetic and whole-pound payout rule. Display precision alone does not change settlement precision. |
| D03 | Does a displayed code use count every placed attributed order, including failures, or only counted orders? Which period and tie treatment should Ranking use? | Sales ranking and displayed use counts can move differently. The prototype explicitly calls this open. | Phase 07 analytics | Proposed: selected-month ranking by counted net sales, same-rank ties, stable display order; keep uses separately defined. Do not imply matching uses guarantees a rank. Ask the owner to confirm only the unanswered parts. |
| D04 | Can an incoming deduction take a later guarantee-qualified month below its guaranteed minimum, or only consume earnings above the floor? | The source-month guarantee calculation is settled; this separate destination-month question is not. | Phase 05C deduction allocation | Build both calculations as reviewed examples. No silent recovery from a protected minimum. Block that affected allocation until chosen; other arrangement work can proceed. |
| D05 | Should positively priced personal purchases appear in the same wardrobe, and count as possession for promotion eligibility? | Shipping-phone matching finds gifts and purchases; classification is agreed, their final presentation is not explicit. | Phase 03B/04A wardrobe inclusion | Preserve classification and order evidence. Recommend displaying received personal purchases as owned, with gift/purchase provenance in details if useful. Do not exclude or include them by assumption. |
| D06 | **ANSWERED 9 Sep 2026: card number.** | — | — | **Closed.** `decisions/D06-the-bank-field-is-a-card-number.md`. The column keeps its name and meaning; every screen now takes its label from one map and says *card number*. The design's *account number* wording is superseded. A frontend guard fails the build if the phrase returns. |
| D07 | **ANSWERED 9 Sep 2026: one email.** | — | — | **Closed.** `decisions/D07-one-email-per-model.md`. No contact email and no contact address. The single address is her login, and every screen that shows it says so — *You sign in with* / *Signs in with* — rather than calling it "email". |
| D08 | What qualifies as low weekly content performance, if an automatic low-performance label is wanted? | Week-one shortfall against a monthly target is not automatically poor performance; no weekly pacing rule is approved. | Phase 07 Home labels | Show neutral recorded/required counts and missing-input status. This can ship without an automatic bad-model classification; do not block all Home work. |
| D09 | How should a later correction to a previously failed Shopify status be settled after a deduction/absorption was used? How are pending-order price edits after approval handled? | Immutable approval cannot absorb a changed instruction silently. New policy explicitly settles failed deliveries but does not fully specify all other revisions. | Phase 05C / before live correction handling | Detect and retain the event; use a manual-review state. Propose an append-only compensating credit approved by staff, never rewrite a used deduction. No refund/exchange deductions after delivery. |
| D10 | If finance colleagues need their own accounts, which existing roles/permissions should they have? Is any new restricted payer role actually desired? | Current repo permits only admin to record payments; prototype Finance is not a real role. | Phase 01 permission map; any role change before 08 | Preserve existing access rules. Record the mapping and obtain an explicit decision only if existing capabilities do not serve the intended users. Never share accounts or grant broad admin automatically. |

## Technical evidence, not owner policy questions

- Confirm current default/deployment branches, latest SHA, migration head, real onboarding state and environment separation. Record changed evidence in the baseline report.
- Verify Shopify API version/scopes and actual returned shipping-address phone, product/variant/media and fulfillment fields. Older-than-60-day history requires the appropriate all-orders access. Field access depends on app type and permissions; do not assume presence because the store UI displays it.
- Verify the shipping-phone matching strategy against the API's documented search fields; use indexed ingestion/pagination if needed. Do not promise a shipping-phone search operator without proving it.
- Verify how pre-cancellation/first-seen-after-delivery order values can be established for historical reconstruction. Reuse stored commission bases and original money evidence when authoritative. Missing evidence belongs in readiness diagnostics.
- Define API pagination, optimistic concurrency, idempotency and migration locking in code, following the repo. Those are engineering decisions.
- Verify target outcome-only historical support and live verification behavior from the current schema/services before adding migrations.

## Answered so far

| ID | Answer | Date | Record |
|---|---|---|---|
| D06 | Card number | 9 Sep 2026 | `decisions/D06-the-bank-field-is-a-card-number.md` |
| D07 | One email | 9 Sep 2026 | `decisions/D07-one-email-per-model.md` |

Both were asked as questions about the act rather than the schema — *what do
you type into the banking app*, *do you want a second address to keep current*
— and both were answered in a word. The records carry what each one settles and
what it leaves alone.

## Recording an answer

Append the owner's actual choice, its date/source and affected rules/checks using `templates/DECISION_RECORD.md`. Update `STATUS.md` and the relevant contract. Do not mark a proposal confirmed because it was convenient to implement.
