# Decisions and inputs still needed

The agent owns technical investigation and routine implementation choices. The owner owns consequential business policy and actual historical facts. Do not ask the owner to redesign schemas, supply fake values, or repeat decisions already in `PRODUCT_RULES.md`.

Resolve a question when its dependent batch is about to begin. If an answer is missing, complete independent work and identify the exact blocked operation. The suggestions below are **not silent approvals**.

| ID | Question / input | Why it matters | Resolve before | Suggested handling until resolved |
|---|---|---|---|---|
| D01 | What is the first month whose payments will be recorded under the new process? Which existing statements/transfers are already real, and which model/months are externally settled? Supply actual collaboration start months and historical terms/outcomes through the setup UI. | Prototype LAUNCH=March and old repository production GO_LIVE=September are not authoritative for this release. Incorrect boundaries can double-pay old months or suppress real debts. | Phase 02 history design; final mapping before 08 rehearsal/release | Inventory existing records read-only. Use an explicit per-model/month transition manifest; never change GO_LIVE_MONTH to January just to expose history. Preserve actual old platform transfers. |
| D02 | Keep existing whole-EGP half-up rounding for final payouts, or change to two-decimal payouts? | The prototype prints decimal totals and uses JavaScript rounding; the repo rounds the total to whole pounds. This affects actual money. | Phase 05A financial acceptance | Preserve existing exact-arithmetic and whole-pound payout rule. Display precision alone does not change settlement precision. |
| D03 | **ANSWERED 11 Sep 2026: a use is a delivery outcome, not a financial one.** | — | — | **Closed.** `decisions/D03-uses-are-deliveries-not-money.md`. Only a failed delivery removes an order from the count; delivered counts permanently and anything in between counts until it resolves. **Do not read `commission_state`** - it folds cancelled, refunded and failed into one `void` and would silently drop the first two. Ranking orders by sales, breaks ties on uses, and gives equal rank with the next place skipped (1, 1, 3). |
| D04 | **ANSWERED 10 Sep 2026: the whole month, below the guarantee if needed.** | — | — | **Closed.** `decisions/D04-recovery-comes-before-the-guarantee.md`. A carried overpayment consumes a later month's whole payable, not only what was earned above the floor; a month can settle at zero. It does **not** make absorption automatic — §11.5's carry-or-absorb choice is untouched. The platform recommended protecting the floor and was overruled; the record says so, and why the screens must now explain a reduced month to the model. |
| D05 | **ANSWERED 10 Sep 2026: gifts only.** | — | — | **Closed.** `decisions/D05-the-wardrobe-is-what-hba-sent.md`. The wardrobe returns products from zero-price orders and nothing else. What she bought with her own money is classified and kept as evidence, and is not hers to see on that screen. |
| D06 | **ANSWERED 9 Sep 2026: card number.** | — | — | **Closed.** `decisions/D06-the-bank-field-is-a-card-number.md`. The column keeps its name and meaning; every screen now takes its label from one map and says *card number*. The design's *account number* wording is superseded. A frontend guard fails the build if the phrase returns. |
| D07 | **ANSWERED 9 Sep 2026: one email.** | — | — | **Closed.** `decisions/D07-one-email-per-model.md`. No contact email and no contact address. The single address is her login, and every screen that shows it says so — *You sign in with* / *Signs in with* — rather than calling it "email". |
| D08 | **ANSWERED 11 Sep 2026: a quarter of the month's targets a week, videos and stories added together first.** | — | — | **Closed.** `decisions/D08-weekly-pace-is-a-quarter-a-week.md`. Rounded up; weeks anchored to the day the month begins; the fourth check is the end of the month, not the end of week four. Stale counts read as *nothing recorded this week*, never as behind. **HBA only** - nothing appears on the model's screens. Decides no money. |
| D09 | How should a later correction to a previously failed Shopify status be settled after a deduction/absorption was used? How are pending-order price edits after approval handled? | Immutable approval cannot absorb a changed instruction silently. New policy explicitly settles failed deliveries but does not fully specify all other revisions. | Phase 05C / before live correction handling | Detect and retain the event; use a manual-review state. Propose an append-only compensating credit approved by staff, never rewrite a used deduction. No refund/exchange deductions after delivery. |
| D11 | **ANSWERED 10 Sep 2026: a profile field both sides edit.** Not in the original list — it arose when Phase 03 asked whether a shipping address was a Shopify fact or a profile field. | — | — | **Closed.** `decisions/D11-her-address-is-a-profile-field-both-sides-edit.md`. Protected model data that admins can see, because HBA types it into the orders they create; both sides may edit it, and the writer is recorded. |
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
| D03 | Uses are deliveries, not money | 11 Sep 2026 | `decisions/D03-uses-are-deliveries-not-money.md` |
| D04 | Recovery comes before the guarantee | 10 Sep 2026 | `decisions/D04-recovery-comes-before-the-guarantee.md` |
| D08 | A quarter of the targets a week | 11 Sep 2026 | `decisions/D08-weekly-pace-is-a-quarter-a-week.md` |
| D05 | The wardrobe is what HBA sent | 10 Sep 2026 | `decisions/D05-the-wardrobe-is-what-hba-sent.md` |
| D06 | Card number | 9 Sep 2026 | `decisions/D06-the-bank-field-is-a-card-number.md` |
| D07 | One email | 9 Sep 2026 | `decisions/D07-one-email-per-model.md` |
| D11 | Her address is a profile field both sides edit | 10 Sep 2026 | `decisions/D11-her-address-is-a-profile-field-both-sides-edit.md` |

All four were asked as questions about the act rather than the schema — *what
do you type into the banking app*, *do you want a second address to keep
current*, *does something she bought belong in her wardrobe* — and all four
were answered in a sentence. The records carry what each one settles and what
it leaves alone.

**Still open: D01, D02, D09, D10.** D02 applies to final payout
rounding. 05A preserved and tested the existing exact-arithmetic whole-pound
rule under the continuation handoff's instruction to proceed. It remains an
open owner decision; D01 still gates live activation.

## Recording an answer

05A implementation note (10 September 2026): D02's existing whole-pound
half-up rule was retained and verified with the supplied financial examples.
This follows the continuation handoff's instruction to proceed; it is not a
new owner answer and does not close D02. D01 remains the live-transition gate;
the new financial rules are available only as a read-only preview.

Append the owner's actual choice, its date/source and affected rules/checks using `templates/DECISION_RECORD.md`. Update `STATUS.md` and the relevant contract. Do not mark a proposal confirmed because it was convenient to implement.
