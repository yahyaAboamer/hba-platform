# Batch report — Phase 02B, shared profile and self-editing

**Date:** 10 September 2026
**Branch:** `phase02b/profile-and-self`, continuing from 02A
**Requested scope:** Shared profile and self-editing. Directory/product/target/payment links target one model profile. Persist authorized contacts and optional measurements; model-only measurement writes. Keep payout change reauthentication and exact URL behaviour. **Resolve contact-versus-login email and bank-field ambiguity before mutating those meanings.**

**Delivered behaviour:** Both blocking decisions were answered and applied. A
model can now edit her own measurements, and nobody else can. The bank field
has one name across the whole product, and it is the right one.

---

## Review

### The decisions, answered and recorded

| | Answer | Record |
|---|---|---|
| **D06** — bank field | **Card number** | `decisions/D06-the-bank-field-is-a-card-number.md` |
| **D07** — contact email | **One email** | `decisions/D07-one-email-per-model.md` |

Both were asked as questions about the act rather than the schema — *what do
you type into the banking app*, *do you want a second address to keep current*
— and both were answered in a word.

### D06 was not hypothetical. The product was already saying two things.

The same column, the same sixteen digits, two different words on two screens:

| Screen | Said | Read by |
|---|---|---|
| Her application, her payout screen | **Card number** | the model typing it |
| The maintainer's profile | *Account number* | staff |
| **The payment recording screen** | *Account number* | **the person copying it into a banking app** |

Nobody had done anything wrong. There were two copies of the label map and only
one got corrected — which is what a second copy is for.

The copies are gone. `PAYOUT_FIELD_LABEL` in `lib/payouts.ts` is the only one,
every screen reads it, and it says *Card number*. The design's *account number*
wording is superseded, on the record, with the reason: adopting it would either
reject every real Egyptian account number or cost the field its only check.

### D07 closed a trap before it opened

The design draws an editable email box on the profile. Left as drawn, it invites
somebody to change a model's **login** while believing they are correcting a
contact detail — and the first anyone learns of it is a model who cannot sign in.

There is one address. It is now visible on both sides and named for what it is:

- Her screen: **You sign in with**
- The maintainer's profile: **Signs in with**

Not "Email". Shown, not editable — moving a login is a real change and not
something to do by tabbing past it on a settings screen.

### What the owner should try

1. **Open a model's payout details from the payment screen.** The number to
   copy is labelled *Card number*. It says the same thing everywhere now.
2. **On a phone, as a model: You → Your size.** Add a height, save. Change it.
   Empty one and save — it comes off her record. All optional, in both
   directions.
3. **Look for a way to edit her measurements as an admin.** There isn't one,
   and that is the design: A05 gives the write to her.
4. Her profile now opens with **Who she is** — when she started, her phone, the
   address she signs in with, and her measurements read-only.

### Approved-design deviations

**One, now formally recorded:** the design's *account number* label. D06
supersedes it. The record explains why, and a build guard stops it returning.

---

## Engineering evidence

**Rules and IDs covered:** A05, A08, M03, D06, D07; UI07, UI08 (partially — the
profile carries contact data now; shipping address belongs with recipient
matching in Phase 03), UI41, UI42.

### Files changed

| File | What |
|---|---|
| `docs/redesign/decisions/D06-…md`, `D07-…md` | **New.** Both records, from the template |
| `docs/redesign/DECISIONS.md` | Both rows closed; an "Answered so far" table added |
| `lib/payouts.ts` | **`PAYOUT_FIELD_LABEL`** — the one map, with D06's reasoning |
| `screens/MyPayout.tsx`, `AffiliatePayout.tsx` | Local copies deleted, both now read the shared map |
| `screens/AffiliateDetail.tsx`, `PaymentRecord.tsx` | Labels from the map; *Signs in with* added |
| `screens/MyDetails.tsx` | *You sign in with*; the new **Your size** editor |
| `api/affiliate_self.py` | **`PUT /api/me/measurements`**; `/api/me` carries email and measurements |
| `api/affiliates.py` | The payload carries her email |
| `services/affiliates.py` | **`UNSET` sentinel** so clearing is distinguishable from silence |
| `services/applications.py` | Passes only what she actually gave |
| `styles/portal.css` | The size fields |
| `lib/__tests__/payoutLabels.test.ts` | **New guard**, 84 cases |
| `tests/test_affiliate_self_api.py` | 7 new |
| `tests/test_portal_api.py` | The writable-routes guard, updated deliberately |

