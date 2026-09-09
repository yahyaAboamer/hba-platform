# Repository baseline and implementation map

Repository: `https://github.com/yahyaAboamer/hba-platform`.
Inspected local commit: `025d8a8b059978e6c8113d3c998465be80730f91`, 4 September 2026. Local status clean. Remote HEAD **not verified**: HTTPS git required credentials and connected GitHub branch read returned 404. This audit is a concrete baseline, not a claim about inaccessible newer code.

## Reuse the existing application

FastAPI, SQLAlchemy 2, PostgreSQL and Alembic serve a React 19 / TypeScript / Vite 6 frontend with React Router. Python requirement is >=3.12; frontend Node requirement is >=20.19. Use its lockfile and existing development/test setup. Do not replace this with Next.js, a new authentication system or a second database merely to import the design.

Read `CLAUDE.md`, `docs/plans/2026-09-04-continuation-handoff.md`, the current README, active environment instructions and relevant ADRs before coding. `docs/limits.md` is long: search for the active subject rather than repeatedly dumping the whole document.

## Existing implementation versus needed work

| Area | Existing files / contracts | Use in the redesign |
|---|---|---|
| Routes and shells | `frontend/src/App.tsx`, `components/Layout.tsx`, `components/AffiliateLayout.tsx`, `screens/AffiliatePortal.tsx` | Replace visual/navigation composition while keeping session gating and pending-application flow. Move old secondary routes into approved information architecture; explicitly retire reopen. |
| Tokens / themes / formatting | `styles/tokens.css`, `styles/portal-accent.css`, `styles/portal.css`, `lib/theme.ts`, `components/Money.tsx`, `lib/money.ts` | Port approved green/dark/light tokens deliberately. Update accent-isolation expectations to the approved palette; keep isolation. UI formatting uses server money, not copied prototype arithmetic. |
| API client / security | `frontend/src/lib/api.ts`, `app/api/deps.py`, `app/api/auth.py`, `app/core/permissions.py` | Reuse sessions, CSRF, authentication, invitation/reset, permission gating. Separate model-owned endpoints from admin IDs. |
| Access / onboarding | `SignIn.tsx`, `FirstRun.tsx`, `AcceptInvitation.tsx`, `ResetPassword.tsx`, `Apply.tsx`, `InviteModel.tsx`; `app/api/applications.py`, `services/applications.py`, `services/invitations.py` | Reskin actual forms and waiting states; extend optional profile fields, preserve required payout/code setup. Do not lose screens absent from final dashboard exports. |
| Models and codes | `Affiliates.tsx`, `AffiliateDetail.tsx`, `AddHouseCode.tsx`; `app/api/affiliates.py`, `services/affiliates.py`, `services/codes.py`, `models/affiliates.py` | Shared profile, contacts/measurements/start history, archived/inactive history, existing code verification/replacement and house accounts. Current profile only has name/phone/status/kind/core timestamps, so shipping/measurements need deliberate schema/API work. |
| Compensation | `Compensation.tsx`; `app/services/compensation.py`, `app/models/compensation.py`, POST `/api/affiliates/{id}/compensation` | Existing dated periods, type/rate validation, overlap protection and approved-month protection are useful. Add one selected-month transactional operation that preserves unaffected ranges; existing effective-start endpoint does not implement this by itself. |
| Targets | `Targets.tsx`; `app/api/targets.py`, `services/targets.py`, `models/targets.py` | Reuse required/achieved/verification rules; implement clear monthly editor, live target grid, historical outcome-only mode, model self view. Do not conflate setting a target and recording completion. |
| Shopify transport and jobs | `app/services/shopify/client.py`, `queries.py`, `normalise.py`, `sync.py`, `bulk.py`, `webhooks.py`, `fulfilment.py`; `app/services/jobs.py`, `reconcile.py` | Reuse transport, verified fulfillment extraction, durable jobs and reconciliation. Baseline API version is 2026-07. Add paginated products/variants/media/line items and a separate protected recipient path; preserve idempotency across all ingest paths. |
| Recipient matching / wardrobe | No corresponding production catalogue/wardrobe API or screens in inspected checkout | New persistence and endpoints for catalog, recipient matching, per-product shipment history, wardrobe and promotion requests. Do not extend the commission index with customer PII. |
| Commission engine | `app/services/commission/state.py`, `base.py`, `calculate.py`, `attribute.py`, `backfill.py`; `models/attributed_orders.py` | Baseline pays Delivered only and has late-delivery carry. Change to Pending + Delivered; do not discard existing attribution, original money evidence, Cairo month, post-delivery freeze or rounding invariants. |
| Approval / reconciliation | `Payroll.tsx`, `PayrollApprove.tsx`, `PayrollReopen.tsx`, `PaymentReconcile.tsx`; `app/api/payroll.py`, `services/payroll.py` | Keep immutable snapshots and per-model approval, remove reopening action/API capability for V1, add explicit late-failure decisions/allocation. Preserve old versions as read-only history. |
| Actual payments / proof | `Payments.tsx`, `PaymentRecord.tsx`, `AffiliatePayments.tsx`; `app/api/payments.py`, `services/payments.py`, `services/payments_state.py`, `services/proof.py` | Already has real recording, allocation, partial-payment handling, proof and adjustment machinery. Extend with the new correction ledger and precise totals; avoid a parallel second payment subsystem. |
| Destinations | `AffiliatePayout.tsx`, `MyPayout.tsx`, `lib/payouts.ts`; `app/services/payouts.py`, `app/api/affiliate_self.py` | Existing authorized full reveal and InstaPay anchor can be reused. Model changes require current password. Previous destination versions remain immutable. Review bank-field semantics in D06. |
| Model data | `MyMonth.tsx`, `MyOrders.tsx`, `MyYear.tsx`, `MyGrow.tsx`, `MyPayments.tsx`, `MyDetails.tsx`, `MyPolicy.tsx`; `app/services/portal.py` | Reshape Home/Orders/Targets/Ranking/You; build missing APIs and use authoritative new financial service. Current months derive from orders/payroll, which needs actual collaboration start handling. |
| Settings / operations / notices | `Settings.tsx`, `DataPanel.tsx`; `app/api/operations.py`, `staff.py`, `policy.py`, `audit.py`; services `notification_prefs.py`, `notifications.py`, `staff.py`, `policy.py`, `audit.py` | Retain support/diagnostic actions and permissions. Adapt attention to requested pop-ups; persist hide/mute with proper semantics. Keep technical health separate from normal user messages. |
| Deployment | `Dockerfile`, `docker-compose.yml`, `railway.json`, `ops/backup/`, migrations and existing CI | Verify actual current targets. Test additive migrations and restore path before data transition. No automatic production push from this handoff. |

