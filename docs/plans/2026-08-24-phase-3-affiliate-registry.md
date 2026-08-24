# Phase 3 — Affiliate registry, code periods, compensation terms

**Spec:** `docs/specs/2026-08-22-hba-platform-v1-design.md` §8, §9.2, §9.5, §6.4, §13, §17
**Depends on:** Phase 1 (identity, roles, audit) and Phase 2 (order index, Shopify client)
**Delivers:** who the affiliates are, which codes they own when, and what they are owed per —
**not** what they are owed. The commission engine is Phase 4.

---

## What this phase is for

Phase 2 ended with 486 orders indexed and a list of discount codes belonging to nobody. This
phase gives those codes owners.

The hard part is not storing an affiliate. It is that **every fact here is effective-dated**.
A code belongs to Nour from March, moves to nobody in July, and comes back in September. A
rate was 8% until June and 10% after. Ask "who owned `NOUR10` in April?" and the answer must
be a fact, not a guess — because in Phase 4 that answer becomes money.

So the shape of this phase is: **periods, not values.** Nothing here stores "Nour's rate". It
stores "Nour's rate, for these months".

### The three rules that decide everything downstream

From §9.2, and each one is a test:

| Registered model codes on an order | Outcome |
|---|---|
| Exactly one | Attributed to that affiliate |
| Zero | Unattributed — indexed only |
| **More than one** | **Financial hold. A human decides.** |

The third is a cheap safety net, not the conflict subsystem the old application carried. The
order waits rather than silently paying the wrong person or paying twice.

### What must be impossible, not merely prevented

From §17. These are database constraints, not code checks:

- No overlapping `compensation_period` rows for one affiliate
- No overlapping ownership of the same code **across affiliates**
- Fixed and base amounts valid only for compensation types that use them
- `house` accounts can never enter payable payroll

The first two need `btree_gist` and `EXCLUDE` constraints. Application code will also check,
so the error is readable — but the database is what makes it true.

---

## Task list

| # | Task | Delivers |
|---|---|---|
| 1 | Affiliate profile | The registry, status lifecycle, `house` accounts |
| 2 | Effective-dated periods | `btree_gist`, month ranges, the overlap machinery |
| 3 | Discount code periods | Code ownership over time, verification gate |
| 4 | Compensation periods | Three pay types, per-type field validity |
| 5 | Payout destinations | Append-only, superseding, masked in audit |
| 6 | Attribution resolution | Codes + month → affiliate, or hold |
| 7 | Affiliate API | CRUD, permission-gated, audited |
| 8 | Unregistered codes, for real | Subtract owned codes; backfill orphans |

---

## Task 1: Affiliate profile

**Files:**
- Create: `app/models/affiliates.py`, `app/services/affiliates.py`
- Modify: `app/models/__init__.py`
- Create: one Alembic migration
- Test: `tests/test_affiliates.py`

**Interfaces:**
- Produces:
  - `AffiliateProfile` model
  - `AffiliateStatus` constants: `PENDING`, `ACTIVE`, `INACTIVE`, `ARCHIVED`
  - `AccountKind` constants: `MODEL`, `HOUSE`
  - `create_affiliate(db, *, user_account_id, name, phone, account_kind) -> AffiliateProfile`
  - `set_status(db, affiliate, status, *, actor) -> None`
  - `list_affiliates(db, *, include_archived=False) -> list[AffiliateProfile]`

- [ ] **Step 1: Write the failing test**

`tests/test_affiliates.py`. The tests that matter:

