# Final export review

## Conclusion

The named files are the right implementation references. The latest admin revision addresses the requested layout changes; another complete Claude Design round is not required to begin. Treat design approval as approval of the visual experience, while correcting the mock behavior below in the real app.

Both final exports changed relative to `(3)(1).zip`; older HTML versions did not. Final hashes are in `evidence/source-manifest.json`. The model v3 changes are largely wardrobe request visibility/copy; they do not resolve its older financial, chart or draft-state problems.

Review evidence: source inspection, old/new comparison, the archive's admin thumbnail, and isolated logic probes in `evidence/prototype-probe-results.json`. These are not browser interaction tests. Local browser navigation was blocked by the cloud browser's URL policy; the agent must perform visual comparison against the running app before claiming implementation fidelity.

## Improvements present in this export

- Full payment destination cards, copy controls and the submitted InstaPay link in admin payment details.
- A selected-month compensation grid, mixed-value indication, Select all editable months, approved locks and repeated save-in-place editing.
- Required-target editing is separated from achieved counts in admin mock state; rates are looked up from the selected month's terms in admin calculations.
- A passive feature-request editor previews Received/Processing audiences. Model v3 wraps the feature section in an empty-state condition and removes invented arrival dates from the sample incoming list.
- Additional order/history rows can be reached, inactive profiles have a history path, and the shared profile has local month context.
- Example late-failure, insufficient-earnings, different-rate, new-model and inactive-history scenarios are provided outside the app frame. They are useful review fixtures; none should ship as product controls.

## Required implementation corrections

| ID | Evidence in final source | Required treatment | Batch |
|---|---|---|---|
| V01 | Model `isApprovedFixed` covers paid/settled but omits approved. | Freeze the approved statement before payment. Live source sales can change separately; approved payable must not. | 05B, 07A |
| V02 | Model receipt's “See how this month was calculated” calls the generic current-month action. Probe opens November from a September receipt. | Route by receipt's source month/snapshot/payment ID, preserving Back context. | 06B |
| V03 | Model payout/contact inputs mutate the shared form immediately; Save just flips a boolean. | Separate drafts, validate/save on server, discard on Cancel, restore successful state after reload; retain payout reauthentication. | 02B, 06B |
| V04 | Model chart divides by `series.length - 1` and zero maxima. Probes produce NaN for one month and all-zero histories. | Center a single point, provide finite zero scales, handle no history and missing data. Zero-height bars must not imply real uses. Test month navigation and tap targets. | 07A |
| V05 | Model uses a global RATE/SALARY/GUARANTEE/arrangement, sample payment rows and fixed calendar. | Every value/label comes from that model/month's server contract. Preserve actual transfers separately from entitlement; year and period selection come from eligible dates. | 02C, 05–07 |
| V06 | Admin `paymentVals` checks only videos for known targets; its other helper checks videos and stories. Probe allows approval with unknown stories. | Reuse one authoritative blocker calculation. Unknown required evidence cannot approve a guarantee; both API and UI agree. | 04, 05B |
| V07 | Admin `allocationsFor` walks only four months. It independently assigns each correction against the full month's earnings. | Persistent unbounded remaining balance, shared per-month allocation capacity and cumulative source-month entitlement correction. Never clamp away an overallocated difference. | 05C |
| V08 | Admin `payable` can recompute carried amounts from current correction state rather than immutable accepted allocations. | Approved statement stores the applied amounts/references. A later correction goes to another open destination or review; it does not change an approved destination. | 05B/C |
| V09 | Historical readiness still uses the first `m.terms` entry rather than every monthly assignment. Probe reports missing terms after all eligible overrides were supplied. | Read actual coverage per month and historical outcome/data readiness; finalization is a real operation. | 02C, 09 |
| V10 | Admin dates include sample CURRENT November 2026, LAUNCH March 2026, January/February 2027 only, and hardcoded update dates. | Server business clock, actual launch boundary, real timestamps and generated month grid. No fixture-driven historical locks or invented transfer dates. | All data batches |
| V11 | Model feature list is an array; `hasFeatured` only checks its length. | Server returns the actual eligible intersection. Preserve concise layout; hide header and cards together when empty. | 03C |
| V12 | Model target qualification treats comparisons as sufficient; histories have invented counts. | Null/zero/verification/outcome-only distinctions; prevent target edits from rewriting approved financial evidence. | 04, 05 |
| V13 | Top-seller aggregation uses product names, increments units by one and sums listed prices. Ranking is seeded. | Stable product IDs, quantities, discount-aware attribution, server ranking and peer-value privacy. | 03, 07B |
| V14 | Prototype action success, receipts, invitation approval, Shopify refresh and notices are largely in-memory. | Wire real APIs, failure/retry states and persistence. No false Saved/Copied/Connected/Paid status. | Relevant vertical batch |
| V15 | Bank/card labels differ between model mock, admin mock and repo; prototype wallet options omit the existing WE Pay option. | Reconcile D06, retain supported providers/fields and the submitted URL. Don't shrink working payment methods to the example list. | 02B, 06 |
| V16 | Prototype roles/preferences/weekly reminders are showcase labels; Home shortfall scoring is arbitrary. | Preserve server permission mapping, keep two confirmed model email events, and use neutral content progress until a pacing rule is chosen. | 01, 07, 08 |

## Visual acceptance when porting

Compare model at 360, 390 and 430 CSS pixels; admin at 1280 and 1440, including a typical shorter laptop viewport. These are proposed verification widths matching the intended devices, not new fixed-width product requirements. Keep normal responsive browser behavior.

Check both themes, long product/model names, realistic small and large figures, many rows, keyboard focus, touch targets, modal/sheet focus and scrolling, text zoom, image aspect ratios, chart taps, browser Back, deep links and content below the fold. Never hide a meaningful order-status filter merely because one phone is narrow; wrap/scroll the controls appropriately.

Keep large page explanations out of the interface. One-line inline status, concise tooltips and specific detail views can carry the required distinctions. Do not copy the export's outer “Complete prototype” banner, review scenario controls or open-decision notes into the app.

## Gaps to design within the approved system

The exported dashboards are not a complete specification for sign-in/reset/application/waiting screens, real validation, staff permissions, protected data errors, setup review, upload retry or every empty state. Apply the existing approved tokens and components to these flows. Bring a screenshot of any materially new interaction to the owner; routine loading/focus/error implementation does not require another entire design project.
