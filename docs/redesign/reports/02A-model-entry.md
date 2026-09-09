# Batch report — Phase 02A, model entry and directory

**Date:** 9 September 2026
**Branch:** `phase02a/model-entry`, based on `main` @ `1f560a7`
**Requested scope:** Finish model entry and directory. Invite/accept/apply/wait/code verification/approve through real services. Preserve inactive/archive and house treatment. **Add real collaboration start as distinct data.** Optional measurements do not block application.

**Delivered behaviour:** The platform now records **when a model actually
started with HBA**, as a fact somebody enters rather than one it infers — and
her own month list is built from it. Height and weight can be given at
application, optionally, and staff can read them and cannot write them.

---

## Review

### The change that matters, in one line

Before, a model saw only the months money appeared in. Now she sees the months
she was here for.

On the running app, with the same seed data, before and after recording that she
started in June:

```
no start recorded  →  {"months": ["2026-09"]}
start = 2026-06    →  {"months": ["2026-09", "2026-08", "2026-07", "2026-06"]}
```

Those three extra months are ones she was on the programme and sold nothing in.
Rule H01 requires they be visible and empty; the old derivation dropped them,
and a model reading her own dashboard could not tell *you sold nothing* from
*you did not exist*.

### What the owner should try

1. Open any model's profile. There is a new first panel, **Who she is**, with
   **Started with HBA**. It reads *Not recorded* and says, in a sentence, that
   her months are being worked out from her earliest order and that this is a
   good guess and a different fact.
2. Press **Record it**, pick a month, Save. Then open her portal and step back
   through the months.
3. Try a month before January 2026. It is refused, and the refusal says why —
   the platform holds no orders before then, so it would open months nothing on
   the screen could explain. Months settled before the platform are a separate
   thing (H03).
4. On the application form there is now **Your height and weight — optional**.
   Leaving it blank changes nothing about the application.

### This is the field D01 is about

The column exists; **the values are yours.** D01 asks for actual collaboration
start months per model, and this is the interface that takes them. Nothing is
backfilled and nothing guesses — a model with no recorded start behaves exactly
as she did this morning, which is the compatibility guarantee for everyone
already on the platform.

### Approved-design deviations

**None.** Nothing in this batch has a drawn counterpart to deviate from — the
exports show a profile, not the mechanics of recording when somebody started.

---

## Engineering evidence

**Rules and IDs covered:** H01 (the whole batch), A05 (optional measurements,
model-writes-only), UI04 partially (optional height/weight at application),
UI09 unchanged and verified. **UI05 and UI06 are not marked complete** — invite,
apply, approve and the directory were verified as working through real services
and were not rebuilt, and the directory's own redesign is still owed.

### Files changed

| File | What |
|---|---|
| `migrations/versions/d4b81c07af22_…py` | **New.** Three nullable columns on `affiliate_profile` + three check constraints |
| `models/affiliates.py` | `collaboration_start_month`, `height_cm`, `weight_kg`, and the same constraints in the ORM |
| `services/affiliates.py` | **New:** `set_collaboration_start`, `update_measurements` |
| `services/portal.py` | `months_for` prefers a recorded start; the month walk extracted to `_months_between` and now shared |
| `services/applications.py` | `submit_application` takes optional measurements |
| `api/affiliates.py` | Payload carries the three fields; PATCH records the start month |
| `api/applications.py` | `height_cm` / `weight_kg`, bounded at the edge |
| `screens/AffiliateDetail.tsx` + `.css` | The **Who she is** panel, with a draft-and-save start month |
| `screens/Apply.tsx` + `.css` | The optional measurements pair |
| `screens/Affiliates.tsx` | The shared `Affiliate` type |
| `tests/test_collaboration_start.py` | **New**, 15 tests |
| `tests/test_affiliates_api.py`, `test_applications_api.py` | 9 more |

### Three decisions worth naming

**The recorded start wins even when an order is older.** An order attributed to
a month before she started is a matching error, not a reason to open that month
to her. Diagnostics for that belong on the maintainer's side, not in her picker.
Tested directly.

