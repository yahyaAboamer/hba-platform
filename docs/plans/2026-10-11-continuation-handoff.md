# Where the work is — 11 October 2026 (Operations and security fixes on production)

Supersedes `2026-10-07-continuation-handoff.md`; its open items are carried
under *Remaining*.

## The exact position

Re-read the remote before describing it (`git ls-remote --heads origin main production`).

| | |
|---|---|
| **Branch** | `repair/batch-2`. `origin/main` (staging) and `origin/production` are on the same commit, the one carrying this handoff. |
| **Production** | Promoted from `c91aff0` on 11 October on the owner's explicit order (fast-forward). It now has the Operations dashboard (ADR 0057) and the security fixes below. Railway keeps deployment `34b26e45` (`c91aff0`) for rollback. |
| **Migration head** | `f6b2d8a41c57` on both. Production ran the six Operations migrations at 00:40 UTC; the role migration took its lock first time. |
| **Backup before it** | `production/2026-10-11T000224Z.dump` (daily `db-backup-production`). |
| **Production config** | Owner set the Bosta and E-stebdal keys on the production service (redeploy `b446fd63`, 08:10 UTC) and invited the operations manager. |
| **Backend** | whole suite through `run-suite.sh`, 96/96 files, at `96d3832`. Frontend unchanged since 7 October. |

## What shipped since 7 October

**Security fixes** (`96d3832`), from a source-only audit on 7 October. Each has
a test that failed before the fix:

- `create_affiliate` and `update_details` refuse to attach a profile to, or
  change the sign-in email of, an account holding staff access the actor does
  not hold (`StaffAccountProtected` → 403, the `can_grant` rule).
- `is_shop_domain` (ASCII-only, whole-value match) guards the Shopify store
  domain in both `ShopifyClient` and the Settings save.
- `POST /api/adjustments` takes `hold_money_gate` before `adjust()`.
- The model's payout-reveal route commits its audit row.

## Remaining, in order

1. **Owner acceptance of Operations, now on production**: Shopify cards against
   Shopify admin; E-stebdal *Needs review* against its list; Bosta B5 against
   *Awaiting your action*, spot-check B1, B2, B6; one Bosta and one E-stebdal
   link (both addresses are assumed); sign in as the operations manager.
2. **Security items still open** (details with the owner, not in the repo):
   sign-in throttling, a body-size limit on the Shopify webhook, the InstaPay
   link scheme, payment allocations scoped to the paid model, Python
   dependency pinning. Each wants a decision, then a test-first fix.
3. **Release gates**, open and now behind production rather than ahead of it:
   reconciliation against a restored copy, the `SETTINGS_ENCRYPTION_KEY` cases,
   and `a6b1c4e20006` on a restored copy.
4. **`SETTINGS_ENCRYPTION_KEY` on staging is not set**, so nothing can be saved
   from Settings there.
5. **Optional, from the database review:** a partial index for
   `ops_bosta_delivery`; a 500 when two operations-manager invitations are
   accepted in the same instant; no foreign key on
   `ops_integration_key.updated_by`.
6. **Shell at 390**: the account row sits under the tabs, not in the brand row.
7. Carried: owner acceptance of the Models tab; the admin sidebar's sideways
   scroll at 390; mapping the flows with real data, then the admin audit tab by
   tab (Payments next). The `feature/operations-dashboard` worktree can go.

## Decisions not to reopen

- ADR 0057 as written: Operations only reads; Bosta never decides pay; one
  operations manager; no customer details stored or shown.
- A source that fails is a dashboard state, not a failed job.
- A staff member may manage another account only if they hold all of that
  account's access — the same rule as invitations.

## Corrections worth knowing

- `run-suite.sh` keys passes on the HEAD commit: commit first, or use a fresh
  `OUT_DIR`, or earlier passes are trusted for code they did not test.
- Staging and production both report `environment: production`, so `Secure`
  cookies and HSTS are on in both.
- Bosta's search wants `stateCodes` as strings; E-stebdal answers a wrong key
  with a 500.
