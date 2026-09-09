# Decision — D07

**Owner's question:** Should marketing maintain a contact email and address
separately from sign-in identity, and who edits those contact fields?

**Owner's actual answer:** **One email.**

**Date / source:** 9 September 2026, Yahya, in the implementation session.

**Status:** confirmed.

---

## What this settles

A model has **one** email address. It is what she signs in with and where HBA
writes to her, and there is no second contact address anywhere.

No `contact_email`. No separate contact address block. Nothing to keep in step
with anything else.

The reasoning offered with the recommendation, and accepted: twenty models, one
address each, and a second address is a second thing to keep current — it goes
stale the first time somebody updates one and not the other, and a stale contact
address is worse than none because it looks answered.

## The trap this closes

The final design draws an editable email box on the profile. Left as drawn, it
is an invitation to change somebody's login while believing you are correcting a
contact detail — and the first anybody learns of it is a model who cannot sign
in.

So the field stays, and it stops being ambiguous:

- Every screen that shows it calls it **the email she signs in with**, not
  "email".
- Changing it is presented as what it is — moving her login — rather than as a
  contact edit.
- `update_details` already records the change with what it changed from, for
  exactly this reason. Its docstring says so: *"why can they not sign in any
  more" is a question that gets asked.* That behaviour is now the documented
  answer to D07 rather than a precaution.

## Affected rules, APIs, migration and checks

- **Rule A05** — marketing needs phone, contact/email and shipping information.
  Satisfied by the single address; **shipping information remains unbuilt** and
  belongs with recipient matching in Phase 03, where the shipping address is a
  Shopify fact rather than a profile field.
- **Rule M03** — map contact email versus login identity deliberately; do not
  silently rename login credentials. **This is that deliberate mapping:** they
  are the same field, said out loud.
- **No migration.** No new column.
- **`update_details`** unchanged in behaviour. Its email branch is the login
  move, and it stays audited.
- **Checks:** `AC04`, `AC08`.

## What remains unchanged

Measurements were never part of this question. They are hers to write and staff
read them (A05), settled in 02A and untouched here.

## Prior proposal this replaces

`DECISIONS.md` proposed "preserve auth identity; propose a separate contact
email and address with audited staff/model editing only after the owner
chooses precedence." The owner chose: **no separate contact email.** The second
half of that proposal is closed, not deferred.

## Required implementation phase/batch

**02B.** Wording and one honest control; no schema, no service change.
