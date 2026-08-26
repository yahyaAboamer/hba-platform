# 0026. Payment proof is stored in Postgres, in its own table

**Status:** Accepted
**Date:** 2026-08-26

## Context

§14 requires a screenshot of every payment, shown to the affiliate it belongs to
(ADR 0017). The Phase 7 plan left where the bytes live as an open decision
needing measurement rather than assertion.

Three options, and the numbers matter more than the instinct.

**The volume.** ~20 models × 12 months × ~200 KB ≈ **50 MB/year**, before the
compression §14 also requires. Call it 30–50 MB/year. Free-tier Postgres offers
around 0.5 GB, and the platform's other growth is roughly 11 MB/year of orders
(§10.2). That is a decade of headroom.

**The instinct** — *"never put binaries in a database"* — is a real rule, and it
is about tables holding gigabytes, dragged into every query and every dump. At
50 MB/year on a shop with twenty affiliates, it is a rule being applied to the
wrong size of problem.

## Decision

**Postgres, in a dedicated `proof_file` table**, referenced by id from
`payment_transaction`.

**Its own table, and that is the important half.** A blob column on
`payment_transaction` would be loaded by every query that touched a payment —
the payments list, the settlement calculation, the audit render — because
selecting a row selects its columns. A separate table means the bytes move only
when somebody actually asks for the image.

**Rejected: a Railway volume.** The old dashboard's volume sat at 431 MB of 500
(§10.2), which is the failure mode: a disk nobody watches until it is full.
Volumes also fall outside the database backup, so proof and payments would be
restored from two places and could disagree.

**Rejected: object storage.** Cheaper per byte and genuinely better at scale, and
it costs a second service, a second credential, a second thing to be down at
month end, and a second place for an access-control mistake to live. The bytes
this saves are worth less than the failure modes it adds (ADR 0019).

## Consequences

Proof is backed up with the payments it belongs to, restored with them, and
access-controlled by the same session that guards everything else. There is no
signed URL to leak and no bucket policy to get wrong — the check is per request,
in the same place as every other permission check.

**Deletion is real deletion.** Removing a `proof_file` row removes the bytes.
With object storage, a delete that half-succeeds leaves an orphan nobody can
find.

**What would change this decision.** Any of:

- Proof storage passing **200 MB**, which at current volume is roughly five
  years, or immediately if the business starts storing something larger than
  payment screenshots.
- The database moving to a tier where storage is the binding constraint.
- Proof needing to be served to more than a handful of people at once — a CDN in
  front of object storage is the right answer to that, and Postgres is not.

`GET /api/operations/sync` reports the total, so the first of those is a number
somebody can watch rather than a surprise.

## Alternatives considered

**A blob column on `payment_transaction`.** Simplest to write and wrong to read:
every payment query would carry the image bytes, and the cost would appear as
inexplicable slowness on screens that never show a picture.

**Storing a hash and keeping the file elsewhere.** Solves nothing here — the file
still has to live somewhere, and now there are two things to keep in step.
