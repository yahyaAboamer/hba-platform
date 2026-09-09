# HBA implementation handoff

Prepared 9 September 2026. This package implements the entire approved admin and model redesign in the existing HBA repository. It is not a new application, a video project, or a request to paste an HTML mockup into production.

## What the owner should do

1. Connect **one** coding agent to `yahyaAboamer/hba-platform`, preferably in a local checkout where it can run the application, database tests and browser previews. Codex or Claude Code can use this same package; you do not need both.
2. Extract this folder into the repository as `docs/redesign/`. The intended path is `docs/redesign/START_HERE.md`, without another nested handoff folder. Do not overwrite the repository's `CLAUDE.md`, `AGENTS.md`, environment files or source code with this package.
3. Give the agent the contents of `prompts/00_START.md`. That prompt starts **only the baseline phase**. The agent should inspect the current checkout, compare it with this review, and establish a runnable starting point before it changes application behavior.
4. Review its baseline report. Answer only the decisions that block the next batch. Then send the next numbered prompt. Each numbered prompt contains smaller batches; use its first batch initially and review its result before moving on.
5. At each review, ask to see the working screens and the result of the checks. The agent must update `STATUS.md` and leave a handoff for the next session. You should not need to repeat this conversation.
6. Test the completed product in staging, reconcile historical data and new calculations, and then schedule release. This package does not authorize a production deployment or edits to live financial data.

Using a coding agent does not mean it starts over. It receives the existing repository **plus this package**. The repository provides the working application; this package supplies the new designs, business rules, implementation sequence and review checks. No Figma account, Claude Design subscription or video-generation tool is required for implementation.

## Verified design sources

| Use | File | Finding |
|---|---|---|
| Models on phones | `designs/Affiliate Portal v3.dc.html` | Present in the latest ZIP; changed from the previous export. |
| Admin on laptops | `designs/Admin Dashboard.dc.html` | Present in the latest ZIP; changed substantially from the previous export. |

These are the correct working references based on the owner's identification and the archive comparison. The ZIP does not independently certify an approval timestamp. Earlier designs have deliberately not been included as competing references. Both selected HTML files and their bundled dependencies are unchanged, with SHA-256 hashes in `evidence/source-manifest.json`.

Keep the approved black/green theme, concise copy, density, hierarchy and navigation. Correct data and behavior problems during implementation without initiating another visual redesign. Explain any necessary visual deviation and show it for review.

The HTML depends on Claude's export runtime (`support.js`, `_ds/`), some external fonts/scripts, and mock state. Open it through a local static server if your browser needs one. For example, from `docs/redesign/designs/`, `python -m http.server 8765`, then open the desired HTML in your browser. This is a design preview, not the production implementation. Do not ship the export runtime, example accounts, review controls or sample finance functions into the application.

## What to read

| Reader / task | Files |
|---|---|
| Owner: process and next step | This file and `IMPLEMENTATION_ROADMAP.md` |
| Agent: start or resume | `prompts/00_START.md`, `STATUS.md`, `PRODUCT_RULES.md`, then the active phase prompt |
| Product meaning | `PRODUCT_RULES.md`, `DECISIONS.md` |
| Every screen and action | `SCREEN_AND_ACTION_MAP.csv` |
| Existing code and integration | `REPOSITORY_AUDIT.md`, `BACKEND_CONTRACTS.md` |
| Prototype corrections | `DESIGN_REVIEW.md` |
| Financial examples and verification | `ACCEPTANCE_CHECKS.csv`, `evidence/financial-examples.json` |
| Data transition and release | `MIGRATION_AND_RELEASE.md` |
| Session continuity | `templates/BATCH_REPORT.md`, `templates/DECISION_RECORD.md`, `STATUS.md` |

Read the active area, not every historical repository document on every turn. Relevant repository invariants still apply. Latest explicit owner decisions supersede older product choices; they do not authorize bypassing access controls or changing permissions by inference.

## Evidence limits

Reviewed local repository commit: `025d8a8b059978e6c8113d3c998465be80730f91` (4 September 2026). The checkout was clean. Git remote verification failed for lack of authentication; the connected GitHub read returned 404. We have **not** established whether the remote has newer work.

The selected HTML source, its changes, the export thumbnail and targeted prototype logic were inspected. The cloud browser refused local-file navigation under its URL policy, so there was no completed browser walkthrough. Full application tests were not run as part of this planning task. The implementation agent must verify its own current baseline and compare running screens before reporting a feature complete.

## What is ready, and what is not

Ready: the visual direction, whole-product scope, key business rules and phased implementation instructions. The owner does not need another round of whole-dashboard mockups.

Still needed at the relevant phase: the actual live-payment boundary, model start dates and historical terms/outcomes, a few policy choices in `DECISIONS.md`, and verified Shopify access. These are explicit dependencies; the agent should proceed with independent work while a dependent decision is pending.