**Absence is not a value, so `null` needs a companion flag.** `PATCH` carries
`collaboration_start_month_set`. Without it, a request that only changes a phone
number would be indistinguishable from one clearing a recorded start — and
clearing is a real answer that puts her back on the derivation. Both directions
are tested.

**Measurements have no staff write path, and that absence is the enforcement.**
A05 gives the write to the model. A permission check inside a shared function
would still leave a function an admin route could call; instead
`update_measurements` has exactly one caller (her application), the profile
shows the values with no control beside them, and a test proves that sending
`height_cm` to the staff PATCH is *ignored* rather than obeyed. The model's own
edit screen is UI41, in 02B.

The audit records **that** she changed a measurement, not what to. The trail is
read by staff who may not change them, and "she updated her measurements" is the
whole of what an audit needs to know.

### Commands, results, environment

| Check | Result |
|---|---|
| `pytest -q --color=no` against `hba_platform_test` | **1613 passed**, 423.46s, **exit 0** — 1589 before, **24 new** |
| `cd frontend && npm test` | **106 passed**, exit 0 |
| `cd frontend && npm run build` | exit 0 |
| `alembic upgrade head` against the dev database | `a71f4c9be830 → d4b81c07af22`, clean |

Green before and after. The schema rebuild inside `conftest` migrates from
nothing every session, so the migration is proven to build as well as to apply.

### Verified on the running app, over HTTP

The screens call these routes; this drives the same ones with a real session and
CSRF token:

| Check | Result |
|---|---|
| `PATCH /api/affiliates/1` with a start month | `200`, payload returns `"collaboration_start_month": "2026-06"` |
| The same with `2025-04` | `400`, *"The platform holds no orders before 2026-01…"*, and the stored value unchanged |
| `GET /api/me/months` as that model, start cleared | `["2026-09"]` |
| `GET /api/me/months` as that model, start recorded | `["2026-09","2026-08","2026-07","2026-06"]` |

Synthetic seed data only. No real, customer or production data; no credentials or
PII in this report.

### Visual comparison — not performed this batch

**Honest limitation.** Sign-in through browser automation would not submit: the
typed value does not reach the field, the browser's own `required` check then
blocks the form, and **no request is made at all** — `POST /api/auth/login` never
appears in the server log. It is an automation problem, not an application one,
and it has recurred across batches. Rather than keep retrying I drove the same
routes over HTTP, above.

So the two new pieces of interface — the **Who she is** panel and the optional
measurements on the application form — have been type-checked and built but
**not seen rendered**. Worth a look before this merges; both are small.

---

## Continuation

### Limitations

- **Nothing is backfilled.** Every existing model still has no recorded start
  and behaves exactly as before. Filling them in is D01 and is the owner's.
- **The directory was not rebuilt.** It works, preserves inactive, archived and
  house accounts, and does not yet show a start month. UI06's redesign is owed.
- **The model cannot edit her own measurements yet.** The service exists and has
  one caller; the self-edit screen is UI41, in 02B.
- **Migrations do not run on `uvicorn` startup**, only in `docker-entrypoint.sh`.
  A local run needs `alembic upgrade head` first. Worth knowing before the next
  batch adds a migration; it cost ten minutes here.

### Decisions recorded

None new. **D01 now has the interface it needs** — the question is unchanged and
still the owner's.

### Next

**Phase 02B** — `docs/redesign/prompts/02_MODELS_AND_SETUP.md`, second batch:
the shared profile and self-editing. It is the first batch that is **blocked on
an owner decision**: D07 (contact email versus login identity) before any new
contact write, and D06 (the bank field — confirmed in the baseline report as a
real card-number-versus-account-number conflict, not a relabel) before touching
payout semantics. Measurements and the profile links can proceed either way.

**02C is largely already built** — the pay-history editor shipped in `63c64c3`.
What it still owes is per-month setup readiness, not the editor.

### Live changes

**None.** Nothing deployed, no production branch moved, no financial data
touched. The branch is local and unpushed.