```python
def test_an_affiliate_is_created_pending(db): ...
def test_an_affiliate_is_rooted_in_a_user_account(db):
    """Identity lives in user_account (ADR 0006). An affiliate is business data
    hanging off an account, never an account in itself."""

def test_a_house_account_is_marked_as_such(db):
    """HBA's own code (HBA10) is a real code used by real customers. It needs a
    working dashboard for verification and must never appear in payable totals
    or rankings."""

def test_archiving_does_not_delete(db):
    """An archived affiliate's past payroll still has to resolve."""

def test_a_deleted_user_account_takes_its_profile_with_it(db):
    """ON DELETE CASCADE, honoured by passive_deletes - the ORM must not try to
    NULL the foreign key instead."""

def test_status_transitions_are_recorded_in_the_audit_log(db): ...
def test_an_unknown_status_is_refused_by_the_database(db): ...
def test_an_unknown_account_kind_is_refused_by_the_database(db): ...
def test_one_profile_per_user_account(db): ...
```

- [ ] **Step 2: Run it, confirm it fails**

- [ ] **Step 3: Write the model**

`app/models/affiliates.py`:

```python
"""The affiliate registry.

Business data for an affiliate, hanging off a user_account rather than
replacing it (ADR 0006). Identity, sign-in and roles stay in one place; this is
who the person is to the business.
"""

class AccountKind:
    MODEL = "model"
    #: HBA's own code - a real code used by real customers, needing a working
    #: dashboard for verification, but excluded from payable totals and
    #: rankings. Replaces the old system's confusing code_type='test'.
    HOUSE = "house"


class AffiliateStatus:
    PENDING = "pending"      # applied, not yet approved
    ACTIVE = "active"        # earning
    INACTIVE = "inactive"    # not earning, may return
    ARCHIVED = "archived"    # gone; history must still resolve
```

Table `affiliate_profile`:

| Column | Type | Notes |
|---|---|---|
| `id` | pk | |
| `user_account_id` | fk → `user_account.id`, **unique**, `ON DELETE CASCADE` | one profile per account |
| `name` | `String(120)` not null | |
| `phone` | `String(40)` | |
| `status` | `String(20)` not null, check | default `pending` |
| `account_kind` | `String(20)` not null, check | default `model` |
| `created_at` | timestamptz not null | |
| `deleted_at` | timestamptz | soft delete; archived is a status, this is removal |

`CheckConstraint` on both `status` and `account_kind` — a fixed vocabulary, not free text,
the same as `background_job.status`.

**`passive_deletes=True` on the relationship.** Phase 1 hit this exact bug: without it
SQLAlchemy issues `UPDATE ... SET user_account_id = NULL` instead of letting the database
cascade, and the delete fails on a not-null column.

- [ ] **Step 4: Write the service**

`create_affiliate` records an audit event. `set_status` records the transition — from and to,
never just the new value, because "who deactivated Nour and when" is a question that gets
asked.

- [ ] **Step 5: Migration, run the suite, commit**

---

## Task 2: Effective-dated periods

**Files:**
- Create: `app/core/periods.py`
- Create: one Alembic migration (the `btree_gist` extension)
- Test: `tests/test_periods.py`

This task exists because Tasks 3 and 4 both need the same machinery and getting it wrong in
two places is worse than getting it right in one.

**Interfaces:**
- Produces:
  - `month_range(start_month, end_month) -> str` — the `daterange` literal
  - `OPEN_ENDED` — what an unbounded `end_month` means
  - `covers(start_month, end_month, month) -> bool`
  - The `btree_gist` extension and the shared column pattern

**The design.**

Months are `YYYY-MM` strings everywhere in this codebase (ADR 0005). Postgres cannot exclude
overlapping *strings*, so each period table carries a **generated** `daterange`:

```sql
effective_range daterange GENERATED ALWAYS AS (
    daterange(
        (start_month || '-01')::date,
        CASE WHEN end_month IS NULL THEN NULL
             ELSE ((end_month || '-01')::date + interval '1 month')::date
        END,
        '[)'
    )
) STORED
```

Then overlap becomes a constraint rather than a code path:

```sql
EXCLUDE USING gist (affiliate_id WITH =, effective_range WITH &&)
```

**Why generated rather than written by the application.** A generated column cannot drift
from the months it is derived from. If the application wrote both, a bug could produce a row
whose range says one thing and whose months say another — and the constraint would then
happily permit an overlap that the reader cannot see.

