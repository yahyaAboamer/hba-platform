# HBA — implement the approved interface faithfully

I am correcting the acceptance standard for this work. Implement the approved admin and model interfaces throughout the existing application. Match their structure, content, wording, typography, colors, spacing, surfaces and interactions. Do the implementation and verification; do not stop after proposing a plan.

The Targets and Payments screenshots are examples of a platform-wide problem. They are not the entire scope. Every main tab, nested tab, secondary page, drawer, modal, menu, form, detail view and meaningful state belongs in this work.

## 1. Establish the current baseline and source of truth

Inspect the current working tree, branch, commits and deployed build. Preserve unrelated work. The earlier HBA code bundle may already be integrated: do not reapply it, reset the repository to its old base, or assume its list of unfinished work is still current.

The visual references are:

- `docs/redesign/designs/Admin Dashboard.dc.html`
- `docs/redesign/designs/Affiliate Portal v3.dc.html`

Use their supporting assets and actual rendered behavior. If paths have moved, locate these exact exports and verify their identity. Keep the reference files unchanged. Read their markup, styles and event handlers, and open them in a browser. Source inspection and rendered inspection are both required.

The four supplied screenshots are, in order: staging Targets, approved Targets, staging Payments, approved Payments. They demonstrate specific mismatches. The supplied conversation explains previous decisions and failed approaches; the agent's claims of completion in it are not acceptance evidence.

Authority:

1. My explicit later business/design decisions override the earlier prototype where they conflict.
2. Otherwise, the approved HTML defines the interface, including exact static wording.
3. Existing code is an implementation to correct, not a competing design authority.

Known later decisions include keeping **E£**, whole-pound payout rounding, optional feature-request messages, the approved whole-year target-requirements capability and target-confirmation behavior, and the other closed decisions already recorded in the project. Do not reopen settled questions. Whole-pound payout rounding does not authorize rounding sales or rewriting the integer-piastres calculation policy everywhere.

The export's outer “Complete prototype” wrapper, laptop-width controls, review-scenario buttons and fake phone furniture are demonstration tools, not product UI. Do not reproduce them in the application. Real names, amounts, months, products and images come from the backend; do not copy sample data into live screens.

## 2. Correct the method that caused the drift

Your earlier font/color “voices” scan was insufficient. An element using a color and font size found somewhere in the reference does not prove that it uses the values assigned to its corresponding reference element. Matching the number of columns does not establish matching layout. Existing functionality, green tests and a successful build do not establish visual fidelity.

Compare corresponding elements: reference page title against candidate page title; reference payment card against candidate payment card; reference row action against candidate row action. Check position, containing surface, dimensions, spacing, text and behavior as well as computed styles.

Do not retain an old component merely because it already works. Reuse its API/service logic where useful, and replace its presentation when the approved structure differs. Remove obsolete rendered sections, surplus copy and superseded styles. Do not leave duplicate legacy controls below the new design or hide the old application behind CSS.

Do not redesign, embellish, add explanatory paragraphs, change labels to your preferred terminology, or invent another navigation structure. Frontend-design skills may assist faithful implementation; they do not authorize creative reinterpretation of an already approved design.

Preserve required financial, security and authorization safeguards. Separate the safeguard from its old presentation. A required confirmation does not justify keeping an unrelated legacy footer. For a later-approved function absent from the export, document the precise difference and fit it into the closest existing interaction pattern. Ask one focused question only if its placement requires a genuinely unresolved design choice; continue unaffected work.

## 3. Inventory the entire interface before calling anything complete

Create or update `docs/redesign/parity/SCREEN_MATRIX.md` from the actual exports and application routes. Enumerate every reachable view and relevant state; do not assume that six sidebar tabs or seventeen top-level screen flags cover everything.

Cover at least:

- Admin shell and account menu; Home and notice actions; Models directory, invitations/applications and approval/setup flows; each profile section (Overview, Wardrobe, Performance, Targets, Payments); Products, coverage, shipments and promotion editor; Targets in both modes; Payments list, individual model/month detail, approval, record-payment, receipts and corrections; compensation-history/month selection; every Settings subsection; order lists/details and any other reachable view in the approved exports.
- Model shell and all five tabs: Home, Orders, Wardrobe, Targets, Ranking. Include calculation views, order details, top sellers, You/account menu, personal details, measurements, payout settings, payment history and receipts, notification preferences, theme and help/FAQ views. Derive the actual navigation pattern from the export rather than assuming every secondary view needs another tab.
- Selected/unselected, expanded/collapsed, saving/saved/error, empty/loading/retry, relevant payment states, historical/current month, and sparse/long content where these affect presentation or behavior.

For each entry record: reference selector/view, application route/component, entry and return actions, data/API source, applicable later decision, current differences, before/after screenshot paths, functional checks and status.

Use statuses such as Unreviewed, Mapped, Implemented, Visually verified, Functionally verified, Blocked. Do not label an entire area complete while its nested views remain unreviewed.

## 4. Normalize comparisons correctly

The supplied screenshots have different viewport widths, and the reference is inside a demonstration frame. Comparing their full-image pixel coordinates is invalid.

Compare the actual application rectangle at the same CSS viewport width and height, browser zoom, device scale factor, theme and scroll position. Use the approved 1280/1440 desktop configurations and approximately 390px model width, then check responsive behavior at another phone width. Do not make the desktop app a fixed-width screenshot just to match the export's outer wrapper.

