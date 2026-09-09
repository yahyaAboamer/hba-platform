# HBA — final admin prototype revision

Paste the prompt below into Claude Design with the latest project. This is a focused revision of the approved visual direction, before production implementation.

---

Continue the latest **Admin Dashboard** in this project. Preserve the black/green theme, typography, spacing, laptop layout, six main tabs, and shared model profile. I like the design. Improve the specific workflows below without redesigning the application or adding explanatory paragraphs throughout it.

Keep the approved mobile Affiliate Portal v3 visually consistent. Change its behavior only where the clarified feature-request audience or shared payment/compensation examples require it. Earlier snapshots are references, not the current specification. These instructions supersede the old note that every model sees every feature request.

Use concise labels, short validation messages and relevant information controls. Keep implementation notes and unresolved decisions outside the app frame. Product photography, actual receipts and the InstaPay help image can remain identified placeholders. This remains a prototype with local sample data; do not connect Shopify, send invitations, or initiate real transfers.

## 1. Make payment destinations usable

The current mock stores masked strings and does not provide the actual destination in the payment-detail page. Replace those fixtures with clearly fictional, complete destination fields.

Show a compact **Where to send it** card directly inside each model/month payment detail, beside the calculation where space permits. Reuse the same destination presentation in the model profile's Payments section and the Record payment view. The main Payments table should provide useful, unmasked destination information and a direct way to open the full card.

- **InstaPay:** show the recorded InstaPay number, the exact link submitted by the model, **Open InstaPay**, **Copy link**, and **Copy number**. Bind the button to the saved link; never construct it from the affiliate's code, name or phone. Opening the link is separate from recording a payment. Keep a copy action available for the laptop workflow.
- **Bank:** show bank name, account holder and the complete recorded destination number. Label it accurately for the field the model actually provided; do not silently treat a card number as an IBAN or introduce mandatory fields that the model form does not collect.
- **Wallet:** show wallet provider, where recorded, and complete wallet phone number with Copy.
- Do not add another masking/reveal step to these authorized admin payment views. Keep existing access permissions when this is implemented in the repository.
- If details are missing or cannot load, say so briefly and offer the relevant retry/profile action. Do not substitute another model's sample details or silently choose an alternative destination.
- A recorded transfer retains the destination actually used, even if the model later changes their current destination. Its receipt detail must show that historical destination.
- Show “Copied” only after the copy succeeds; keep the value selectable if clipboard access is unavailable.

## 2. Replace “Effective from” with selecting months

Keep this inside the existing compensation editor, reached from the model's Payments section and Historical setup. Do not create another main tab.

Use a year selector and a compact grid of twelve month buttons. Each month should convey its arrangement or “Not set,” selection state and, when applicable, its locked state. Include **Select all editable months in [year]** and Clear selection. Do not interpret “all” as all future years.

Beside or below the grid, keep the existing arrangement controls:

1. Commission only: commission rate.
2. Fixed salary plus commission: salary and commission rate.
3. Guaranteed minimum with commission: minimum and commission rate; eligibility depends on that month's target outcome.

The normal interaction must be:

- Select January and February, enter one arrangement and choose **Apply to 2 months**.
- Stay in the editor, show the updated month labels and a short saved confirmation.
- Select March and April, enter another arrangement, apply it, and continue.
- Support separate selected months too: changing January and March must leave February untouched.
- Show a compact “Terms through the year” summary using explicit month ranges. Do not label a scheduled future arrangement “Current.”

Safeguards and scope:

- Load the values actually stored for the selected months. If their values differ, show a mixed state; do not silently replace a custom rate or salary with the fixture defaults.
- Only selected months change. A January–February edit must not leak into March. An existing ongoing arrangement beyond the selection must remain intact. Future/open-ended changes, if retained, require a separate explicit choice and must not be implied by selecting months in this year.
- Months before January 2026 or the model's later collaboration start are unavailable. Keep collaboration dates distinct from the date the invitation was approved.
- **Historical setup:** existing models' already-settled prelaunch months need their original terms entered. These months must be editable during setup without creating debts or invented transfer records. Demonstrate the January–February / March–April / May onward example in this setup context.
- **Live operation:** ordinary edits must not rewrite terms used by an approved statement, even if its transfer has not been recorded yet. Show those months locked. There is no reopening action. Explain locked months briefly when relevant, not with a permanent paragraph.
- Saving a selection must be one complete update: validation or a newly locked month must not leave half the selection changed. Preserve all unselected months and avoid overlapping arrangements or accidental gaps.
- Validate entered values explicitly. Blank or invalid values must not silently become 10%, EGP 12,000 or EGP 2,000.
- Preserve unsaved changes when changing views or offer a brief discard choice. Refresh the summary and affected unapproved estimates after a successful save.

