# 0046 — A model abroad applies without a payout destination

**Status:** accepted
**Date:** 2026-09-26
**Related:** `app/services/applications.py` (`submit_application`, `abroad`);
`app/services/payouts.py` (`set_destination` clears the flag);
`migrations/versions/d7a2c4e10003_paid_outside_egypt.py`;
`tests/test_applications.py`, `tests/test_applications_api.py`

## The situation

Every destination the platform can hold is Egyptian: InstaPay, an Egyptian
bank card, an Egyptian mobile wallet. The application asked *where is your
bank or wallet?* first, and a model answering *Outside Egypt* was shown a
paragraph asking her to email HBA - with the Send button switched off. She
could not apply at all. The owner walked it on a phone on 26 September and
chose, of the two options put to him:

> Option A - she can send her application without payment details; it is
> marked "payment to arrange" and HBA sets it up later.

over keeping her blocked behind an email link.

## Decision

- `POST /api/applications` takes `abroad: true`. With it, `payout_method` may
  be absent, **no destination row is written**, and anything typed into the
  payout fields is dropped rather than stored.
- `affiliate_profile.payout_abroad` (boolean, false by default) records *why*
  nothing is on file, so an empty destination is never ambiguous between "she
  is abroad" and "nobody filled it in". It is served on `/api/me` and on the
  maintainer's affiliate detail.
- **Saving any destination clears it**, in `set_destination`, whoever saves
  it. The first destination after an abroad application also sends the
  maintainer's destination-changed notice, which the first destination
  otherwise does not: it replaces an arrangement HBA was making by hand.

## What it costs

- **A model can be approved with nowhere on file to pay her.** Recording a
  payment already tolerates that (its destination snapshot is simply empty),
  so nothing refuses; the person sending the money has to arrange it outside
  the platform, which is what the owner chose.
- **A third migration** joins the two already awaiting a migration/rollback
  rehearsal before release (`b1f0a40c0001`, `c3d51e7a0002`). It is additive -
  one column with a default - and its downgrade drops it.

## Not decided here

How HBA pays somebody abroad. The platform records that it is arranged by
hand; it does not model a foreign destination, a currency, or a fee.
