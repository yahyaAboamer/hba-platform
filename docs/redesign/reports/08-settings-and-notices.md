# Batch report — Phase 08, settings and notices

Date: 11 September 2026.

Branch and base/current commit: `phase08/settings-and-notices`, based on `main`
@ `4b6f72c`.

Requested scope: **08A and 08B.** Preserve the admin operations in the approved
navigation — staff, Shopify health and retry, historical setup, house codes,
policy and audit. Then notices, preferences, theme and help: temporary hide
versus item mute versus resolution, two model email preferences that never
touch security mail, and help copy matching the new rules.

Delivered behaviour: **notices now behave the way A10 describes**, which is the
gap `STATUS.md` has carried since the baseline — and three pieces of copy that
had quietly become false were corrected.

08A needed nothing built. Saying so, with the audit, is most of its half of
this report.

---

## Review

### 08A — audited, and already there

A09 lists what Settings must retain. Every item is present:

| A09 asks for | Where it is |
|---|---|
| Staff, invitations, status | Settings — *Invite a member of staff*, *Staff & roles* |
| Shopify and sync health, retry | *Shopify & data* — catalogue, parcels, failed emails, work that did not happen, each retryable |
| Historical setup | *Import order history* |
| House codes | `AddHouseCode`, on `POST /api/affiliates/house` |
| Appearance | The theme toggle in each layout, stored per surface |
| Policy and reference | *Policy versions*, and the glossary |
| Audit and support | *Recent activity* |

And A09's negative requirement holds: **there is no credential field anywhere
in Settings or the data panel**, and nothing claims a connection it has not
made. The Shopify scope check is a diagnostic route with no button, by design.

S05 holds too: the roles screen maps existing server permissions and invents no
Marketing or Finance role from a prototype label.

**Nothing was changed in 08A.** It was read and confirmed.

### 08B — three things that look alike

A10 asks for three behaviours, and the failure to guard is the middle one being
mistaken for the last:

    hide for now     comes back; the browser's business, not the server's
    stop showing     persists, and resolves nothing
    fixing it        the notice stops being generated at all

**Hide** lives in `sessionStorage` and the server never hears about it — which
is exactly what makes it temporary. **Mute** is a row in `notice_mute`, so it
outlives the tab it was clicked in. **Resolving** ends it properly, at which
point the mute becomes irrelevant rather than wrong and nothing has to remember
to clean it up.

**A mute resolves nothing, so muted notices are listed back** under their own
heading — *"2 turned off · they are still unresolved"* — with a way to put each
one back. A mute must not become a thing nobody remembers turning off, and
somebody who did not set it should still be able to find the problem.

### The guard A10 does not state and I think it requires

**A blocking notice cannot be muted.** A10 lets somebody stop seeing a notice;
it does not let them stop seeing a stop sign. *"No go-live month is set, so
nothing can be approved"* is not noise to be turned off — it is the reason the
month will not close, and silencing it would make the platform quietly useless
rather than loudly stuck.

The route refuses it with a 400 that says fixing it is what makes it go away.

**Notices are links now**, which A10 asks for and they were not: one about a
single record opens that record, one about several opens a filtered list.

### Copy that had become false

The prompt asks for help and policy text to match the new rules. Three places
did not, and two of them were actively misleading:

**The month picker said "Approved — reopen to change it."** Reopening was
retired in 05B; that route answers 409. Telling somebody to press a button that
refuses is worse than saying nothing. It reads *"Agreed — changes are recorded
against it."*

**The reconcile screen** described an overpayment as *"usually because it was
reopened to a lower figure"*. That is no longer how one arises.

**The glossary predated Phase 05 entirely.** Three terms added:

- **Uses** — what D03 settled, and that it is not the same as sales: an order
  delivered and later refunded is still a use and pays nothing.
- **Agreed** — a month whose figure does not change afterwards.
- **Correction** — and this one exists because of **D04**. It says, in her own
  words, that a later month can be smaller than usual or come to nothing, that
  the month itself will say so, and that **she is never asked to send money
  back**. D04's record obliged the screens to explain a month that pays
  nothing; this is the help text half of that.

### What was verified rather than rebuilt

**M05's two email preferences** already map to the existing backend kinds —
month closed and payment sent — and `test_security_mail_is_not_something_a_model_can_mute`
already exists by name. There is no switch for a password reset or a change to
where money goes, because those are not news.

**Theme already persists** per device and per surface, with every storage
access wrapped: a private window makes the accessor itself throw, and a theme
is not worth a blank screen.

### What the owner should try

