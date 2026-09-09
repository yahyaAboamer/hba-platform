# Implementation roadmap

Build in the existing repository, one connected batch at a time. Each feature batch includes the required schema/service/API, its admin/model interface and meaningful verification. A decorative frontend completed before the financial model would conceal the most consequential gaps.

## Phase sequence

| Phase | Batches | Working result the owner reviews |
|---|---|---|
| 00 — Establish the baseline | Current checkout, instructions, running app, test/database setup, route coverage, decision dependencies | Actual current-state report and confirmed plan; no application edits yet |
| 01 — Shared UI foundations | A: tokens/components; B: admin/mobile shells and route/permission map | Approved theme on real authenticated shells, both themes, existing flows still reachable |
| 02 — Models and setup | A: invitations/applications/directory; B: shared profile and self edits; C: monthly terms + historical readiness | A model can join, have valid details and distinct terms saved for selected months |
| 03 — Products and wardrobe | A: catalog/line items ingestion; B: recipient matching/backfill; C: product rosters, both wardrobes and feature requests | One Shopify shipment appears consistently on both sides; promotion audience is correct |
| 04 — Targets | A: required/achieved weekly recording; B: verification/history/self view | Marketing records actual progress; models see it; guarantee evidence stays distinguishable |
| 05 — Financial rules | A: pending-inclusive calculations; B: immutable approval; C: late failures, absorption and carry allocation | Correct figures and documented source/destination corrections across real services |
| 06 — Payments | A: admin totals/destinations/recording; B: history/proof/model payment views | Finance can see where to pay, record a real transfer and inspect its unchanged evidence |
| 07 — Performance screens | A: model Home/Orders/charts; B: ranking/top sellers/admin Home/profile performance | All headline numbers reconcile with their underlying records and approved statements |
| 08 — Settings and notifications | A: staff/settings/support; B: notice persistence and email preferences/help | Existing admin operations and concise user notices work with the new navigation |
| 09 — Rehearsal and release | A: migration/reconciliation; B: cross-role visual/UAT; C: reviewed release and post-release checks | Complete staging app, verified historical setup and a concrete release candidate |

00→01→02 is the recommended start. 03 and 04 can be done in either order after their profile/terms dependencies; 05 requires the relevant 02/04 outputs. 06/07 require financial contracts from 05. 08 may be brought forward if it serves an active batch. 09 is the final integration gate. This is sequencing guidance, not an instruction to run parallel agents or to implement every phase in one session.

The agent must not switch the live commission policy during Phase 05 development. Use local/staging isolation and a reviewed cutover mechanism. An unfinished UI branch must not alter ongoing real payroll.

## Each batch follows the same loop

1. Read `STATUS.md`, the active prompt and its referenced rules/paths/checks. Confirm the baseline commit and dependency status.
2. Identify the smallest complete behavior to implement. If it is too large, write a bounded sub-batch before coding; do not omit backend work to claim the screen is finished.
3. Implement in a working branch/worktree based on the current repository, preserving unrelated work. Reuse services and existing contracts where they fit.
4. Run the checks relevant to that behavior. For money/auth/migration changes, include the affected regression suites and the required database invariants. Frontend changes need build and appropriate behavior/visual checks. Do not write tests that merely duplicate CSS or mock implementation details.
5. Open the running screens and capture relevant states using synthetic data. Compare with the selected design source. If no browser is available, state that limitation and leave visual acceptance incomplete.
6. Update `STATUS.md`, the coverage/check CSVs and a report from `templates/BATCH_REPORT.md`. Include actual commands/results, commit, migrations, remaining limitations and the exact next prompt/batch.
7. Present the owner the working result and what to try. Stop at the requested batch boundary. Start the next batch when the owner sends its prompt/continuation. Do not treat visual acceptance as permission for live financial writes or release.

## Definition of a completed feature

The design matches; the real API persists and reloads correctly; errors and empty states are truthful; permissions work on the server; relevant data migration/backfill exists; meaningful tests and visual comparison are recorded; old necessary entry points still resolve; no fixture amounts or mock actions ship.

A screenshot of a populated page alone is not completion. A passing service test alone is not visual implementation. Each report needs both forms of evidence where relevant.

## Review without reading every engineering file

For each batch the owner should receive: what changed, a preview/screen recording, a small list of tasks to try, outstanding business decisions for that batch, and test status. The detailed package is primarily the agent's working contract; the owner reviews concrete behavior progressively.

If changing agents, provide the same repository branch plus this updated folder. The new agent reads `STATUS.md` and the latest batch report before choosing its next action. Do not rely on an old chat transcript or a claim that the previous agent remembers the project.

## Immediate next action

Connect the repository, place this package under `docs/redesign/`, and send `prompts/00_START.md`. Phase 00 should establish the current facts and produce a baseline report. It should not start rebuilding all tabs or touch production.
