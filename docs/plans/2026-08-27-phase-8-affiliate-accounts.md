# Phase 8 — Affiliate accounts, onboarding, and payout destinations

**Spec:** `docs/specs/2026-08-22-hba-platform-v1-design.md` §13 (all), §6.1, §6.4, §6.5,
§10.4, §16
**ADRs:** 0006 (identity rooted in `user_account`), 0018 (permissions are separable),
0028 (paying by bank or wallet needs a number)
**Depends on:** Phase 3 (the registry, code periods, payout destinations) and Phase 7
(the payment screen this phase puts a warning on)
**Delivers:** the first time a person who is not staff can sign in, and the first time
anybody other than the maintainer can change where money is sent.

---

## What this phase is for

Everything built so far assumes one kind of user: somebody who runs HBA. Every route is
gated on a permission, every screen is an admin screen, and the only way an affiliate
record comes into existence is an administrator typing it in against an account somebody
else already made.

This phase opens the second door. A model gets an account, applies for herself, and
manages the one thing about her record that is genuinely hers — where her money goes.

It stops short of showing her what she has earned. That is Phase 9, and the split is
deliberate: **accounts and money-in are different risks from money-out.** Getting a model
signed in wrongly is an access bug; showing her the wrong figure is a trust bug, and it
deserves its own phase with its own attention.

### The rule the whole phase rests on

§6.1 and ADR 0006. **A model reaches her data by owning the record, never by holding a
permission.**

`app/core/permissions.py` already says this out loud — the `affiliate` role's permission
set is `frozenset()`, empty, with a comment explaining that this is intentional rather
than an oversight. Every route in the platform is currently gated by
`require_permission(...)`, and a model holds none, so a model can currently reach nothing.

That is correct and it is also the thing standing in the way. This phase adds the second
gate: **ownership**, resolved from the signed-in account to the `affiliate_profile` that
hangs off it.

Two gates, never mixed:

| Question | Gate | Used by |
|---|---|---|
| May this person do this? | `require_permission` | Every staff route |
| Is this person the subject of this record? | `current_affiliate` | Every model route |

Mixing them is the failure to avoid. A staff route that also accepts ownership would let a
model reach an admin screen for her own row; a model route that also accepts a permission
would let an administrator quietly act *as* a model, which §6.5's audit trail could not
then distinguish from the model acting herself.

---

## Two defects this phase closes

Both were introduced earlier and are recorded here rather than discovered later.

**A model signing in today gets a broken admin screen.** `App.tsx` renders the admin
`Layout` for any session at all, and `/` is the maintainer's Overview, which calls
`/api/payroll/{month}` — a route requiring `affiliates.view`. A model has no such
permission, so she would land on the admin sidebar and a 403. Nothing about this is
harmful, and all of it is embarrassing on first contact.

**§6.4.5's warning reaches no screen.** `changed_recently` was written in Phase 3 and its
own docstring says *"The screen is Phase 8; this is the fact it will ask for."* The
payment screen was built in Phase 7 without it. Until this phase nobody but the maintainer
could change a destination, so the warning had nothing to warn about — from this phase on
it does, and that is exactly when the omission stops being harmless.

---

## What this phase deliberately does not do

Stated so none of it reads as forgotten.

**No emails.** §13 steps 3 and 5 want confirmation and approval emails, and §16 routes
them through a `notification_outbox` that does not exist yet. Phase 10. Until then the
invitation link is handed to the maintainer to send, exactly as staff invitations already
work in Settings.

**No earnings, orders, or payment history for the model.** Phase 9. This phase gives her
an account and one screen: her own details.

**No illustrated InstaPay guide.** §13.1 wants screenshots showing a model where to find
her Payment Address. *Blocked on the business* — the assets do not exist. The field is
built with written guidance and a place for the images to land.

**The InstaPay deep-link is still unverified.** §13.1 calls this an implementation
discovery item to be settled *before* the Pay flow is built around it. The Pay flow shipped
in Phase 7, so this is already overdue rather than upcoming. ADR 0028 reduced the exposure
by showing the number beside the link, so a failed deep-link is now an inconvenience rather
than a dead end. **Raising it again here rather than letting it disappear.**

---

## Task list

| # | Task | Delivers |
|---|---|---|
| 1 | `current_affiliate` | The ownership gate, and the tests that prove it does not leak |
| 2 | Affiliate invitations | An invite that creates a model, not a staff account |
| 3 | The application | What a model fills in for herself, and what it may not set |
| 4 | The affiliate shell | Where a signed-in model lands, instead of a broken admin screen |
| 5 | Payout destination, self-service | §6.4's high-risk change, done by its owner |
| 6 | The recent-change warning | §6.4.5, wired to the payment screen at last |
| 7 | Review and approval | The maintainer's side: verify the code, complete the record |