**Why `[)` and not `[]`.** March to June inclusive is `[2026-03-01, 2026-07-01)`. A period
ending in June and another starting in July must not touch. With `[]` they would share an
instant and every adjacent pair would be rejected as overlapping.

**`end_month IS NULL` means open-ended** — "from March, until further notice". `daterange`
with a null upper bound is unbounded, and `&&` handles it correctly.

Tests:

```python
def test_a_closed_period_covers_its_own_months(): ...
def test_a_period_does_not_cover_the_month_after_it_ends(): ...
def test_an_open_ended_period_covers_everything_after_its_start(): ...
def test_adjacent_periods_do_not_overlap(db):
    """March-June and July-onward must both be storable. Getting the bound
    wrong makes every adjacent pair look like a conflict."""
def test_the_range_cannot_be_written_by_hand(db):
    """It is generated. An INSERT supplying it is refused, which is what stops
    it drifting from the months it claims to describe."""
def test_a_backwards_period_is_refused(db):
    """end_month before start_month produces an empty range, which overlaps
    nothing and would silently never apply."""
```

That last one matters: an empty range is not an error to Postgres. It is a period that covers
no months and conflicts with nothing — a row that looks stored and does nothing. A check
constraint refuses it: `end_month IS NULL OR end_month >= start_month`.

---

## Task 3: Discount code periods

**Files:**
- Create: `app/models/codes.py`, `app/services/codes.py`
- Create: two migrations (table, then the exclusion constraint)
- Test: `tests/test_code_periods.py`

**Interfaces:**
- Produces:
  - `DiscountCodePeriod` model
  - `register_code(db, affiliate, code, start_month, end_month=None, *, verified_at) -> DiscountCodePeriod`
  - `owner_of(db, code, month) -> AffiliateProfile | None`
  - `codes_for(db, affiliate, month) -> list[str]`
  - `registered_codes(db, month) -> dict[str, int]` — code → affiliate id

**The rules.**

Codes are normalised **upper-case on the way in**, matching `normalise_order`, which already
upper-cases what Shopify sends. A lookup that does not match because of case would silently
attribute nothing — the exact failure §10.4 exists to prevent.

`shopify_verified_at` records **when Shopify confirmed the code exists**. §10.4 makes this a
required gate before approval. Storing the timestamp rather than a boolean means "verified,
but eight months ago" is answerable.

**The exclusion constraint is on `code`, not `(affiliate_id, code)`.** Two affiliates must
never own the same code in overlapping months — that is precisely the situation that pays the
wrong person:

```sql
EXCLUDE USING gist (code WITH =, effective_range WITH &&)
```

The business said a conflict "can't happen" given how codes are issued. This makes that true
rather than hoped.

Tests:

```python
def test_a_code_is_owned_by_one_affiliate_for_a_month(db): ...
def test_the_same_code_cannot_be_owned_by_two_affiliates_at_once(db):
    """The constraint that stops the wrong person being paid."""
def test_the_same_code_can_move_to_another_affiliate_later(db):
    """Ownership is a period, not a property. March-June for Nour, July-onward
    for Sara is legitimate and must be storable."""
def test_a_code_is_stored_upper_case(db):
    """normalise_order upper-cases what Shopify sends. A lookup that misses on
    case attributes nothing, silently."""
def test_lookup_is_case_insensitive(db): ...
def test_an_unverified_code_can_be_registered_but_is_marked(db):
    """Registration and verification are separate acts. §10.4 gates approval on
    verification, not registration."""
def test_owner_of_returns_nobody_outside_the_period(db): ...
def test_one_affiliate_may_hold_several_codes_in_a_month(db):
    """The business rule: one model code per order, but a model may have more
    than one code."""
```

---

## Task 4: Compensation periods

**Files:**
- Create: `app/models/compensation.py`, `app/services/compensation.py`
- Create: two migrations
- Test: `tests/test_compensation.py`

