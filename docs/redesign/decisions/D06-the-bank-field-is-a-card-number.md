# Decision — D06

**Owner's question:** Is the bank field the existing supported card number, a
bank account number, or should both be supported as distinct fields?

**Owner's actual answer:** **Card number.**

Asked as a question about the act rather than the schema — *when you send a bank
transfer to a model, what do you type into the banking app?* — and answered
directly: a card number.

**Date / source:** 9 September 2026, Yahya, in the implementation session.

**Status:** confirmed.

---

## What this settles

The repository was right and the prototype's label was wrong.

`payout_destination.bank_account_number` holds, and continues to hold, **the
16-digit number on the front of a bank card**. `frontend/src/lib/payouts.ts`
validates exactly that, and its reasoning stands unchanged:

> The card number rather than the account number, deliberately: Egyptian account
> numbers vary in length by bank, so no single rule could check one.

The final design's *account number* wording is **superseded**. It is a label on
a mockup, not a change to what a person types when money moves, and the two
cannot be swapped without either rejecting every real account number or losing
the only check the field has.

## Affected rules, APIs, migration and checks

- **Rule A08** — authorised payers see complete bank details. Unchanged; what
  they see is a card number and the screen now says so.
- **No migration.** The column keeps its name and its meaning. Renaming it to
  `bank_card_number` would be a migration, a service sweep and a rewrite of
  every stored value's provenance, in exchange for a tidier identifier — and
  the comment above the column already carries the answer.
- **`REQUIRED_PAYOUT_FIELDS`** unchanged. **`cardProblem`** unchanged.
- **Labels** are the only thing that moves: every screen that shows or asks for
  this value says *card number*, so a model does not type an account number into
  a field that will refuse it and a payer does not read one as the other.
- **Checks:** `AC36`, `AC37`. The existing payout-destination tests already
  cover the validation; this adds no behaviour to test, only wording.

## What remains unchanged

Everything about how money reaches anybody. InstaPay keeps the exact submitted
`instapay_address_url`; the wallet keeps its provider list, **including WE
Pay**, which `DESIGN_REVIEW.md` V15 correctly flagged the prototype for
dropping. Destination versions stay immutable and a model still reauthenticates
with her current password to change one.

## Prior proposal this replaces

`DECISIONS.md` suggested "preserve existing field semantics; add distinct fields
only if the owner wants them". That was the right holding position and is now a
confirmed answer rather than a default: **no second field is wanted.**

## Required implementation phase/batch

**02B.** Labels only.