Wait for fonts and assets to load. Inspect the computed font family and the font actually available; assigning a font name in CSS does not prove it loaded. Match each element's font size, weight, line height, letter spacing and wrapping. Measure sidebar width, header height, content padding, column widths, input/button dimensions, row height, radii, borders, backgrounds and gaps from the reference.

Use matching deterministic fixture data in an isolated local/test environment for visual comparisons. Match names, text lengths, row counts, amounts and selected states where possible. Do not alter production records to manufacture matching screenshots. Use real API integration checks separately. Mask only genuinely variable pixels when justified, never a mismatched panel or paragraph.

Produce side-by-side captures and aligned overlays/differences. Inspect these images yourself. Do not declare “zero mismatches” from token-set membership, a changed test snapshot, or a threshold that tolerates obvious structural differences.

## 5. Start by proving the method on Targets and Payments

Targets must reproduce the approved toolbar and table, including:

- Search, the selected-state styling of Record achieved / Set requirements, and the top-right Save changes action.
- The contained table surface, header styling, column alignment, compact row spacing and exact mode-specific wording.
- Correctly sized numeric inputs with the “of N” text beside them where the reference places it, not underneath oversized inputs.
- Arrangement text, status presentation and last-updated information in their corresponding positions.
- Unsaved/discard behavior and later-approved requirements/confirmation actions, without an unapproved block of explanatory prose below the table.

Payments must reproduce:

- Three separate rounded summary cards with their own surfaces, gaps and semantic value colors; not one flat strip with vertical dividers.
- The reference filter buttons, selected state, counts and search placement above the table.
- The Model / To receive / Destination / State / Next action table, with the corresponding hierarchy, concise labels, badges, row heights and action styling.
- Recorded amounts and payment destinations in their intended places. Keep E£ as I approved. Show authorized destination details and open the exact saved InstaPay link in the appropriate payment view; do not fabricate or unnecessarily mask details the finance workflow requires.
- State-appropriate Review / Record payment / Open actions with the correct model and month maintained through navigation and reloads.

Do not copy the reference's sample “Fully paid” states into records that are awaiting approval. A difference in business state is legitimate; inventing long alternative wording or a different layout for the same state is not. Identify each card/row amount's actual meaning before binding it; do not interchange earnings, approved amounts, transfers and remaining balances just because they are all money.

These two screens establish the method. After verifying them, continue across the complete matrix; do not stop and treat the examples as the finished scope.

## 6. Make the interface genuinely functional

Bind every approved control to real state and backend behavior. Verify save/cancel, filters, tabs, pagination where specified, return navigation, deep links, copy/open actions, receipts and retained month/model context. Eliminate fake success, dead buttons and placeholder implementations.

Where the backend cannot supply required content, implement the missing contract with focused tests. Do not silently omit the section, fill it with unrelated aggregate data, or calculate financial policy again in React. In particular, personal top sellers must use that model's sales; wardrobe ownership and feature eligibility are separate facts; feature requests remain passive and only eligible models see them.

Preserve immutable approvals, separate actual transfers, correction history, target revisions, authorization and customer privacy. Approved-but-unpaid is not paid. Historical months must follow the approved history rules. Connection failures must not look like zero earnings, no payments or an empty wardrobe. Use concise loading/empty/retry states consistent with the design.

## 7. Work in verifiable batches and leave durable evidence

Implement shared foundations plus Targets/Payments first. Then complete remaining admin primary and secondary views, followed by all model views and shared regression checks. Keep changes reviewable and checkpoint them; do not repeatedly rewrite the plan without completing screens.

For each batch:

1. Capture and map the reference and existing implementation.
2. Implement the exact presentation and required wiring.
3. Render again; inspect aligned comparisons and correct remaining differences.
4. Exercise relevant actions and run focused tests, typecheck and build. Broaden regression checks for concrete risk or required project gates. Passing tests do not replace visual inspection.
5. Update the matrix with actual evidence and remaining differences.

Do not weaken or delete valid tests to make the redesign green. Update tests that encode superseded layout/copy only when their former behavioral guarantee is still covered. Backend tests must use a positively identified disposable database; the project's test setup can drop its schema. Never point it at development, staging or production to save setup time.

Before any already-authorized merge/promotion, complete the applicable batch checks. Preserve my standing instruction to keep production aligned with staging after verified merges; do not mistake that deployment instruction for proof that the design has passed. After deployment, verify the expected build actually loaded, hard-refresh stale assets as needed, and inspect the deployed result. Do not change deployment permissions through this prompt.

If browser access or rendering fails, continue useful source work but mark visual verification blocked. State precisely what access is missing and request only that. Do not replace visual evidence with a computed-style scan or claim completion anyway.

## 8. Completion standard and next action

A screen is complete only when its structure, copy, corresponding computed styles, visible rendered result and actual interactions have all been checked. Legitimate differences are limited to real data, explicitly approved later decisions, and documented platform rendering variation—not an alternative design that seems close enough.

Final evidence must cover the full matrix, including secondary views, both themes, responsive checks and meaningful states. Report remaining mismatches plainly. “Built,” “deployed,” “has five columns,” and “all tests passed” are not synonyms for “matches the approved design.”

Start now: inspect the current repository, establish the complete inventory, then implement and visually verify Targets and Payments using this method. Keep reporting concise progress while carrying the work through the remaining screens. Ask me only about a specific unresolved conflict or access requirement, not whether to continue work I have already requested.
