# Decisions and inputs still needed

The agent owns technical investigation and routine implementation choices. The owner owns consequential business policy and actual historical facts. Do not ask the owner to redesign schemas, supply fake values, or repeat decisions already in `PRODUCT_RULES.md`.

Resolve a question when its dependent batch is about to begin. If an answer is missing, complete independent work and identify the exact blocked operation. The suggestions below are **not silent approvals**.

| ID | Question / input | Why it matters | Resolve before | Suggested handling until resolved |
|---|---|---|---|---|
| D01 | **ANSWERED 11 Sep 2026: September 2026 is the first month we pay.** | — | — | **Closed.** `decisions/D01-september-is-the-first-month-we-pay.md`. Everything before it was settled outside: still calculated and frozen, never payable, and the ledger refuses a transfer against one. **Production was already set this way** - the decision is no change, and the point of recording it is that the setting was a default nobody had ratified. History shown to a model is `max(her start, January 2026)`, which `months_for` already did. |
| D02 | **ANSWERED 12 Sep 2026: whole pounds.** | — | — | **Closed.** `decisions/D02-we-pay-in-whole-pounds.md`. A payout settles at a whole EGP, half-up, once, on the total — which is what ADR 0004 already did, so the decision changes no code. The arithmetic underneath is untouched: integer piastres, basis points, multiply before dividing. Display precision is not settlement precision. `F05`'s *unless D02 explicitly changes it* does not fire. |
| D03 | **ANSWERED 11 Sep 2026: a use is a delivery outcome, not a financial one.** | — | — | **Closed.** `decisions/D03-uses-are-deliveries-not-money.md`. Only a failed delivery removes an order from the count; delivered counts permanently and anything in between counts until it resolves. **Do not read `commission_state`** - it folds cancelled, refunded and failed into one `void` and would silently drop the first two. Ranking orders by sales, breaks ties on uses, and gives equal rank with the next place skipped (1, 1, 3). |
| D04 | **ANSWERED 10 Sep 2026: the whole month, below the guarantee if needed.** | — | — | **Closed.** `decisions/D04-recovery-comes-before-the-guarantee.md`. A carried overpayment consumes a later month's whole payable, not only what was earned above the floor; a month can settle at zero. It does **not** make absorption automatic — §11.5's carry-or-absorb choice is untouched. The platform recommended protecting the floor and was overruled; the record says so, and why the screens must now explain a reduced month to the model. |
| D05 | **ANSWERED 10 Sep 2026: gifts only.** | — | — | **Closed.** `decisions/D05-the-wardrobe-is-what-hba-sent.md`. The wardrobe returns products from zero-price orders and nothing else. What she bought with her own money is classified and kept as evidence, and is not hers to see on that screen. |
| D06 | **ANSWERED 9 Sep 2026: card number.** | — | — | **Closed.** `decisions/D06-the-bank-field-is-a-card-number.md`. The column keeps its name and meaning; every screen now takes its label from one map and says *card number*. The design's *account number* wording is superseded. A frontend guard fails the build if the phrase returns. |
| D07 | **ANSWERED 9 Sep 2026: one email.** | — | — | **Closed.** `decisions/D07-one-email-per-model.md`. No contact email and no contact address. The single address is her login, and every screen that shows it says so — *You sign in with* / *Signs in with* — rather than calling it "email". |
| D08 | **ANSWERED 11 Sep 2026: a quarter of the month's targets a week, videos and stories added together first.** | — | — | **Closed.** `decisions/D08-weekly-pace-is-a-quarter-a-week.md`. Rounded up; weeks anchored to the day the month begins; the fourth check is the end of the month, not the end of week four. Stale counts read as *nothing recorded this week*, never as behind. **HBA only** - nothing appears on the model's screens. Decides no money. |
| D09 | **ANSWERED 12 Sep 2026: a delivery outcome is final.** | — | — | **Closed.** `decisions/D09-a-delivery-outcome-is-final.md`. *"Once the status is delivered or failed it can't be the other one"* — so a recovered failure that later turns out to be a delivery cannot arise, and no manual-review state is built for it. Same shape as D03. The second half — a price edit after approval — is already covered by `corrections.py`: an agreed month is never unmade, and what changes is recorded against it. |
| D10 | **ANSWERED 12 Sep 2026: no new role.** | — | — | **Closed.** `decisions/D10-only-the-admin-edits.md`. Recording a payment stays admin-only. The prototype's *Finance* described a person who does not exist at HBA, and a permission boundary between two colleagues in one room protects against nothing. Existing roles unchanged, accounts still never shared. Reopened only when somebody is hired to sit behind it. |
| D11 | **ANSWERED 10 Sep 2026: a profile field both sides edit.** Not in the original list — it arose when Phase 03 asked whether a shipping address was a Shopify fact or a profile field. | — | — | **Closed.** `decisions/D11-her-address-is-a-profile-field-both-sides-edit.md`. Protected model data that admins can see, because HBA types it into the orders they create; both sides may edit it, and the writer is recorded. |
| D12 | **ANSWERED 12 Sep 2026: a featured product needs no message.** Not in the original list — it arose from the design-parity audit. | — | — | **Closed.** `decisions/D12-a-featured-product-needs-no-message.md`. The approved design shows a featured product as an image card with an *optional* note; the server refused a blank one. The refusal goes, in both places, so a note can also be cleared. W09's three verbs (`message`, `visible`, remove) are untouched. |

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
| D01 | September is the first month we pay | 11 Sep 2026 | `decisions/D01-september-is-the-first-month-we-pay.md` |
| D02 | We pay in whole pounds | 12 Sep 2026 | `decisions/D02-we-pay-in-whole-pounds.md` |
| D03 | Uses are deliveries, not money | 11 Sep 2026 | `decisions/D03-uses-are-deliveries-not-money.md` |
| D04 | Recovery comes before the guarantee | 10 Sep 2026 | `decisions/D04-recovery-comes-before-the-guarantee.md` |
| D08 | A quarter of the targets a week | 11 Sep 2026 | `decisions/D08-weekly-pace-is-a-quarter-a-week.md` |
| D09 | A delivery outcome is final | 12 Sep 2026 | `decisions/D09-a-delivery-outcome-is-final.md` |
| D05 | The wardrobe is what HBA sent | 10 Sep 2026 | `decisions/D05-the-wardrobe-is-what-hba-sent.md` |
| D06 | Card number | 9 Sep 2026 | `decisions/D06-the-bank-field-is-a-card-number.md` |
| D07 | One email | 9 Sep 2026 | `decisions/D07-one-email-per-model.md` |
| D10 | Only the admin edits | 12 Sep 2026 | `decisions/D10-only-the-admin-edits.md` |
| D11 | Her address is a profile field both sides edit | 10 Sep 2026 | `decisions/D11-her-address-is-a-profile-field-both-sides-edit.md` |
| D12 | A featured product needs no message | 12 Sep 2026 | `decisions/D12-a-featured-product-needs-no-message.md` |

All four were asked as questions about the act rather than the schema — *what
do you type into the banking app*, *do you want a second address to keep
current*, *does something she bought belong in her wardrobe* — and all four
were answered in a sentence. The records carry what each one settles and what
it leaves alone.

**Nothing is open.** D02, D09 and D10 were answered on 12 September 2026 and
D12 was raised and answered the same day, which closes the set D01-D12.

The last three went the same way: each was a question about machinery for a
situation HBA does not have. Decimal payouts nobody wants, a reversal Shopify
does not perform, a finance role for a colleague who does not exist. The answer
in all three cases was to keep what the platform already did and say so.

## Recording an answer

05A implementation note (10 September 2026): D02's existing whole-pound
half-up rule was retained and verified with the supplied financial examples.
This follows the continuation handoff's instruction to proceed; it is not a
new owner answer and does not close D02. D01 remains the live-transition gate;
the new financial rules are available only as a read-only preview.

Append the owner's actual choice, its date/source and affected rules/checks using `templates/DECISION_RECORD.md`. Update `STATUS.md` and the relevant contract. Do not mark a proposal confirmed because it was convenient to implement.
