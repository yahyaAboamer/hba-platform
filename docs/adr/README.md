# Architecture Decision Records

This platform will outlive everyone's memory of why it was built this way. An
ADR records a decision *and its reasoning*, so that someone in 2029 changing
this code can tell the difference between a deliberate constraint and an
accident.

**The rule: every decision that would be expensive or dangerous to reverse gets
an ADR, written when the decision is made, not afterwards.**

## What belongs here

A decision belongs in an ADR when reversing it later would be costly, when it
looks wrong without its context, or when it encodes a business rule rather than
a technical preference. If a future maintainer might reasonably look at the code
and think "why on earth did they do that?", write one.

Routine choices - a variable name, a helper's shape - do not.

## What does not belong here

- **How the system works.** That is the specification and the code.
- **What was built.** That is the git history.
- **A record of every change.** ADRs record *decisions*, not activity.

## Format

Each record is `NNNN-short-title.md` and answers four questions:

- **Status** — Accepted, Superseded by NNNN, or Deprecated
- **Context** — what was true that forced a choice
- **Decision** — what was chosen, stated plainly
- **Consequences** — what this costs, including what it makes harder

A superseded ADR is **never deleted**. It is marked superseded and left in
place: knowing what was tried and rejected is often more useful than knowing
what was chosen.

## Index

| # | Decision | Status |
|---|---|---|
| [0001](0001-rebuild-rather-than-iterate.md) | Rebuild rather than iterate on the old dashboard | Accepted |
| [0002](0002-money-as-integer-piastres.md) | Money is integer piastres, never floats | Accepted |
| [0003](0003-multiply-first-divide-once.md) | Commission multiplies first and divides once | Accepted |
| [0004](0004-half-up-rounding.md) | Rounding is half-up, not banker's | Accepted |
| [0005](0005-business-month-in-cairo.md) | The business month is derived in Africa/Cairo | Accepted |
| [0006](0006-identity-rooted-in-user-account.md) | Identity is rooted in user_account, not affiliate | Accepted |
| [0007](0007-permissions-in-code.md) | Permissions are defined in code, assigned in data | Accepted |
| [0008](0008-append-only-enforced-by-database.md) | Append-only is enforced by database triggers | Accepted |
| [0009](0009-postgres-as-the-job-queue.md) | Postgres is the job queue; no Redis | Accepted |
| [0010](0010-two-tier-order-storage.md) | Every order is indexed; only attributed ones in full | Accepted |
| [0011](0011-commission-base-and-freezing.md) | Commission base is cash kept, frozen at return or exchange | Accepted |
| [0012](0012-earned-on-delivery.md) | Commission is earned on delivery; HBA absorbs late returns | Accepted |
| [0013](0013-on-demand-payroll.md) | Payroll is an action, not a schedule | Accepted |
| [0014](0014-historical-months-show-sales-only.md) | Pre-go-live months show sales, never commission | Accepted |
| [0015](0015-shopify-client-credentials.md) | Shopify authenticates by client credentials | Accepted |
| [0016](0016-frontend-toolchain-pinned.md) | The frontend toolchain is pinned to the builder's Node | Accepted |
| [0017](0017-payment-proof-visible-to-affiliates.md) | Payment screenshots are shown to affiliates | Accepted, risk accepted |
| [0018](0018-content-manager-scope.md) | content_manager holds wide, overlapping authority | Accepted, risk accepted |
| [0019](0019-size-to-the-requirement.md) | Size to the requirement, and record the measurement | Accepted |
| [0020](0020-receipts-store-a-digest.md) | Event receipts store a digest, not the payload | Accepted |
| [0021](0021-lease-committed-before-work.md) | The worker commits the lease before running the handler | Accepted |

See also [`../limits.md`](../limits.md) — the register of known limits and
foreseeable failures, which records what will eventually break rather than what
was decided.
