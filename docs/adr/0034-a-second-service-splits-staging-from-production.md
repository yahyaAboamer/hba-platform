# 0034. A second service splits staging from production

**Status:** Accepted
**Date:** 2026-08-30 (revised 2026-09-01: this is the permanent arrangement)

## Context

Since the Amsterdam move (ADR 0031), one Railway service (`hba-platform`)
served both `staging` and `production`, both tracking `main`. Every merge
deployed both simultaneously — there was no gate at all between "merged" and
"live for the models."

Two mechanisms for splitting them were tried and ruled out by testing them
directly, not by reading documentation and assuming:

- **`railway environment edit --service-config source.branch`** — the CLI
  path several Railway guides show for per-PR environments. Returned "No
  changes to apply" for every value tried, including one that plainly
  differed from the current branch. Not a permissions issue; the path simply
  did not take effect through this command, on the current CLI (checked
  before and after upgrading it).
- **`connect-service-source` / `railway service source connect`** — proved
  live, deliberately at low cost, to set a service's branch **for every
  environment it exists in at once**, not per-environment. Confirmed by
  watching it flip `staging`'s branch the moment production's was changed.

Railway's model, once both were exhausted: **branch isolation between
environments requires genuinely separate services**, each with its own
source. It is not retrofittable onto two environments that already share one
service.

## Decision

**Staging got the new service, not production.** `hba-platform-staging` is a
service scoped only to the `staging` environment, tracking `main`, with its
own generated domain `hba-platform-staging-staging.up.railway.app`. The
original `hba-platform` service keeps its public domain, its data, and
everything about it — only its tracked branch changed, from `main` to a
`production` branch that started as an exact copy of `main`'s tip.

This was the lower-risk half of the split. Moving *production* to a new
service would have meant moving its live public domain — Railway domains
cannot be reattached to a different service, only newly generated — a real
disruption to the side that matters. Moving staging's costs nothing: nobody
depends on staging's hostname being a particular string.

**Every variable on the new service is a Railway reference, never a typed
value** — `${{hba-platform.BREVO_API_KEY}}` and so on, `${{Postgres
.DATABASE_URL}}` for the database. Chosen for two reasons: not one credential
had to be read to set this up, and a credential rotated on the original
service is picked up automatically, with nothing to keep in sync by hand.

**The workflow this buys.** Merges to `main` deploy `hba-platform-staging`
immediately. Nothing reaches production until `production` is fast-forwarded
to `main` and pushed, deliberately.

Note which way round this is, because it is the safety property: `main` is
GitHub's default branch, so a pull request opened without thinking targets
**staging**. Reaching production takes an explicit, separate act. The safe
target is the default; the risky one has to be chosen.

## Consequences

**A second service is a second thing to keep in sync by hand.** A build
setting changed on one has to be remembered on the other; nothing links them
beyond the variable references set at creation.

**`hba-platform` still has a service instance in the `staging` environment,
and it cannot be removed.** Railway has no `serviceInstanceRemove`: a service
exists in every non-fork environment or none. That instance is neutralised
rather than deleted — auto-deploy off in staging, domain removed, deployment
taken down. It contributes nothing and must not be revived. Both staging
instances would otherwise share the staging database; that is survivable
(job leasing uses `SELECT … FOR UPDATE SKIP LOCKED`, so nothing is
double-processed) but it is waste, and the two run different code.

**`railway service delete` on `hba-platform` would destroy production.** Its
CLI help reads "Delete a service from an environment," which is false here.
The API's own rule: an `environmentId` scopes the delete **only if that
environment is a fork**. Neither `staging` nor `production` is a fork
(`sourceEnvironment: null`), so a delete scoped to staging deletes the
service in *every* non-fork environment — production included, along with
`hba-platform-production.up.railway.app`, which cannot be reattached. This
is recorded in `docs/limits.md` as well, because it is the kind of thing
found once and needed later.

## Alternatives considered

**Moving production's domain instead.** Rejected: production is pre-launch,
so actual disruption would have been minor, but a strictly safer equivalent
was available and achieved the identical outcome.

**A custom domain, so either side could be repointed via DNS instead of a new
Railway domain.** Not available — the platform runs entirely on
Railway-generated subdomains.

**Collapsing back to one shared service, with discipline standing in for the
gate.** Considered and rejected once the mechanics were understood: with one
service, branch tracking is service-wide, so both environments necessarily
run the same commit. That does not simplify the gate, it removes it. Keeping
two services is the price of having a staging environment that means
anything.