**Batches**, as agreed:

- **Batch A — tasks 1, 2, 3.** The spine: a model can be invited, apply, and exist.
- **Batch B — tasks 4, 5, 6.** Self-service: she can sign in, see herself, and move her money.
- **Batch C — task 7.** The maintainer closes the loop.

Each batch is one PR, tested and merged before the next starts.

---

## Task 1: `current_affiliate`

**Files:** `app/api/deps.py`; `tests/test_affiliate_access.py`

A dependency resolving the signed-in account to the `affiliate_profile` it owns, refusing
the request when there is not exactly one.

```
current_user  ->  affiliate_profile WHERE user_account_id = user.id
```

**Every refusal is a 403, never a 404.** Whether an affiliate record exists for some
account is not information an unauthorised caller should be able to probe by watching
status codes.

Four refusals, each with its own test:

| Case | Why it must refuse |
|---|---|
| Staff account, no profile | An administrator is not an affiliate and must not become one by calling a model route |
| `archived` profile | History resolves; the person does not sign in |
| Suspended `user_account` | Already refused at `resolve_session`; asserted again so the two cannot drift |
| Account owning no profile at all | Fails closed |

**`inactive` is allowed through, deliberately.** §8's own words: *not earning, may return*.
A paused model must still be able to sign in and see what she is owed from before she was
paused — locking her out would make "paused" indistinguishable from "archived" to the only
person it affects.

**A second dependency, `affiliate_or_owner`, is not built.** It is the obvious convenience
and it is the mixing this phase exists to avoid. Where a maintainer needs a model's data
there is already an admin route for it.

---

## Task 2: Affiliate invitations

**Files:** `app/services/invitations.py`; `app/api/auth.py`; migration; tests

`Invitation` already carries `email`, `role`, a hashed single-use token, and an expiry.
Accepting creates a `user_account` plus a `role_assignment`. For a model that is not
enough: she also needs an `affiliate_profile`, and it must not exist until she has
actually applied.

**The invitation says who and what, never how much.** It carries `email` and
`role='affiliate'` and nothing else. No name, no proposed code, no compensation. Anything
the invitation carried would be a figure the maintainer typed before the model was asked,
and §13's step 2 is explicit that the model supplies her own details.

**Accepting an affiliate invitation creates the account and stops.** It does not create the
profile. The profile is created by the application (task 3), because until she has told us
her name and code there is nothing to create a profile *from*, and a half-empty `pending`
row is a row that looks like an application nobody made.

**Reuses the existing token machinery unchanged.** Same hash, same single use, same expiry,
same "validate the password before consuming the invitation so a rejected weak password
does not burn the link". Adding a second invitation mechanism for models would be two
things to keep in step, and the security-relevant half is exactly the half that must not
diverge.

**Refuses an email that already owns an affiliate profile**, with a readable message. The
database's unique index on `lower(email)` already refuses a duplicate account; this refuses
the sharper and more likely mistake of inviting somebody who is already on the programme.

---

## Task 3: The application

**Files:** `app/services/applications.py`; `app/api/applications.py`;
`frontend/src/screens/Apply.tsx`; tests

§13 step 2. Name, phone, proposed discount code, payout method and details. The password is
set by the invitation acceptance in task 2, so this form asks only for the record.

Creates, in one transaction:

- `affiliate_profile`, status `pending`, `account_kind='model'`
- a `discount_code_period` for the proposed code, **unverified**
- a `payout_destination`

**The code is registered unverified, and that is the point.** §10.4 makes Shopify
verification a required gate before approval, and `set_status` already enforces it —
approving an affiliate with no verified code raises. Registering the code here means the
maintainer's review has something concrete to verify rather than a free-text field to
retype, and the existing gate does the refusing.

**Nothing on this form decides what she is paid.** §6.5. No compensation type, no rate, no
targets. The application collects identity and destination; the money terms are the
maintainer's, at review. This is checked server-side rather than merely omitted from the
form — a form that only *looks* restricted is not a control.

**A model may apply once.** Submitting twice is refused rather than creating a second
profile. The obvious failure otherwise is a double-tapped button producing two pending
applications and two code registrations for the same person, one of which quietly wins.

**The payout fields follow ADR 0028's shape:** InstaPay collects the Payment Address URL
*and* the phone number, bank collects name, holder and account number, wallet collects the
number. The written guidance goes in now; §13.1's screenshots land when the business
provides them.

---

## Task 4: The affiliate shell

**Files:** `frontend/src/App.tsx`; `frontend/src/components/AffiliateLayout.tsx`;
`frontend/src/screens/MyAccount.tsx`

Where a model lands. Today: the admin sidebar and a 403.

