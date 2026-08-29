# 0033. A house account gets a user_account it can never sign into

**Status:** Accepted
**Date:** 2026-08-30

## Context

`AccountKind.HOUSE` has existed since Phase 3 for exactly one purpose: HBA10,
HBA's own discount code, used by real customers, whose sales needed counting
without ever being paid a commission or appearing in a ranking. Nothing could
create one - `POST /api/affiliates` requires an existing `user_account_id`,
and the only two things in the platform that ever produce a `user_account`
are bootstrapping the first admin and somebody accepting an invitation. A
house code is not a person to invite. This was gap 4 of the seven capability
gaps found while auditing what the platform could technically do against
what a screen could reach.

The `AccountKind.HOUSE` docstring, written before this was decided, said a
house account "needs a working dashboard and Shopify verification like any
other" - which reads as an assumption that somebody would sign in as it.
Asked directly, the answer was no: the actual want is a discount code whose
sales are visible and comparable to the models', with nobody ever using it as
a login.

Production has real data behind this. 292 of 816 recorded orders - 36% of
everything the shop has sold - already carry `HBA10`. It is not a
hypothetical account; it is the single largest code in the shop, sitting
unattributed.

## Decision

`create_house_account` gives a house account a real `user_account` row -
identity still lives in exactly one place (ADR 0006), not in a special-cased
nullable column for the one kind of affiliate that is not a person - but one
that starts `status="suspended"` and never leaves it. `suspended` is the same
status a real person's account is put into to lock them out after the fact;
here it is the account's entire life. Its password is generated with
`secrets.token_urlsafe(48)`, hashed, and told to nobody - not logged, not
returned, not knowable even by whoever wrote the function that generated it.
Sign-in checks `status == "active"` everywhere it is checked; this account
can never satisfy that.

`POST /api/affiliates/house` does in one call what a model's onboarding does
in three separate ones - create the account, register the code, verify it,
approve if verified - because a house account has nobody to come back and
perform the middle steps, and nothing to wait on: it has no compensation and
no targets, so a verified code is the only thing standing between it and
`active` (`set_status` already enforces exactly this and nothing more).

The docstring on `AccountKind.HOUSE` is corrected to say what is actually
true now, rather than what was assumed before anyone had decided.

## Consequences

**A second, narrower kind of account-creation gap remains.** `POST
/api/affiliates` still cannot create a *model* without an invitation - a real
person who genuinely has no email. That was never solved by this and was
never the ask; `tests/test_reachability.py` now says so explicitly rather
than reading as one unsolved problem covering both cases.

**Nothing downstream needed to change.** Attribution, commission
calculation, payroll, and the Targets and Affiliates screens already
branched on `account_kind == "house"` correctly - each one either excludes it
outright (`is_payable`, Targets' own filter) or names it as the reason
nothing is owed (`payroll.py`'s `HOUSE_ACCOUNT` blocker) rather than
computing a wrong figure. This was purely a creation gap; every consumer of a
house account had already been built to expect one.

**A synthetic email exists in the identity table.** `house.<slug>@hba-
platform.internal` is not a real address and will bounce if anything ever
mails it. Nothing does today - invitations, applications, and every
notification in `app/services/notifications.py` are reached only through
paths a house account never takes (it has no application, and payout/
compensation notifications never fire because it has neither) - but a future
feature that emails "every affiliate" without checking `account_kind` would
silently fail against this address, which is the intended outcome and not a
bug: nobody should be emailing HBA10.

## Alternatives considered

**A nullable `user_account_id`.** Rejected on the same grounds ADR 0006
already settled: a second shape for "the affiliate that is not a person"
would have propagated a null-check into every join and every screen that
currently assumes an affiliate always resolves to somebody with an email and
a login, for the sake of one row.

**Letting HBA staff actually sign in as HBA10**, matching what the original
docstring assumed. Rejected once asked directly: the want was comparison and
reporting from the *admin* side - "what our code sells versus what the
models sell" - not a parallel model-style dashboard for a discount code. If a
dedicated code-vs-model comparison view is wanted later, it is a reporting
feature building on data this ADR makes attributable, not a reason to give
HBA10 a session of its own.
