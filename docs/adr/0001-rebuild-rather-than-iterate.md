# 0001. Rebuild rather than iterate on the old dashboard

**Status:** Accepted
**Date:** 2026-08-22

## Context

HBA ran its affiliate programme on `hba-operations-dashboard`: a FastAPI
application with SQLite, 5,200-line HTML files containing their own CSS and
JavaScript, and no build system. It worked, and it was not badly written.

It was, however, unplanned. It grew feature by feature across three unrelated
business needs owned by three different people - Boda's affiliate tracking,
Hussam's production HTML, Amr's operational monitoring - each bringing its own
tables, screens and conventions. Nothing was designed against a shared model.

That produced the symptoms the business described: inconsistent interfaces, no
editing pattern, screens showing everything known rather than what a decision
required, and two financial defects found during review (see 0011, 0012).

## Decision

Build a new platform rather than refactor the existing one. Keep the business
rules, which were hard-won and largely correct, and discard the delivery
mechanism.

Design the shared foundation - identity, permissions, audit, notifications,
navigation - once and generically, but build only the affiliate module. No
speculative tables for modules that do not exist.

## Consequences

The old dashboard is frozen at cutover and kept read-only. Nothing is deployed
from it again.

Order history is rebuilt from Shopify, which is authoritative. Business
configuration - affiliates, codes, compensation terms - is entered and verified
by hand, because Shopify does not hold it.

The cost is real: a working system is replaced rather than improved, and every
rule has to be re-implemented and re-tested. The justification is that the
inconsistency is structural, so a visual refresh would not have fixed it.

## Alternatives considered

**Refactor in place.** Rejected: the problem is the absence of a shared spine,
and adding one to a live system module by module means a long period where both
patterns exist, which is worse than either.

**Adopt `hba-operations-hub`,** the half-built Next.js application. Rejected:
its foundation is sound but partial, and adopting it would have meant a third
codebase alive at once. Its patterns were studied and re-implemented instead.
