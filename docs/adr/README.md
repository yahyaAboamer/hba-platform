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
| [0010](0010-two-tier-order-storage.md) | Every order is indexed; only attributed ones are stored in full | Accepted |
| [0011](0011-commission-base-and-freezing.md) | Commission base is cash kept, frozen when a return or exchange begins | Accepted |
| [0012](0012-earned-on-delivery.md) | Commission is earned on delivery; HBA absorbs late returns | Accepted |
| [0013](0013-on-demand-payroll.md) | Payroll is an action, not a schedule | Accepted |
| [0014](0014-historical-months-show-sales-only.md) | Pre-go-live months show sales, never commission | Superseded by 0036 |
| [0015](0015-shopify-client-credentials.md) | Shopify authenticates by client credentials | Accepted |
| [0016](0016-frontend-toolchain-pinned.md) | The frontend toolchain is pinned to the builder's Node | Accepted |
| [0017](0017-payment-proof-visible-to-affiliates.md) | Payment screenshots are shown to affiliates | Accepted — risk knowingly accepted by the business |
| [0018](0018-content-manager-scope.md) | content_manager holds wide, overlapping authority | Accepted — risk knowingly accepted by the business |
| [0019](0019-size-to-the-requirement.md) | Size to the requirement, and record the measurement | Accepted |
| [0020](0020-receipts-store-a-digest.md) | Event receipts store a digest, not the payload | Accepted |
| [0021](0021-lease-committed-before-work.md) | The worker commits the lease before running the handler | Accepted |
| [0022](0022-codes-are-recorded-not-declared.md) | Shopify owns the codes; the platform only records them | Accepted |
| [0023](0023-delivery-comes-from-shopify.md) | Delivery is read from Shopify, not from Bosta | Accepted |
| [0024](0024-an-order-can-be-finished-with.md) | An order can be finished with, and an exchange finishes it | Accepted |
| [0025](0025-delivery-is-final.md) | Delivery is final: V1 ignores what happens afterwards | Accepted |
| [0026](0026-proof-lives-in-postgres.md) | Payment proof is stored in Postgres, in its own table | Accepted |
| [0027](0027-numerals-change-face-when-a-figure-becomes-an-obligation.md) | Numerals change face when a figure becomes an obligation | Typeface rule superseded by 0039 |
| [0028](0028-paying-by-bank-or-wallet-needs-a-number-not-a-link.md) | Paying by bank or wallet needs a number, not a link | Accepted, amended 2026-08-27; **reveal step superseded by 0042** |
| [0029](0029-a-late-order-is-paid-at-its-own-months-rate.md) | A late order is paid at its own month's rate, on top of any guarantee | Accepted |
| [0030](0030-a-reopened-month-emails-once-on-reapproval.md) | A reopened month emails once, on re-approval, and says why | Accepted |
| [0031](0031-the-platform-runs-in-amsterdam-not-california.md) | The platform runs in Amsterdam, not California | Accepted |
| [0032](0032-backups-run-in-their-own-container-not-the-apps.md) | Backups run in their own container, not the app's | Accepted |
| [0033](0033-a-house-account-gets-a-user-account-it-can-never-sign-into.md) | A house account gets a user_account it can never sign into | Accepted |
| [0034](0034-a-second-service-splits-staging-from-production.md) | A second service splits staging from production | Accepted |
| [0035](0035-an-adjustment-closes-a-difference.md) | An adjustment closes a difference; it never opens a larger one | Accepted; amended by 0041 |
| [0036](0036-pre-go-live-months-are-ordinary-months.md) | Months before go-live are ordinary months, settled outside | Accepted |
| [0037](0037-what-you-were-paid-is-not-how-you-sold.md) | What a model was paid and how their sales performed are two numbers | Accepted |
| [0038](0038-the-portal-wears-the-brand-the-tool-does-not.md) | The portal wears the brand; the maintainer's tool does not | Superseded by 0039 |
| [0039](0039-one-palette-across-both-halves.md) | One palette and one typeface across both halves | Accepted; type mechanism amended by 0043 |
| [0040](0040-a-pending-order-is-a-sale.md) | A pending order is a sale, and the carry becomes a backlog | Accepted |
| [0041](0041-a-correction-settles-money-that-moved.md) | A correction settles money that moved; a balance is money that has not | Accepted; amends 0035 |
| [0042](0042-the-payer-sees-the-whole-destination.md) | The payer sees the whole destination, without asking twice | Accepted; amends 0028 |
| [0043](0043-type-as-the-exports-set-it.md) | Type as the exports set it: proportional figures, one weight | Accepted; amends 0039 |

**0014 is superseded by 0036** and **0038 by 0039**. **0027 keeps its
principle and loses its mechanism to 0039**: an agreed figure is still set
apart from a working one, but by weight and colour rather than by a second
typeface - **and 0043 then removes the weight**, as the exports draw every
figure at 400: the words beside a figure are what set it apart. **0028 is amended by 0042**: masking still governs every record, and the payer's own screen shows the whole destination, which is what the approved design always drew. **0035 is amended by 0041 in a single clause**: an adjustment still
closes a difference and never opens a larger one, but a *credit* closes only an
overpayment — carrying a difference forward recovers it in the month it is
carried to, and reducing the source month as well recovers it twice. Each
carries the reasoning at the top of the superseded or amended file rather than
only in the one that replaced it.

See also [`../limits.md`](../limits.md) — the register of known limits and
foreseeable failures, which records what will eventually break rather than what
was decided.
