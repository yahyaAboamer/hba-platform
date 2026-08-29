# 0034. A temporary second service splits staging from production

**Status:** Accepted — explicitly temporary, see Consequences
**Date:** 2026-08-30

## Context

Since the Amsterdam move (ADR 0031), one Railway service (`hba-platform`) has
served both `staging` and `production`, both tracking `main`. Every merge
deployed both simultaneously. During a session of heavy, fast-moving changes,
the business asked for a real gate: staging free to move on every merge,
production only moving when told to.

Two mechanisms were tried and ruled out by testing them directly, not by
reading documentation and assuming:

- **`railway environment edit --service-config source.branch`** — the CLI
  path several Railway guides show for per-PR environments. Returned "No
  changes to apply" for every value tried, including one that plainly
  differed from the current branch. Not a permissions issue; the path simply
  did not take effect through this command, on the current CLI (checked
  before and after upgrading it).
- **`connect-service-source` / `railway service source connect`** — proved
  live, deliberately at low cost (see below), to set a service's branch **for
  every environment it exists in at once**, not per-environment. Confirmed by
  watching it flip `staging`'s branch the moment production's was changed.

Railway's own model, once both of those were exhausted: **branch isolation
between environments requires genuinely separate services**, each with its
own source, matching what `duplicate environment` builds for a fresh
environment — not something retrofittable onto two environments that already
share one service.

## Decision

**Staging got the new service, not production.** `hba-platform-staging` is a
fresh service, scoped only to the `staging` environment, tracking `main`,
with its own generated domain. The original `hba-platform` service keeps its
public domain, its data, and everything about it — only its tracked branch
changed, from `main` to a new `production` branch that starts as an exact
copy of `main`'s tip.

This was the deliberately lower-risk half of the split. Moving *production*
to a new service would have meant moving its live public domain — Railway
domains cannot be reattached to a different service, only newly generated —
which is a real, if brief, disruption to something real, even with no models
onboarded yet. Moving staging's domain instead costs nothing: nobody depends
on `hba-platform-staging.up.railway.app` staying the same string, only on
staging behaving like staging.

**Every variable on the new service is a Railway reference, never a typed
value** - `${{hba-platform.BREVO_API_KEY}}` and so on, `${{Postgres
.DATABASE_URL}}` for the database directly. Chosen for two reasons: it meant
not one credential had to be read to set this up, and a credential rotated on
the original service is picked up by the new one automatically, with nothing
to keep in sync by hand.

**The old `hba-platform-staging.up.railway.app` domain is retired, not
deleted.** It still answers - the same shared service now serves `production`
branch content there too, since the branch-scoping proved global - but it is
stale and must not be linked or relied on. `docs/operations.md` says so.

From here: merges to `main` deploy `hba-platform-staging` immediately. Nothing
reaches `hba-platform` (production) until `production` is fast-forwarded to
`main` and pushed, on request.

## Consequences

**This is explicitly temporary, on the business's own instruction.** The
plan, as stated: run with this while the platform is still changing quickly,
then collapse back to the single-service model within days once things
settle - discipline (ask before anything risky reaches production) standing
in for the technical gate once the gate has done its job. Reverting means:
decommissioning `hba-platform-staging`, repointing the original service's
branch back to `main`, and deleting the `production` git branch. Recorded in
this session's memory as well as here, so the reversal does not need
rediscovering.

**A second service is a second thing to keep in sync by hand** for exactly as
long as this lasts - a build setting changed on one has to be remembered on
the other, since nothing keeps them linked beyond the variable references set
up at creation.

**The retired staging domain is a live foot-gun if forgotten.** Anyone who
still has `hba-platform-staging.up.railway.app` bookmarked now reaches
*production* content under a *staging*-sounding name. Worth removing
entirely once the temporary period ends, rather than leaving it live
indefinitely.

## Alternatives considered

**Moving production's domain instead.** Rejected for cost against benefit:
production is pre-launch (no models registered yet) so the actual disruption
would have been minor, but there was a strictly safer equivalent available,
and no reason to accept even a small risk to the side that matters when the
side that does not achieves the identical outcome.

**A custom domain, so either side could be repointed via DNS instead of a new
Railway domain.** Not available - the platform currently runs entirely on
Railway-generated subdomains.