Use the selected month's actual rate in every calculation, order commission, payment breakdown and relevant chart. The present prototype displays the saved rate but still multiplies sales by a global 10%. Remove that inconsistency, including the Home label “Commission at 10%” when models have different rates.

## 3. Restrict feature requests to eligible wardrobes

The audience is now clarified:

| Model's relationship to this product | Feature request visible to that model? |
|---|---|
| Received | Yes |
| Processing / on the way | Yes, with the processing context |
| Not sent | No |
| Failed delivery / needs checking, without another eligible shipment | No |

Eligibility belongs to the model/product relationship, not whether the model has received some other item in the same collection. Evaluate it as the shipment state changes while the request is active.

- Replace the generic “A model who does not” preview with **Received** and **On the way** previews. Remove “Every model sees the request; the ownership line differs.”
- A compact audience count such as “12 received · 3 processing” is sufficient in the admin editor. Do not add a manual recipient-management system.
- If no models qualify, the request may remain configured but nobody sees it; state that briefly for the admin.
- Apply the same eligibility rule in the mobile Wardrobe. Hide the entire request section if it contains no eligible visible requests.
- Do not invent arrival dates. Show dates only when real data provides them.
- Keep this a display-only content request: no Done button, acknowledgement, completion tracking, required content type, or automatic target change.
- Preserve Show/Hide and Remove. Hiding/removing a request does not remove the product from a wardrobe.
- Keep the existing four product-coverage groups, search, names and order references. Sizes remain in wardrobe/details. Shopify is the delivery-status source; remove wording implying a direct courier connection.

## 4. Make the approval, correction and payment examples agree

These are prototype consistency fixes, not a request to build a production finance engine inside the HTML.

### Approval and later failures

- Approval freezes the actual calculation shown: applied terms, target outcome, earnings components, deductions and approved amount. A later order failure may update the original month's sales performance; it must not silently change approved earnings, recorded transfers or the remaining amount due on that approval.
- Use a coherent guarantee example everywhere: original commission and actual transfer **EGP 2,100**; later failed commission **EGP 200**; revised commission **EGP 1,900**. If targets were met and the minimum is EGP 2,000, recover **EGP 100**. If targets were missed, recover **EGP 200**. The current correction screen says EGP 2,100 was paid while September's payment page/receipt is generated from the revised EGP 2,000; correct this contradiction.
- Distinguish approval from transfer: an order can fail after approval but before payment. Do not label every such correction “already paid.” Retain the frozen approval and show the actual transfer state separately.
- On the order detail, identify the correction decision and where a deduction was applied, with a link. If a failed order's original amount is known, show its excluded commission/amount struck through as agreed. If unavailable, use a short unavailable state, not a fabricated zero. Do not claim cancellation always destroys Shopify product lines.
- A chosen deduction changes the destination month's payment breakdown, not that month's own sales or sales graph. Allow allocation only to a suitable unapproved month, not one already frozen. Once an allocation has been approved, do not expose an ordinary action that silently removes or moves it.

### Insufficient earnings and transfer records

- Demonstrate a recoverable EGP 300, current earnings EGP 40, applied deduction EGP 40, amount to send EGP 0, and **EGP 260 remaining**. The remaining balance must appear in a subsequent month, including across December/January; merely printing “carries forward” is insufficient.
- After approval, a zero-payment month needs a completed state such as **No transfer due**, with its carried balance visible. It must not wait forever for a transfer that should not exist.
- When several corrections exist, their applied lines must sum to the actual deduction. Do not independently subtract the full available earnings for each source.
- Preserve each transfer exactly once when another partial payment is added. Current mock accumulation can duplicate a seeded transfer on a later save. Retain receipt attachment state and distinguish “No receipt attached” from an actual receipt.
- “Recorded so far” means the actual amount transferred; do not cap this figure at the current calculated entitlement. Default the transfer form to the remaining approved amount, but retain a way to document what was actually transferred if it differs, with the discrepancy visible. Do not silently alter either the transfer or the approved statement to force a match.
- Use an explicit sample launch boundary, clearly marked outside the app as a fixture. Do not treat March 2026 or a July policy date as an agreed business decision. Prelaunch months are settled with no receipts imported and no funding requirement. They still show reconstructed performance from January 2026 or the later collaboration start.

## 5. Correct targets and preserve historical records

