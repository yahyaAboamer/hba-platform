# 0031 — The platform runs in Amsterdam, not California

**Status:** Accepted
**Date:** 2026-08-29
**Related:** [0027](0027-provisional-figures-are-sans-agreed-figures-are-mono.md)

## The question

The business asked whether the platform could be made faster. Measuring rather
than guessing turned up something that was never a decision at all.

Railway runs two separate layers. **Edge PoPs** are where traffic enters —
ours is Paris (`x-railway-edge: cdg1`), about 69 ms round trip from Cairo.
**Deploy regions** are where the code and the database actually run, and ours
was `sfo`: California.

So every tap in the platform travelled Cairo → Paris → **California** → Paris
→ Cairo. Measured on a warm connection, one request cost **221–238 ms**, and
roughly 150 ms of that was the transatlantic leg doing nothing but travelling.

Nobody chose California. Railway deploys to the account's preferred region by
default, a new account's default is US West, and the staging environment
inherited it from the project. It had been costing every model 150 ms per tap
since the first deploy, and it took looking to find.

## The decision

**Both services, in both environments, run in `europe-west4-drams3a`
(Amsterdam).** The models are in Egypt; Amsterdam is ~3,300 km away and
California ~12,000 km.

**The app and the database move together, database first.** `DATABASE_URL`
resolves over Railway's private network, so today a query is effectively free.
Moving only the app would have put the Atlantic between the app and its
database and made several queries per page much slower than the single request
we were trying to fix. This is the part that would have turned an improvement
into an outage.

Amsterdam over Virginia or Singapore is simply distance: Railway offers four
regions and this is the nearest one to Egypt.

## What it bought

Measured from the same machine, minutes apart:

| | Before (California) | After (Amsterdam) |
|---|---|---|
| Warm request | 221–238 ms | **84–89 ms** |
| First request, cold connection | 448–685 ms | **337 ms** |

**About 2.8× faster on every request**, not only the first — every screen,
every button, every navigation.

## Consequences

**The cost was downtime, once.** Volumes cannot be teleported, so changing a
database's region migrates the disk and the database is offline meanwhile. Both
volumes are small — staging 191 MB, production 225 MB — and both finished in
about 60–95 seconds.

**Nothing else changed.** Domains, private networking, environment variables
and the Shopify webhook addresses are all unaffected, which is Railway's
documented behaviour and held in practice.

**The repository does not pin the region.** `railway.json` sets `numReplicas:
1` and says nothing about geography; the region lives in Railway's own service
settings. There was a real worry that our file would reassert the account
default on the next deploy, so it was tested rather than assumed: staging was
rebuilt from scratch after the move and came back in Amsterdam. Config as Code
is deprecated by Railway from 2026-12-01 in any case, so pinning the region
into a file that is about to stop being read would have been the wrong fix.

**A restored backup carries no region.** Should either database ever be rebuilt
from a dump, whoever does it has to set the region again — it is a property of
the Railway service, not of the data.
