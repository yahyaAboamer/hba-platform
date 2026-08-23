# 0016. The frontend toolchain is pinned to the builder's Node

**Status:** Accepted
**Date:** 2026-08-23

## Context

The first production build of the frontend failed with:

```
Error: Cannot find module '@rolldown/binding-linux-x64-gnu'
```

The obvious diagnosis - a lockfile generated on Windows lacking the Linux binary
- was wrong. The lockfile contained all fifteen platform bindings.

The real cause was one line earlier in the log:

```
added 25 packages, and audited 26 packages in 1s

npm warn EBADENGINE package: 'vite@8.2.2',
  required: { node: '^20.19.0 || >=22.12.0' },
  current: { node: 'v22.10.0' }
```

Nixpacks provides Node **22.10.0**. Vite 8 requires 22.12.0 or newer, so npm
**silently skipped the platform-specific optional dependency as
engine-incompatible**, and the build then failed looking for it. A skipped
optional dependency is a warning, not an error, which is why the failure
surfaced late and pointed somewhere else.

Requesting a newer Node was not available: Nixpacks pins a nixpkgs snapshot
that predates Node 24, so `nodejs_24` does not exist to ask for.

## Decision

Pin the frontend toolchain to versions every supported Node satisfies, rather
than depending on which Node the builder happens to provide.

| | From | To | Node required |
|---|---|---|---|
| vite | 8.2.2 (rolldown) | **6.x** (rollup) | `^18 \|\| ^20 \|\| >=22` |
| @vitejs/plugin-react | 6.x | **4.x** | `>=16` |
| typescript | 6.x | **5.7** | `>=14.17` |
| oxlint | 1.79 | **removed** | unused, same constraint |

## Consequences

The build no longer depends on the builder's Node version, which is not under
our control and changes without notice.

The frontend runs a version behind the newest tooling. For a project whose
frontend is a placeholder until Phase 3, that costs nothing.

Verified the way the builder does it: wipe `node_modules`, run `npm ci` from
clean, confirm **zero** `EBADENGINE` warnings - the precise signal that caused
the skip.

## Alternatives considered

**Force a newer Node through nixpacks.** The attribute does not exist in the
pinned snapshot.

**Switch to the Railpack builder.** Plausible, and it changes an unrelated
variable while debugging a build - the wrong moment to introduce one.