**Routing splits on what the session is, not on what it may do.** `/api/auth/me` already
returns the actor's role; the shell chooses on `role === 'affiliate'`. A model never sees
the maintainer's navigation, and a maintainer never sees the model's — not because the
other one would refuse her, but because a menu full of things that refuse you is a menu
that teaches you the tool is broken.

**One screen this phase: her own details.** Name, phone, her discount code and whether it
is confirmed, and where her money goes. Earnings, orders and payments arrive in Phase 9,
and the screen says so plainly rather than showing empty panels.

**§12.5: the affiliate portal is phone-first.** The admin screens are laptop-first because
they are used to reconcile twenty rows at month end. This one is used standing up, on a
phone, and is built that way from the start rather than retrofitted.

**A pending application shows its own state.** A model who has applied and not yet been
approved signs in to *"We have your application"*, not to an empty dashboard. She is the
one person for whom "nothing here yet" and "we are still looking at it" are completely
different messages.

---

## Task 5: Payout destination, self-service

**Files:** `app/api/affiliate_self.py`; `frontend/src/screens/MyPayout.tsx`; tests

§6.4, and the highest-risk thing in this phase. A compromised account that can silently
repoint an InstaPay address can redirect an entire payout.

Five requirements, all of them §6.4's:

1. **Re-enter the password.** Not the session — the password. A session is what an attacker
   has; the password is what they may not.
2. **Old and new shown masked for confirmation**, using `mask_destination`, which already
   exists and is already the only sanctioned representation outside the owner's own screen.
3. **The maintainer is notified immediately.** No outbox until Phase 10, so this phase
   writes the fact and surfaces it in-platform; the email is Phase 10's to send. Recorded
   as a deliberate partial rather than done quietly.
4. **Audited with sensitive fields masked.** `record_audit` already masks on the way in,
   and `set_destination` already writes both sides masked.
5. **A new row, superseding the old.** Already how `set_destination` works: nothing is
   updated in place, so a payment made in March still resolves the destination in force
   then.

**Most of this exists.** `set_destination`, `mask_destination` and the audit masking were
all built in Phase 3 against this moment. What is new is the password re-entry, the
confirmation step, and a model being allowed to call any of it.

**The password check is its own service function, not inline.** `authenticate` already
exists and already returns `None` rather than raising, and reusing it means a model
re-entering her password is checked by exactly the code that checks it at sign-in.

---

## Task 6: The recent-change warning

**Files:** `app/api/payments.py`; `frontend/src/screens/PaymentRecord.tsx`; tests

§6.4.5. `changed_recently` has existed since Phase 3 and is wired to nothing.

The payment screen shows a prominent warning when the destination it is about to reveal
changed within seven days — the moment a redirected payout would actually cost money.

**Seven days is the existing default and is not being re-derived here.** If it proves wrong
it is one number in one place.

**The warning does not block.** A destination changing shortly before payday is
overwhelmingly a model who switched banks, and refusing to pay her would be the wrong
default by a wide margin. It is a warning because the person paying is the one who can tell
the difference, and they cannot tell it if nobody mentions it.

Small task, listed separately because it closes a stated gap rather than adding a feature,
and those are the ones that get folded into something bigger and lost.

---

## Task 7: Review and approval

**Files:** `frontend/src/screens/Applications.tsx`; `app/api/affiliates.py`; tests

§13 step 4. The maintainer's side of the loop.

A pending application is currently visible on the Affiliates list as a row marked *waiting
to be approved*, which is enough to know it exists and not enough to act on. This is the
screen that acts on it: what she submitted, the code verified against Shopify, compensation
set, targets set, approved.

**Approval already refuses an unverified code.** `set_status` raises, per §10.4. This screen
does not re-implement that check; it makes it visible before it fires, so the maintainer
verifies as part of reviewing rather than meeting a refusal at the end.

**Compensation and targets reuse the existing Pattern C pages.** They are money decisions
and §12.2 puts them on their own pages with their own previews. Duplicating them into a
review wizard would be a second place for a rate to be typed.

**Rejection is not built.** There is no `rejected` status in `AffiliateStatus` and this
phase does not add one. A model who is not taken on is left `pending` or archived, both of
which already exist and both of which already resolve in history. Adding a fifth status to
express *"we said no"* is a schema change in service of a message better delivered by a
person.

---

## What "done" looks like

A model is invited from Settings, opens the link, sets a password, fills in her own name,
phone, code and payout details, and signs in to a phone-shaped screen that tells her she
has applied. The maintainer sees the application, verifies the code against Shopify, sets
her terms and her targets, and approves her. She signs in again and the screen says she is
on the programme. She changes her InstaPay address, re-entering her password to do it, and
the next time anybody opens her payment screen it says the destination changed two days
ago.

No email is sent at any point in that sequence, and every step of it is in the audit trail.