**Interfaces:**
- Produces:
  - `CompensationType` constants: `COMMISSION`, `FIXED_PLUS_COMMISSION`, `BASE_GUARANTEE`
  - `CompensationPeriod` model
  - `set_terms(db, affiliate, *, start_month, type, ...) -> CompensationPeriod`
  - `terms_for(db, affiliate, month) -> CompensationPeriod | None`

**The three types** (§9.5):

| Type | Payout | Required fields |
|---|---|---|
| `commission` | sales commission | `commission_rate_bp` |
| `fixed_plus_commission` | commission **plus** fixed salary | `commission_rate_bp`, `fixed_amount_piastres` |
| `base_guarantee` | **max(commission, base)** — only when targets are achieved *and* verified | `commission_rate_bp`, `base_amount_piastres` |

**`base_guarantee` is a maximum, not an addition and not a cap.** The base is never added on
top of a higher commission and never limits it. That sentence is in the docstring because it
is the rule most likely to be implemented wrong from the name alone.

**Per-type field validity is a check constraint** (§17):

```sql
CHECK (
  (type = 'commission'            AND fixed_amount_piastres IS NULL AND base_amount_piastres IS NULL)
  OR (type = 'fixed_plus_commission' AND fixed_amount_piastres IS NOT NULL AND base_amount_piastres IS NULL)
  OR (type = 'base_guarantee'        AND base_amount_piastres IS NOT NULL AND fixed_amount_piastres IS NULL)
)
```

Without it, a row can carry a `base_amount_piastres` that nothing reads — and the next person
to look assumes it is being paid.

**`expected_customer_discount_bp` is stored separately from `commission_rate_bp`** and never
derived from it (§10.4). A creator may give customers 10% off while earning 5%. It exists to
be *compared* against what Shopify reports, never to stand in for a commission rate.

Money is integer piastres, rates are basis points, both validated on the way in by the
existing `app/core/money.py` (ADR 0002).

Tests:

```python
def test_terms_apply_from_their_start_month(db): ...
def test_terms_do_not_apply_before_they_start(db): ...
def test_overlapping_terms_are_refused_by_the_database(db): ...
def test_a_rate_change_is_a_new_period_not_an_edit(db):
    """Editing would rewrite history: an approved month would silently
    recalculate at the new rate."""
def test_a_commission_type_may_not_carry_a_fixed_amount(db): ...
def test_a_fixed_type_must_carry_a_fixed_amount(db): ...
def test_a_base_guarantee_may_not_carry_a_fixed_amount(db): ...
def test_the_customer_discount_is_not_the_commission_rate(db):
    """Different commercial concepts. Storing one and inferring the other is
    wrong exactly when it matters."""
def test_money_fields_refuse_floats(db): ...
def test_a_rate_over_one_hundred_percent_is_refused(db): ...
```

---

## Task 5: Payout destinations

**Files:**
- Create: `app/models/payouts.py`, `app/services/payouts.py`
- Create: two migrations (table, append-only trigger)
- Test: `tests/test_payout_destinations.py`

**Interfaces:**
- Produces:
  - `PayoutMethod` constants: `INSTAPAY`, `BANK`, `WALLET`
  - `PayoutDestination` model
  - `set_destination(db, affiliate, *, method, actor, **details) -> PayoutDestination`
  - `current_destination(db, affiliate) -> PayoutDestination | None`
  - `mask_destination(destination) -> dict` — safe to log, safe to show

**§6.4 treats this as compensation-level risk, not a profile edit.** A compromised account
that can silently repoint an InstaPay address can redirect an entire payout.

**Append-only, superseding.** A change writes a new row and stamps `superseded_at` on the old
one. Past payments must always resolve the destination that was in force when they were made,
so nothing is ever updated in place. Enforced by the same `reject_mutation()` trigger as
`audit_event` and `integration_event` — with one exception, `superseded_at`, which is what
supersession means. That is a `BEFORE UPDATE` trigger permitting only that column to change.