1. **Home → a notice → Hide for now.** It goes. Reload the page and it is
   still gone; open a new tab and it is back.
2. **Stop showing this.** It goes and stays gone — and appears under *turned
   off · still unresolved*, with **Show again**.
3. **Fix the thing itself.** It disappears from both lists.
4. **Unset the go-live month.** That notice offers no mute at all.
5. **Payroll → the month picker.** An agreed month no longer tells you to
   reopen it.

### Approved-design deviations and reason

**None.** The notice controls sit on the notices the design already has.

### Confirmation needed before the next dependent decision

**None.** D01, D02, D09 and D10 remain open; none blocks Phase 09.

---

## Engineering evidence

### Files changed

| File | Change |
|---|---|
| `migrations/versions/c93f2a17d4e8_notice_mute.py` | **New.** Where a muted notice is remembered |
| `app/models/notifications.py` | `NoticeMute` |
| `app/api/operations.py` | Muted notices filtered and listed back; `UNMUTABLE`; mute and unmute routes |
| `frontend/src/screens/Overview.tsx`, `.css` | Hide, mute, the muted list, and notices as links |
| `frontend/src/components/MonthPicker.tsx` | The reopen wording |
| `frontend/src/screens/PaymentReconcile.tsx` | The reopen wording |
| `frontend/src/lib/glossary.ts` | Uses, Agreed, Correction |
| `tests/test_notices.py` | **New.** 9 |

### Schema, migration and compatibility

**One migration, `c93f2a17d4e8`** — a single new table, no change to an
existing one, and a real `downgrade` that drops it. Nothing is backfilled:
before it, nothing was muted.

Keyed by the notice's key rather than by a record id, deliberately. A mute tied
to a row would outlive the row and could suppress a later, different problem
that reused the id.

**Forward and backward compatible.** An older client ignores the new `muted`
list and the two new routes; an older server simply has no mutes.

### Authorisation, idempotency and money

Both routes sit behind `affiliates.view` — the same permission that shows the
notices. **No money is touched and nothing about payroll changes.**

**Both are idempotent.** Muting twice is what a double-click looks like and
returns the same answer rather than a constraint violation; unmuting something
that was never muted is not an error. Tests for both.

### Existing failures distinguished from regressions

**No regressions.** Full suite **1873 passed**, up from 1858 — nine new here
and the rest from 07B. `test_operations_api.py` 64, `test_notifications.py` 37,
`test_migrations.py` 5, `test_reachability.py` 3 all pass.

### No real credentials or personal data in evidence

Nothing in this batch reads or stores a credential — and A09's requirement that
Settings contain no credential field was checked rather than assumed.

### Exact commands, actual results and environment

Windows, Git Bash, local PostgreSQL on 5433, migration head **`c93f2a17d4e8`**,
one pytest process at a time.

| Check | Actual result |
|---|---|
| Full backend suite | **1873 passed in 216.53s**, exit 0 |
| `tests/test_notices.py` | **9 passed**, exit 0 |
| `tests/test_operations_api.py` | **64 passed**, exit 0 |
| `tests/test_notifications.py` | **37 passed**, exit 0 |
| `tests/test_migrations.py` | **5 passed**, exit 0 |
| `cd frontend && npm test` | **256 passed**, exit 0 |
| `cd frontend && npx tsc --noEmit` | exit 0 |
| `cd frontend && npm run build` | exit 0 |

### Visual comparison — not performed

Automation cannot sign in. The notice controls and the muted list have not been
seen.

---

## Continuation

### Remaining limitations

- **A hide is per browser, not per person.** Two tabs in the same session share
  it and a different device does not. That is what *temporary* means here, and
  it is deliberate rather than missing.
- **Mutes are global, not per user.** One person muting a notice hides it for
  everybody. With two people running payroll that is arguably right — the
  decision is about the platform, not about a reader — but it is a choice, and
  a third staff member would make it worth revisiting.
- **`UNMUTABLE` holds one key.** Every blocking notice should probably be
  unmutable by severity rather than by name; it is a list of one because that
  is the only blocking notice today, and the rule is stated where it would be
  extended.

### Decisions recorded

**None new.**

### Exact next batch and prompt

**Phase 09 — rehearsal and release.**
`docs/redesign/prompts/09_REHEARSAL_AND_RELEASE.md`.

This is the last phase, and **D01 is its subject**: which month the platform
starts paying for, and which historical statements are already real. That
decision has been open since the package was written and 09 cannot finish
without it.

### Live deployment or data changes

**None in this batch.** `main` is at `4b6f72c` with 07B merged and staging
deployed; production was promoted by the owner earlier today.
