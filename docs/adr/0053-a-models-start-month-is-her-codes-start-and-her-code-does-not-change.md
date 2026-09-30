# 0053. A model's start month is her code's start on Shopify, and her code does not change

**Status:** Accepted
**Date:** 2026-09-30
**Amends:** 0052, in one clause (reactivating an archived model)

## Context

A model's *start month* decides from which month she appears on the payments
desk, which months need pay terms, and which months her profile and portal
show. It was typed by hand on her profile, and when nobody typed it the
platform guessed it from her **first order**.

The owner, 30 September 2026: a model can start in June and get her first
order in July. Guessing from the first order then says she was not working
with HBA in June when she was - and a June with a guaranteed minimum and met
targets is a month she may be owed. The owner asked for the start to come from
**her code on Shopify** instead, and said no model has ever changed her code:
she registers it when she applies, and it stays hers.

The platform already asks Shopify about a model's code when it is verified,
and already reads when the code was created (for the month its ownership
starts). Shopify also records when a discount code is set to start
(`startsAt`, "Active dates" in Shopify admin).

The admin profile carried a **Register or change a code** form, backed by two
routes: register another code (`POST /api/affiliates/{id}/codes`) and move her
onto a new one (`POST /api/affiliates/{id}/replace-code`). By the owner's
account neither ever happens.

There were no models on staging or production on 30 September 2026, so there is
nothing to backfill.

## Decision

1. **Her start month is the month her code starts on Shopify**, in Cairo time:
   the code's start date where Shopify has one, otherwise its creation date,
   and never earlier than January 2026 (the platform's data horizon). It is
   written when Shopify confirms her code - on re-checking it, or on adding a
   brand code - and only when nobody has recorded one already.
2. **Staff can still change it on her profile**, for the exception. A recorded
   start is never overwritten by a later check.
3. **Her code is the one she applied with, and it does not change.** The admin
   form to register another code or move her onto a new one is removed, with
   both routes and the service that retired one code for another. Correcting a
   **typo** in a code Shopify has not yet confirmed stays (`recheck-code`): an
   unconfirmed code has attributed nothing, so correcting it changes no history.
4. **Reactivating an archived model restarts her own code** from the current
   month, instead of saying a new code must be registered (0052). If her code
   ended this month it is simply reopened; if it ended earlier a new period of
   the same code starts now. If somebody else holds the code by then, the
   reactivation is refused and says so.

## Consequences

- A model who started before her first order now has those months: she appears
  on the payments desk for them and they need pay terms. That is the point, and
  it is also more work for whoever sets her up.
- The start depends on Shopify holding the right date. A code made in Shopify
  months after she began would start her late; the profile's own field is the
  fix, and a recorded start always wins.
- **A model who genuinely changes her code has no screen to do it.** The owner
  chose that knowingly ("if in the future it happens, we will then decide").
  The service that registers a code is kept - applications and brand codes use
  it - so bringing a replacement back is a route and a form, not a redesign.
- Unowned discount codes (Settings → Shopify and sync) can no longer be
  "registered on the model's page". The advice there now says to add HBA's own
  as a brand code, and that a model's code is the one she applied with.

## Alternatives considered

- **First order, as before.** Rejected by the owner for the June/July case
  above.
- **Code creation date only.** A code can be created ahead of its start; the
  start date is what the owner means by "the start of the code". Creation is
  kept as the fallback because a code with no start date is live from the
  moment it exists.
- **Keep the change-code form, hidden.** Rejected: an unused path that can
  still end a model's earnings is a risk with no benefit, and the owner asked
  for it removed from the backend as well.