**Masking is not optional.** §6.4.4: raw account numbers and InstaPay addresses are never
copied verbatim into audit JSON. `mask_destination` is the only thing that may put a
destination into an audit event, a log line, or a notification.

Tests:

```python
def test_setting_a_destination_supersedes_the_previous_one(db): ...
def test_a_superseded_destination_is_still_readable(db):
    """A payment made in March must still resolve where it was sent."""
def test_a_destination_cannot_be_edited(db): ...
def test_a_destination_cannot_be_deleted(db): ...
def test_the_table_cannot_be_truncated(db): ...
def test_the_audit_record_never_contains_the_raw_address(db):
    """§6.4.4. The whole point of masking - and the test that proves the
    audit trail is not itself a leak."""
def test_masking_keeps_enough_to_recognise_but_not_enough_to_use(db): ...
def test_an_instapay_destination_requires_an_address(db): ...
def test_a_bank_destination_requires_an_account_number(db): ...
def test_changing_a_destination_records_who_and_when(db): ...
```

**Deferred to a later phase, deliberately:** the password re-entry (§6.4.1), the maintainer
notification (§6.4.3), and the payment-screen warning (§6.4.5). Those need the affiliate
portal and the notification outbox, neither of which exists. **This task builds the storage
and the masking so that when those arrive they have something correct to sit on.** Recorded in
`docs/limits.md` so the gap is visible rather than assumed done.

---

## Task 6: Attribution resolution

**Files:**
- Create: `app/services/attribution.py`
- Test: `tests/test_attribution.py`

The heart of the phase. Everything before it was storage; this is the rule that turns an order
into an owed amount in Phase 4.

**Interfaces:**
- Produces:
  - `AttributionOutcome` — `ATTRIBUTED`, `UNATTRIBUTED`, `HELD`
  - `resolve(db, codes, month) -> Attribution` with `outcome`, `affiliate_id`, `matched_codes`
  - `resolve_order(db, order_index_row) -> Attribution`

**The rule** (§9.2), stated once, tested exhaustively:

```
registered model codes on the order:
  exactly one  -> ATTRIBUTED to that affiliate
  zero         -> UNATTRIBUTED, indexed only
  two or more  -> HELD. A human decides.
```

**"Registered" means registered for that order's business month**, not today. An order placed
in April is attributed by April's ownership, permanently. Using today's ownership would make
last April's payroll change every time a code moves.

**Non-model codes are ignored entirely.** Free shipping and seasonal promos may appear in any
number alongside a model code without affecting anything. Only *registered* codes count toward
the one/zero/many test.

**A `house` code attributes normally.** It resolves to the house affiliate, so the dashboard
works and verification is possible — and Phase 4 excludes it from payable totals. Excluding it
here instead would make HBA10's orders look unattributed, which is a different and wrong
answer.

Tests — this is where the phase earns its keep:

```python
def test_one_registered_code_attributes_the_order(db): ...
def test_no_registered_codes_leaves_the_order_unattributed(db): ...
def test_two_registered_codes_put_the_order_on_hold(db):
    """Never guess. Paying the wrong affiliate is worse than paying late."""
def test_a_held_order_names_every_code_that_caused_the_hold(db):
    """A human has to decide, and cannot without knowing what conflicted."""
def test_unregistered_codes_alongside_a_model_code_are_ignored(db):
    """FREESHIP + NOUR10 is one registered code, not two."""
def test_attribution_uses_the_order_s_month_not_today(db):
    """An order placed in April is attributed by April's ownership. Using
    today's would make last April's payroll change whenever a code moves."""
def test_a_code_registered_later_does_not_attribute_earlier_orders(db): ...
def test_a_house_code_attributes_to_the_house_account(db):
    """It is a real code used by real customers. Phase 4 excludes it from
    payable totals; excluding it here would say 'unattributed', which is a
    different and wrong answer."""
def test_case_differences_do_not_prevent_attribution(db): ...
def test_an_order_with_no_codes_at_all_is_unattributed(db): ...
def test_resolution_is_pure(db):
    """It reads and returns. Writing attribution is Phase 4's job, once
    attributed_order exists with its immutability rule."""
```