- **Set requirements** must edit that month's required videos/stories. **Record achieved** must edit that month's achieved counts. Currently both save through the achieved-count path, so changing a requirement can falsely record completed work.
- Keep requirements and achieved counts scoped to their actual month. Changing November's requirement must not rewrite September's guarantee outcome or approved calculation.
- Accept nonnegative whole counts; no negatives or fractions. Fix sample-data generation that currently produces negative story counts.
- Blank/unrecorded and explicitly recorded zero are different states. Saving one field must not silently mark another unrecorded field as zero. A guarantee cannot be finalized with an unknown relevant target outcome.
- Weekly entries represent the month's cumulative achievements so far. Keep the recorded/updated context. Do not invent a weekly underperformance threshold: the current monthly shortfall list does not establish that someone is behind this week. Keep the Home section neutral until that rule is agreed.
- Making a model inactive must preserve their existing wardrobe, historical sales, targets, statements and transfers. Historical totals must include everyone who participated in that month. Outstanding payment obligations must remain accessible after inactivation. Current-active filters may control current operating lists, not erase history.

## 6. Finish the small navigation and setup gaps

- Give the model's Overview/Performance a local month selector with eligible months. Currently the profile inherits the last Home month and hides the selector, requiring a trip back to Home to change its period. Wardrobe remains an ownership view, independent of the financial month.
- Add pagination or Load more to the all-attributed-orders list; it currently stops at 40 rows with no way to reach the remainder. Historical setup must reach all models, not just its current first six rows.
- Preserve filters, selected month and useful return position when navigating from product → model → payment/order and back.
- Make application setup reviewable: connect the existing code-verification, terms and target-setup actions to their respective prototype forms; make approval update the shared sample roster consistently. Show what still needs setup before approval instead of displaying nonfunctional setup labels. Keep Shopify interaction read-only within the agreed scope.
- Historical setup should identify uncovered terms and unknown historical target outcomes for guarantee months. A first terms record alone does not prove the entire history is ready. Reuse the month editor here.
- Keep owner Home focused on sales, expected payout, active models, top three by sales, and content progress. Supporting notices should follow the requested dismissible pop-up behavior. **Hide for now** and **Don't remind me about this item** must have different outcomes; unresolved hidden-for-now notices can return, resolved notices disappear, and muting does not resolve the underlying record.
- Provide short loading, empty and retry states for data views. A failed fetch must not look like zero earnings, an empty wardrobe or no payments. Retain last successfully loaded data with a concise stale indication where appropriate.

## 7. Review the revision using these examples

Keep sample controls outside the app frame so the interface itself stays clean:

1. Each payment method shows its complete destination; InstaPay uses the saved link and copy controls.
2. Historical setup assigns three arrangements to selected months, stays open after saving, and leaves unselected months unchanged. A separate live example shows locked approved months.
3. Two different commission rates produce different, correct calculations across Home, profile and payment details.
4. Received and processing models see a feature request; not-sent and failed-only models do not.
5. September remains approved/paid at EGP 2,100 while its later correction is explained; both guarantee outcomes work.
6. An insufficient month closes with no transfer due and carries only its remaining balance into the next month.
7. Saving required targets does not change achieved counts; no record remains distinct from zero.
8. An inactive model's history and wardrobe remain available; all orders and historical setup rows are reachable.

Return the revised prototype and a short list of what changed. Flag any unresolved business choice outside the app instead of inventing a policy. Do not add new top-level features or fill pages with explanation.

---

## Repository handoff notes for the eventual coding agent

These notes are not product UI copy and do not require Claude Design to change the repository.

- Review source: `Admin Dashboard.dc.html` in upload **Dashboard redesign for affiliate platform (3).zip**, including all six tabs, shared profile and secondary views. The exported overview image and source were inspected; a live browser walkthrough was not completed.
- The existing repository already exposes full destinations through `POST /api/affiliates/{affiliate_id}/payout-destination/reveal`, with the existing payment-recording permission. `frontend/src/screens/PaymentRecord.tsx` already demonstrates the full fields and an `Open InstaPay` anchor using `instapay_address_url`. Reuse the established data contract and destination snapshot behavior; adapt presentation to the approved design.
- `frontend/src/screens/Compensation.tsx` currently has an effective-start workflow. `app/services/compensation.py` stores dated periods, prevents overlap and protects approved months. It does **not** already implement arbitrary month selection. Add a transactional selected-month operation that splits/preserves existing periods as necessary, validates the whole edit, and retains approved calculation references. Do not simulate it with a sequence of independent browser requests that can partially succeed. Remove obsolete reopening instructions from the resulting user-facing flow.
- Prototype checks confirmed: changing a stored rate from 10% to 15% still calculated EGP 340 instead of EGP 510 for a sample EGP 3,400; saving an 8-video requirement changed achieved videos while the requirement stayed 6; September's correction reported an original EGP 2,100 payment while its payment functions returned EGP 2,000; an EGP 260 remainder had no later-month allocation; an inactive model with August sales was omitted from August's Payments list and had an empty generated wardrobe.
- Mock arrays, date boundaries, receipts, status labels and showcase role names are not production policy or permissions. Preserve the agreed Shopify monitoring, monthly compensation, target and payment rules when implementing. Maintain model/customer privacy in their respective authorized views.
