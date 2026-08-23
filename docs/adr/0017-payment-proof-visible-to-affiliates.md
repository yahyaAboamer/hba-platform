# 0017. Payment screenshots are shown to affiliates

**Status:** Accepted — risk knowingly accepted by the business
**Date:** 2026-08-22

## Context

Recording a payout requires proof: the maintainer pays through InstaPay, then
uploads a screenshot of the confirmation. Only then does a month become `paid`.
That part is settled - the Pay button itself changes nothing, because the
platform must never record a payment that may not have happened.

The open question was whether the affiliate sees that screenshot.

An external review raised a real objection. A transfer confirmation can expose
HBA's sender name, account details, transaction identifiers, and in some
banking apps the remaining balance - to roughly twenty external people.

## Decision

**The screenshot is shown to the affiliate**, as the business requested.

Mitigations applied regardless: EXIF metadata is stripped on upload, images are
compressed, file size is capped, and proof is served only to the affiliate the
payment belongs to.

## Consequences

Affiliates can see for themselves that a payment was sent, which removes an
entire category of "did you send it?" messages and is the reason the business
wanted it.

Whatever appears in that image is visible to the recipient. HBA is responsible
for what it screenshots.

The alternative was offered and declined: a generated receipt showing amount,
date, method and a reference suffix, with the raw image kept as internal
evidence. **That option remains available and is the recommended change if the
exposure ever becomes a concern** - it needs no schema change, only a different
view.

## Alternatives considered

**Generated receipt, screenshot admin-only.** The reviewer's recommendation and
mine. Same trust benefit, no exposure of HBA's banking details. Declined in
favour of showing the real thing.

**Automatic redaction.** Rejected as worse than either option: redaction that
misses something is more dangerous than none, because it creates false
confidence.