**This task writes nothing.** `resolve` is a pure read. `attributed_order` and the
immutable-`affiliate_id` rule belong to Phase 4, and building the decision separately from the
recording of it means the rule can be tested exhaustively before any money depends on it.

---

## Task 7: The affiliate API

**Files:**
- Create: `app/api/affiliates.py`
- Modify: `app/main.py`
- Test: `tests/test_affiliates_api.py`

**Endpoints**, all permission-gated using the existing `require_permission`:

| Method | Path | Permission |
|---|---|---|
| `GET` | `/api/affiliates` | `affiliates.view` |
| `POST` | `/api/affiliates` | `affiliates.manage` |
| `GET` | `/api/affiliates/{id}` | `affiliates.view` |
| `PATCH` | `/api/affiliates/{id}` | `affiliates.manage` |
| `POST` | `/api/affiliates/{id}/codes` | `affiliates.manage` |
| `POST` | `/api/affiliates/{id}/compensation` | `compensation.manage` |
| `PUT` | `/api/affiliates/{id}/payout-destination` | `affiliates.manage` |

**`compensation.manage` is deliberately a different permission from `affiliates.manage`.**
Adding a code is administrative; changing a rate is money. The role bundles already separate
them (ADR 0018) and the API must not quietly re-join them.

**§6.5 — a model may never edit anything determining what they are owed.** The `affiliate`
role holds no permissions at all, so every one of these refuses it. There is a test per
endpoint, because "enforced server-side" is a claim that needs proving rather than asserting.

Tests include, for each endpoint: unauthenticated → 401, affiliate role → 403, wrong-manager
permission → 403, correct permission → 200. Plus the guard test that the permitted case
actually succeeds, so a uniformly broken endpoint cannot masquerade as working authorisation.

---

## Task 8: Unregistered codes, for real

**Files:**
- Modify: `app/api/operations.py`, `app/services/codes.py`
- Create: `app/services/backfill.py`
- Test: extend `tests/test_operations_api.py`, create `tests/test_backfill.py`

Two things Phase 2 left as promises.

**1. `/api/operations/unregistered-codes` currently returns every code seen.** Its docstring
says: *"Phase 3 subtracts the codes that belong to an affiliate, leaving only the genuinely
unregistered ones."* Now it can. A code owned for the month an order was placed is registered;
everything else is not.

The endpoint becomes what its name claims: **live codes nobody owns, whose sales are being
attributed to no one.**

**2. Backfill on first registration — moved to Phase 4.** This plan contradicted itself and
the contradiction was only visible once the code was in front of me.

§9.2 says a previously unattributed order may be attached when its code is registered for the
first time. But attaching an order means writing `attributed_order` — and this same plan's
*Deliberately not in this phase* section defers `attributed_order` to Phase 4, on the reasoning
that recording an attribution belongs with the table that stores it and the immutability rule
that protects it.

Both cannot be true. **Backfill goes to Phase 4**, with the table it writes to:

- Building a `backfill_attribution` job now would queue work no handler can do. The worker
  would fail it with `no_handler` — the exact anomaly built in Phase 2 Task 4 to catch a
  half-finished deploy.
- Building a stub handler that queues correctly and writes nothing is worse: it would look
  finished, pass a test asserting the job was queued, and silently attach no orders at all.

**What Task 8 delivers instead is the information backfill needs.**
`/api/operations/unregistered-codes` now reports which months of a code are unowned, so
registering it starts from the right month rather than leaving a gap that a later backfill
would have to find. The orders themselves wait for Phase 4.

Tests:

```python
def test_a_registered_code_is_no_longer_reported_as_unregistered(db): ...
def test_a_code_registered_for_a_later_month_is_still_unregistered_earlier(db):
    """Ownership is dated. Registering NOUR10 from September does not make
    April's NOUR10 orders owned."""
def test_the_report_names_the_months_that_are_unowned(db):
    """So whoever registers the code starts it from the right month rather
    than guessing and leaving a gap."""
def test_a_closed_code_period_leaves_later_orders_unregistered(db):
    """An affiliate left in June, her code kept being used in August. Nobody
    thinks to look for that, and it is exactly what this report is for."""
def test_case_does_not_defeat_the_subtraction(db): ...
```

**Deferred with the backfill (Phase 4):** `test_backfill_attaches_previously_unattributed_orders`,
`test_backfill_never_moves_an_already_attributed_order`, `test_backfill_is_idempotent`,
`test_registering_the_same_code_twice_queues_one_backfill`. The second is the one that matters
most — orders never move between models — and it needs `attributed_order` to have anything to
assert against.

---

## Definition of done for Phase 3

- [ ] `pytest` passes in full
- [ ] `alembic upgrade head` builds the schema from empty; every migration reverses
- [ ] Two affiliates **cannot** own the same code in overlapping months — refused by the database
- [ ] One affiliate **cannot** have overlapping compensation periods — refused by the database
- [ ] A `commission` period cannot carry a fixed amount — refused by the database
- [ ] An order with two registered codes resolves to **HELD**, never to a guess
- [ ] An order is attributed by **its own month's** ownership, not today's
- [ ] A payout destination cannot be edited, deleted, or truncated
- [ ] No raw InstaPay address or account number appears in any audit record
- [ ] Every affiliate endpoint refuses the `affiliate` role
- [ ] `/api/operations/unregistered-codes` excludes owned codes
- [ ] ~~Backfill attaches orphans and **never** moves an attributed order~~ — moved to
      Phase 4 with `attributed_order`; see Task 8

---

## Deliberately not in this phase

- **The commission engine** — Phase 4. This phase decides *who*, not *how much*.
- **`attributed_order`** — Phase 4, with the immutable-`affiliate_id` rule. Task 6 produces
  the decision; recording it belongs with the table that stores it.
- **Targets** — Phase 5.
- **Payroll, snapshots, approval** — Phase 6.
- **The affiliate portal and onboarding flow** — Phase 8. This phase builds the registry a
  maintainer fills in; self-service comes later.
- **Password re-entry, notification, and the recent-change warning** for payout destinations
  (§6.4.1, .3, .5) — they need the portal and the notification outbox. The storage and masking
  are built now so they have something correct to sit on.

---

## Where the account comes from — settled

Phase 1 already answers this, and the onboarding flow the business described (§13) matches it
exactly:

| Step | What exists afterwards |
|---|---|
| 1. Maintainer invites by email | An `invitation` row. **No account.** |
| 2. Model opens the link, fills in their details, sets a password | `accept_invitation` creates the `user_account`. **`affiliate_profile` is created here, `pending`.** |
| 3. Maintainer verifies the code (§10.4), sets compensation and targets | Code period, compensation period |
| 4. Maintainer approves | Status becomes `active` |

So `affiliate_profile.user_account_id` is **not nullable and needs no placeholder** — the
account always exists before the profile does. No nullable foreign key, and nothing for Phase 8
to backfill.

**What Phase 3 builds is step 3.** Steps 1 and 2 exist (Phase 1 invitations); the *self-service
form* at step 2 is Phase 8. Until then a maintainer creates the profile directly, through the
same service function Phase 8 will later call from the acceptance flow. One code path, reached
two ways — not two implementations that must be kept agreeing.

## Decided, not open

**A code period closes at the current month when an affiliate is archived — never earlier.**
Ending it retroactively would rewrite past attribution and change months that are already
approved and paid. Archiving says "from now on, not theirs"; it cannot say "was never theirs".

If the business wants a code reissued to someone else, that is a new period starting the month
after — which the exclusion constraint permits and the overlap rule protects.

## Still open

**`house` in rankings.** §8 excludes house accounts from payable totals *and rankings*.
Payable totals are handled in Phase 4. Rankings do not exist yet; noted here so it is not
forgotten when they are built.