## Existing API anchors, verified in this checkout

Use existing request models before proposing replacements. These are **existing**, unlike the suggested extensions in `BACKEND_CONTRACTS.md`.

- Self: GET `/api/me`, `/api/me/months`, `/api/me/earnings/{month}`, `/api/me/year`, `/api/me/payments`, `/api/me/payments/{payment_id}/proof`.
- Payout: GET/PUT `/api/me/payout-destination`; GET `/api/me/payout-destination/changed-recently`; POST `/api/affiliates/{affiliate_id}/payout-destination/reveal`; PUT `/api/affiliates/{affiliate_id}/payout-destination`.
- Notification preferences: GET/PUT `/api/me/notifications`.
- Targets: GET/PUT `/api/targets/{month}`, POST `/api/targets/{month}/verify` and `/unverify`.
- Earnings: GET `/api/earnings/{month}`, `/api/affiliates/{affiliate_id}/earnings/{month}`.
- Payroll: GET `/api/payroll/{month}`, POST `/api/payroll/{month}/approve`. The existing `/reopen` mutation and `/reopened` view must not remain an active back door to the removed workflow.
- Transfers/proof: GET `/api/payments/{month}`, POST `/api/payments`, POST `/api/affiliates/{affiliate_id}/proof`, GET `/api/payments/{payment_id}/proof`, GET `/api/affiliates/{affiliate_id}/payments`.
- Adjustments: POST `/api/adjustments`; evaluate reuse carefully against new source/destination and decision semantics rather than assuming it already fulfills them.
- Orders: GET `/api/orders/{month}`, `/api/orders/lookup/{order_number}`.
- Operations: `/api/operations/sync`, `/failed-jobs`, `/unregistered-codes`, `/verify-code`, `/shopify-scopes`, `/order-facts`, `/start-import`, `/notifications`, `/attention`, `/notifications/retry` with their existing methods/permissions.

## Invariants to retain

1. Integer piastres; basis-point rates; exact aggregate arithmetic; one final half-up rounding rule. All financial authority is server-side.
2. Business month in Africa/Cairo. Never slice a UTC timestamp or use the laptop clock to assign payroll month.
3. Immutable payroll snapshots, payment transactions/allocations/adjustments, payout destinations and policy versions, including database append-only triggers. Never disable these to make migration or editing convenient.
4. No customer PII in commission `order_index`/attributed-order storage or model commission responses. The new shipping-phone use requires a separate restricted ingest/index design and updated tests that preserve this boundary.
5. House accounts never payable and excluded from model rankings. Code attribution is not guessed from a submitted string without existing validation.
6. Receipts are actual uploads with digest, format/content validation, size handling and ownership checks. Reuse the existing PostgreSQL proof strategy and `frontend/src/assets/instapay-link.png` for the instructional graphic.
7. Approved money is distinct from actual money sent. A new calculation cannot rewrite an earlier transfer or its destination.

## Repository instructions requiring explicit reconciliation

ADRs 0012/0029/0030 and parts of payroll documentation describe delivered-only earning, late delivery or reopening; these are superseded for the new workflow. ADR 0038 and the old continuation document describe red styling; final HTML supersedes that visual direction. Update the relevant docs with the actual new implementation rather than deleting their history.

The old CLAUDE workflow says push main and production together while no real models are onboarded. That condition must be checked against current reality. This request only prepares an implementation handoff, so no branch promotion is currently authorized. A later implementation prompt can authorize local development; production release should use the reviewed staging result and current deployment policy.

The old docs also say staging and production share one Shopify shop and not to launch a staging bulk import. Verify current topology, retain that restriction unless deliberately changed, and coordinate jobs at the shop level. Database isolation alone does not isolate Shopify operations.

Historical docs report 1,558 backend tests and 87 frontend tests. Those are old reported counts, **not results from this review**. The baseline phase records current commands and actual results.