**No migration.** 02A's columns carry all of this; neither decision needed one.

### Three things worth naming

**`None` could not carry two meanings, so it stopped trying.** A model
correcting only her height sends nothing for her weight; a model who no longer
wants her weight on file sends it empty. Reading those as one request would
either delete a field she never touched or refuse to clear one she did. Hence
`UNSET` in the service and `_set` flags on the wire — the same shape 02A used
for the start month, for the same reason. Both directions are tested.

**The measurements route has no password, and that is deliberate.** §6.4.1 asks
for one before a payout destination changes, because that is where money goes
and a session is what an attacker already has. A height is not that: the worst
an intruder does is make HBA send the wrong size, and asking for a password
every time she corrects a number she volunteered teaches her to type it into
anything that asks.

**The writable-routes guard failed, and that is what it is for.**
`test_nothing_about_a_target_can_be_changed_from_their_side` asserts the *whole
list* of routes a model may write, so it fails when anybody adds one rather than
when they add a bad one. Adding `/api/me/measurements` broke it. Updated in the
same commit, with the reason beside each entry — which is the difference between
a decision and an afternoon.

### One shared profile — verified, not built

UI07 asks that directory, product, target and payment links all reach one
profile. Every screen that names a model already links to `/affiliates/:id`:
`Targets.tsx:318`, `Payments.tsx:255`, `Payroll.tsx:406`, `Orders.tsx:363`,
and the directory itself. **Nothing needed changing.** Products has no screen
yet; when Phase 03 builds it, this is the route it links to.

### Commands, results, environment

| Check | Result |
|---|---|
| `pytest -q --color=no` against `hba_platform_test` | **1620 passed**, exit 0 — 1613 after 02A, **7 new** |
| `cd frontend && npm test` | **190 passed**, exit 0 — 106 before, **84 new** (the guard runs per file) |
| `cd frontend && npm run build` | exit 0 |

**The new guard was checked for teeth.** Reintroducing *"Account number"* into
`AffiliatePayout.tsx` fails the suite, naming that exact file — a guard that
cannot fail is worse than none.

Green before and after, apart from the deliberate guard update described above.

### Visual comparison — not performed

Same limitation as 02A, and it has now cost two batches: sign-in through browser
automation will not submit — the typed value does not reach the field, the
browser's own `required` check blocks the form, and no request reaches the
server at all. An automation problem, not the application's.

**Four pieces of interface are built, type-checked and unseen:** the *Who she
is* panel, *Your size*, the two email rows, and the relabelled payout rows. All
small, none of them carrying a calculation. Worth ten minutes on staging before
this merges.

---

## Continuation

### Limitations

- **Shipping address is still not collected.** A05 names it; it belongs with
  recipient matching in Phase 03, where a shipping address is a Shopify fact
  rather than a profile field. Not an oversight — a placement.
- **No admin route corrects a mistyped email.** `update_details` supports it and
  nothing calls it. D07 makes that deliberate: moving a login is not a profile
  edit, and if it is ever wanted it deserves its own flow.
- **The directory is still not redesigned.** UI06 stands.
- Measurements are not shown anywhere marketing would naturally look for them —
  only on the profile. That is Phase 03's roster work.

### Decisions recorded

**D06 and D07, both closed.** Eight remain, each due at its own phase. **D01 now
has both the field and the interface it needs** — only the values are missing,
and those are the owner's.

### Next

**Phase 02C** — the third batch of `02_MODELS_AND_SETUP.md`. Read
`BASELINE_REPORT.md` §5 first: **the selected-month terms editor already
exists**, shipped in `63c64c3` before this package arrived. What 02C still owes
is the *readiness* half — per-month setup coverage across every eligible month,
including the outcome-only historical target hooks — not the editor.

### Live changes

**None.** Nothing deployed, no production branch moved, no financial data
touched. The branch is local and unpushed.
