# 0052. A model's life: pause, archive, decline, reconsider and erase

**Status:** Accepted
**Date:** 2026-09-30

## Context

The admin Models tab could approve a model and nothing else. The backend had
four statuses (`pending`, `active`, `inactive`, `archived`) and an archive
routine, but the profile only ever sent `active`, so the *Inactive* filter
could never fill and nobody could be paused, retired or turned down. The audit
of 29 September (`docs/design/admin-models-tab-audit-2026-09-29.html`) found
this beside four gaps around it, and the owner approved all five
recommendations on 29 September, with two refinements on 30 September:

- **Pause and archive** from the profile, each with a written reason.
- **Decline** an application. There was no "no": an unwanted application sat
  under *Applications* for ever.
- **Pay terms before approval.** Approval checked only the code, so a model
  could go live showing *No terms set* while the panel said payroll stays
  blocked.
- **Delete a model who never earned anything.** Test and mistaken entries had
  no way out. The owner chose a *true* delete (30 September) over a
  remove-but-keep-the-trail option, knowing it needs the append-only guards on
  payout destinations and the audit log to let her rows go.
- **Pay terms for future months.** The editor listed months only up to the
  working month, so an agreed raise from next month could not be entered
  until that month arrived.

A declined applicant cannot simply be invited again: invitations refuse an
address that already has an account. The owner chose a *Reconsider* action
(30 September) over making a decline final.

## Decision

### Statuses

`pending`, `active`, `inactive` (shown as **Paused**), `archived`, and a new
`declined`. Every change of status is audited with who, when and the reason.
Only these moves are allowed: `pending` → `active`, `declined`, `inactive` or
`archived`; `active` → `inactive` or `archived`; `inactive` → `active` or
`archived`; `archived` → `active`; `declined` → `pending`. Nothing else
returns to `pending`, so a declined model meets the approval gates again.

### Pause (`active` → `inactive`)

A reason is required. She keeps her sign-in and sees that she is paused. Her
code keeps counting her orders and payroll is unchanged: pausing is a note on
the relationship, not a stop on earnings. To stop earnings, archive her or end
her code. **Reactivate** (`inactive` → `active`) needs nothing more than the
existing verified-code gate.

### Archive (`active` or `inactive` → `archived`)

A reason is required. Her sign-in closes; her open codes end with the current
month (`close_codes_for`, unchanged); her history, payroll and payments stay.
**Reactivate** from archived clears `archived_at`, because parcel matching
skips anyone with it set, and says plainly that her codes ended so a new one
must be registered before her sales count again.

### Decline (`pending` → `declined`)

A reason is required. She can still sign in, and sees that her application was
not accepted this time; nothing is emailed. Her code is released: if no order
has been attributed to her, her code periods are removed so another model can
register the code at once; if one has, they are closed as archiving closes
them. **Reconsider** (`declined` → `pending`) returns the application to
*Applications*; she cannot reapply by herself. A declined model appears under
*Inactive*.

### Approval (`pending` → `active`)

Requires a code Shopify has confirmed (unchanged) and, for an account that is
paid, **pay terms covering the working month**. A house account is never paid
and needs only the code. The screen asks for confirmation first and says she
is emailed.

### Erase (admin only)

A true delete, allowed only when nothing about money or goods ever touched
her: no attributed order, no payroll month, no payment, no payroll adjustment,
no parcel sent to her, no proof file. Never an account that also holds a staff
role, whose audit rows are the business's trail, and never the admin's own. It removes her profile, sign-in account,
sessions, codes, pay terms, targets, invitations to her address, queued
notices, payout destinations, and the audit entries she made or that are about
her, her account or the invitations sent to her. One new audit entry records that model #id was erased, by whom, when and
why, and carries none of her details.

**How the guards let it through.** The append-only triggers on
`payout_destination` and `audit_event` refuse `DELETE` unless the
transaction has set `hba.erasing_affiliate`, `hba.erasing_user` and
`hba.erasing_subjects` locally (`set_config(…, true)`), and then only for
rows of that affiliate, made by that account, or about one of those subjects. `UPDATE`
stays refused, `TRUNCATE` stays refused, and nothing outside the erasing
transaction sees the setting.

### Future pay terms

The terms editor lists months up to **twelve months after the working
month**. The last arrangement stays open-ended from wherever it starts, and an
approved month still cannot be changed. Applying asks for a review of what
changes, month by month, first.

## Consequences

- **Append-only is no longer absolute.** Two tables that promised *never
  deleted* now allow a scoped delete through one admin-only path. The price is
  accepted by the owner; it is contained by the eligibility check (no money,
  no parcels), the transaction-local setting, and the one audit entry that
  survives.
- A migration adds `declined` to the status check and replaces the two guard
  functions. It is additive; its downgrade restores both guards and refuses to
  run while any profile is `declined`. It joins the migrations to rehearse
  before release.
- Pausing does not stop earnings. If the business later wants *paused* to mean
  *not earning*, that is a change to attribution, not to this screen.
- Approving now needs terms. A model whose deal is not agreed stays under
  *Applications*, which is where an unagreed deal belongs.
- Erased is gone: there is no undo, and a question about her later has only the
  one audit entry to answer it.

## Alternatives considered

- **Remove but keep the trail** (hide her, free the email and code, keep the
  masked destinations and audit rows). Kept the guards absolute; the owner
  chose a true delete.
- **Disable the triggers for the delete** (`ALTER TABLE … DISABLE TRIGGER`).
  Global, needs table ownership, and takes a lock every other session waits
  on. The transaction-local setting is narrower.
- **Declined is final.** Simpler, but turning somebody down by mistake would
  have needed an erase and a new invitation. The owner chose *Reconsider*.
- **Pause stops attribution.** Would silently move a paused model's customers'
  orders to nobody. Not what was approved: the audit's pause keeps her code
  counting.
