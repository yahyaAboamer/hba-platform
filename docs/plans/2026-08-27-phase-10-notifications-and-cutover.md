# Phase 10 — The platform speaks, and then it goes live

**Spec:** §16 (notifications, audit, policy), §18.2 (cutover), §10.5, §19, §12
**ADRs:** 0009 (Postgres as the job queue), 0017 (proof visible to the affiliate),
0021 (lease committed before work), 0030 (a reopened month emails once, on
re-approval)
**Depends on:** Phase 9 — every event this phase announces is a screen they can
now open
**Delivers:** the last build phase, and the cutover it exists to make possible

---

## The date decides the shape of this phase

Today is **27 August 2026**. The business intends to send sign-in links to
every model on **31 August**, so that the platform is theirs from the first day
of the month it starts paying for.

That is four days, and it changes what this plan should put first. So, plainly,
before any of the design:

### What actually stands between today and links going out

| | Status |
|---|---|
| **A deployed platform on a real URL** | **Nothing is deployed.** This is the blocker. |
| Affiliates, codes and current terms entered | Not started. §18.2 step 4, and it is the business's own work by design (§6.5). |
| A month verified against manual calculation | Not done. §18.2 step 5, and the spec makes it a gate on opening access. |
| Email that sends itself | **Not the blocker.** See below. |

**Email is not what is holding this up.** The Settings screen already produces
a working invitation link that can be copied and pasted. Twenty links into
twenty emails is an hour of somebody's evening, once. It is worth building the
sending properly — a sign-in link that arrives from `hbaaesthetics.com` rather
than a personal Gmail is the difference between a model trusting it and
deleting it — but if the four days get tight, **this is the piece that can be
done by hand and nothing else can.**

A deployment cannot. A verified month cannot.

---

## What this phase is for

Nine phases built a platform that is correct and silent. It knows when a
month closes, when money moves, when a payout destination is repointed at
somebody else's account — and it tells nobody. Every one of those is a fact
somebody needs on the day it happens, not the next time they think to log in.

This phase is the platform learning to speak, and then the cutover that makes
speaking worth anything.

### One rule underneath all of it

§16: **every email is written through `notification_outbox` in the same
transaction as the change that caused it.**

Not sent inline. A mail server that is slow must not make approving payroll
slow, and a mail server that is down must not make approving payroll fail — the
month was agreed either way, and an obligation that rolled back because an SMTP
handshake timed out is the worst possible trade. Equally, a month that was
agreed and whose email was never queued is a model who was paid and never told.

Writing the row inside the transaction is what makes those two impossible at
once. Sending it is a separate job on the queue that already exists (ADR 0009),
with the retry behaviour that already exists (ADR 0021).

### The other rule

**Every model gets email only.** There is no in-platform inbox for them; that
channel is the maintainer's. §16 says so explicitly and it is worth restating
here, because "notifications" is the kind of word that grows a bell icon in the
corner of every screen if nobody stops it.

---

## Task list

| # | Task | Delivers |
|---|---|---|
| 1 | The outbox | A row written with the change, never instead of it |
| 2 | Sending | The job that drains it, and what happens when it cannot |
| 3 | The six emails that matter | §16's table, in their language |
| 4 | Deploy | A real URL, a real database, real secrets |
| 5 | The maintainer's warnings | In-platform, where the maintainer already looks |
| 6 | Policy versions and the dictionary | Why a figure was what it was, and what the words mean |
| 7 | First-run polish | What a model sees on 1 September, when nothing has happened yet |

**Batches:**

- **Batch A — tasks 1, 2, 3, 4.** Everything on the critical path for
  31 August. Ends with a deployed platform that emails a working sign-in link.
- **Batch B — tasks 5, 7.** The maintainer's safety net, and the first
  impression.
- **Batch C — task 6.** Policy versions, the FAQ and the glossary.

Batch C is deliberately last. It is the one thing here that improves an
explanation rather than enabling an action, and if the calendar takes a bite
out of this phase, that is the bite to take.

---

## Task 1: The outbox

**Files:** `app/models/notifications.py`, a migration,
`app/services/notifications.py`; tests

One table. `notification_outbox`: recipient, event, payload, state, attempts,
last error, timestamps.

**Written in the caller's transaction, never in its own.** `queue()` takes the
session it was handed and adds a row; it does not commit, and it does not
open a connection of its own. That is the whole point — the email and the thing
it announces succeed together or fail together.

**The payload is frozen, not a set of references.** The same reasoning as
`payroll_snapshot` (§11.1): an email that resolves *"their September figure"* at
send time will say something different from the screen if anything moved in
between, and the model will be reading both.

**Not append-only**, unlike the audit tables — an outbox row is a piece of work
that changes state as it is done. The audit trail of what was sent is the
`audit_event` written beside it.

## Task 2: Sending

**Files:** `app/services/mail.py`, a job handler, `app/config.py`; tests

A job that leases pending rows, sends, and marks them. The queue, the leasing
and the backoff are Phase 2's and unchanged (ADR 0009, ADR 0021).

**The provider is behind one interface with a no-op default.** Blank
credentials mean the platform runs, queues, and logs what it *would* have sent
— exactly as Shopify is blank by default so health checks work on a machine
with no credentials. A test suite that needs a mail server is a test suite that
stops being run.

**A bounce is not a retry.** A refused recipient and a timed-out connection are
different failures: one will never succeed and one probably will next minute.
Retrying a dead address five times only delays somebody noticing the address is
dead.

**Nothing sensitive travels in an email.** No account number, no InstaPay
address, no password, no full order detail — the standing rule for audit
records and logs applies here more strongly, because mail is the one channel
that leaves the building. An email says a figure and links to the screen.

## Task 3: The six emails that matter

**Files:** templates, `app/services/notifications.py`; tests

§16's table, in the order they matter for going live:

| Event | To | Why it is here |
|---|---|---|
| **Application approved** | Model | **The one that carries the sign-in link.** This is what goes out on 31 August. |
| Application submitted | Model + maintainer | They know it arrived; somebody knows to look. |
| Month approved | Model | What they are owed, now fixed. §11.1's whole distinction, delivered. |
| Payment recorded | Model | With the receipt (§14, ADR 0017). |
| **Payout destination changed** | Maintainer, immediately | §6.4.5. The one email that is a security control rather than a courtesy. |
| Month **re-approved** | Model | ADR 0030, and the case with the sharpest edge — below. |

**Re-approval is where care is needed.** ADR 0030: a reopen sends nothing, and
the existing "month approved" email covers re-approval with two additions when
`version > 1` — the difference from the previous version and the written
reason, in plain language rather than copied from the audit log.

And the sharp one: **if the new figure is lower than what was already paid, the
email goes immediately, before any correction is applied.** There is no
transfer to attach the news to and nothing will change in their bank account, so
without it the first they hear of an overpayment is a smaller payment next
month. It names the resolution that was chosen: *"E£300 will come off next
month's payment"*, or *"nothing further is needed from you"*.

**Every email links to the screen that explains it.** Phase 9 built those
screens; an email that restates a breakdown is a second place for the figures
to disagree.

## Task 4: Deploy

**Files:** `railway.json`, `nixpacks.toml` (both exist), configuration; docs

Not code so much as a sequence, and **most of it is the business's to run** —
see *What only you can do* below.

The build is already deployable: one service builds the Python API and compiles
the frontend into `app/web`, migrations run at start so a deploy that cannot
migrate fails its health check rather than serving a half-migrated database.

What this task adds: the mail configuration, the public base URL that
invitation links are built from, and a written cutover checklist that follows
§18.2 rather than being reconstructed from memory on the night.

**Two environments, and the second one is the answer to "how do I test this?"**
A staging deployment with its own database is where a full walk-through
happens — real sign-in, real invitation email, real payroll run — without a
single row of it touching what models will see. It is also the only honest way
to test the emails, because an email that links to `localhost` proves nothing.

## Task 5: The maintainer's warnings

**Files:** `app/api/operations.py` (exists), an overview panel; tests

§16's bottom two rows: sync failure, failed job, unattributed code, multi-code
hold, stuck reopen, and the payroll reminder on the 5th.

**Most of this data already exists.** `/api/operations/sync`, `/failed-jobs`
and `/unregistered-codes` were built in earlier phases and are read by the
Settings screen. What is missing is the part that matters: **the maintainer
should not have to go looking.** These belong on the Overview, where somebody
lands, and quiet when there is nothing to say.

A warning that is always on is one nobody reads — the same rule the
destination-changed notice already follows.

## Task 6: Policy versions and the dictionary

**Planned:** 2026-08-30. Deliberately last, per the batch note above — the
calendar took the bite it was allowed to, and this is it. Written now because
the platform is live and both halves have real content to describe rather than
a guess at what the rules will turn out to be.

Two features that got bundled under one task number because the business
asked for them together, not because they share a data model. They are built
and shipped as two independent pieces.

### 6a. Policy versions

**Files:** a migration on `payroll_snapshot`, a `policy_version` table, the
calculation path that stamps it, a maintainer screen to add one, the figure a
model sees; tests

**The column already has a comment written for it.** `app/models/payroll.py`
says so directly: *"no `policy_version` column yet... a column nothing writes
reads as a feature and is a lie."* This task is the thing that fills it.

**What "versioned and effective-dated with plain-language text" means here,
concretely** - two things this project has never needed to distinguish before:

- **The engineering record** is the ADRs. 0002 through 0031 already say
  exactly what the rules are and why, precisely and for nobody but whoever
  reads code.
- **The policy version** is the same rules, translated once into what a model
  reads: *"Commission is worked out on the sale price after any discount and
  after shipping and tax are taken off. If a parcel is refused within 10 days
  the commission it earned is reversed. A guaranteed minimum only pays in a
  month your targets were both met and confirmed."* Nothing new is decided
  here - it is translation, not policy-making.

**The model.** `policy_version`: `id`, `effective_month` (the first business
month it governs), `summary_markdown` (the plain-language text), `created_at`,
`created_by`. Nothing is ever edited or deleted - a rule change is a new row
with a later `effective_month`, exactly the append-only discipline every
other money-adjacent table in this platform already holds to.

`payroll_snapshot.policy_version_id` records which version was in force when
that snapshot was calculated - looked up once, at calculation time, by
`effective_month <= month order by effective_month desc limit 1`, and frozen
into the snapshot the same way every other figure on it is frozen. A policy
version created *after* a month was calculated never touches that month's
snapshot, for the same reason a compensation change never touches an approved
one (ADR affecting `assert_correctable`): a snapshot is what a model was told,
and what they were told does not change because the wording changed later.

**Backfilling.** Every rule this platform has ever calculated under is, in
effect, one policy that was never written down as such. There is no v0 to
distinguish it from. So: **policy v1 is written now**, dated to
`GO_LIVE_MONTH`, describing the ruleset as it stands today - and a migration
sets `policy_version_id = 1` on every snapshot that predates the column,
rather than leaving them `null` and making "which rules applied here" a
question the data cannot answer for the platform's own first months.

**Where it appears.** One line on a settled month, model-facing: *"Calculated
under the rules in force since September 2026."*, linking to that version's
text. Nothing changes for a month whose policy never changed - this is only
visible as a fact worth stating once a second version exists to distinguish
from.

**A new one is added by the maintainer**, not edited into existence by a
migration each time - a small screen (name, effective month, the text) in
Settings, gated the same way compensation and targets are: recording facts is
one permission, deciding what they mean is another. Given how rarely the
actual rules change (a handful of ADRs across ten phases), this does not need
to be more than a form with a text area.

**What needs a decision, and it is not code.** *Who writes the plain-language
text?* Recommended: drafted here, from the ADRs, the same way every other
plan and spec document in this project has been - and reviewed by the
business before it ships, the same way every plan has been. Not a live
self-service editor for v1; the rules do not change often enough to earn one,
and a form that is only ever touched a handful of times per year is exactly
the kind of screen that is safer built plain than built flexible.

### 6b. The dictionary

**Files:** a static glossary screen, links from wherever a term already
appears; no migration - this is content, not data

**Six places already explain these words, separately**, checked directly
rather than estimated: `Money.tsx`, `AffiliateDetail.tsx`, `Compensation.tsx`,
`MyMonth.tsx`, `MyOrders.tsx`, `Orders.tsx`, `Payroll.tsx`, `Targets.tsx` all
define at least one of *carried forward*, *pending*, *void*, *guaranteed
minimum*, *provisional* inline, in their own words, at the moment a screen
needs them - eight files, at last count, not the six the original note
guessed. Each explanation is honest on its own and none of them are
guaranteed to say the same thing five phases from now.

**One page, both sides.** The definitions do not differ between what a
maintainer needs and what a model needs - *void* means the same thing on the
Payroll screen as it does on MyOrders. So this is **one glossary**, not two,
reached from both the maintainer's layout and the affiliate portal's, which is
also what keeps it from drifting into two dictionaries that quietly disagree.

**Terms, gathered from the eight files above rather than reinvented:** *carried
forward, pending, void, guaranteed minimum, provisional, historical, settled,
verified* - each a sentence explaining what it means and, where useful, why
the platform draws the line where it does (*void* is not "we chose not to pay
this," it is "the parcel came back, so there is nothing to pay on").

**Not a replacement for the inline explanations that already work.** A
tooltip that already says the right thing at the moment somebody needs it
stays exactly where it is - this is the page a person reaches when the
tooltip is not enough, linked from an ⓘ beside each term rather than
replacing the sentence already there. Removing working inline copy to force a
navigation would be a worse experience wearing a tidier information
architecture.

## Task 7: First-run polish

**Files:** `MyMonth.tsx`, `AffiliatePortal.tsx`

A model who signs in on 31 August or 1 September opens on September, and
September has nothing in it. Today that reads *"Still adding up — E£0.00"*,
which is true and lands badly as a first impression of a platform they were just
invited to.

It should say the month has not started rather than showing them a zero. Small,
and it is the first thing twenty people will see.

---

## What only you can do

Everything here needs a decision or a secret, and **no secret should ever be
pasted into this conversation, the repository, or a file I can read.** Set them
in Railway's variables yourself; I will tell you the names.

### 1. How email gets sent — a decision, then a secret

Two routes, and I would not pick the same one for both cases:

**A transactional provider** — Resend, Postmark, Brevo, SendGrid. Needs a
domain HBA controls and two or three DNS records (SPF and DKIM). Emails arrive
from `no-reply@hbaaesthetics.com`, land in the inbox rather than spam, and you
can see what was delivered.

**Gmail with an App Password** — turn on 2-factor authentication on the Google
account, then generate a 16-character App Password (a normal Gmail password
will not work for SMTP). Free and quick.

**My recommendation: the provider, if HBA owns a domain.** These emails carry
sign-in links, which is precisely the shape spam filters are trained on. A link
from a personal Gmail address asking a model to sign in and check their payout
details is one that a careful person *should* distrust — and one an incautious
person clicking teaches to trust the next one, which may not be from you.

What I need from you either way: **which route**, the **From address and
display name**, and the secret set in Railway.

### 2. Railway — a decision, then several approvals

The Railway account connected to this session is **`yahyaaboamer's Projects`,
and it has no projects in it.** It cannot see the `HBA_Server` workspace where
the old `hba-affiliate` dashboard lives, which is a useful accident: I could
not disturb the live dashboard from here even by mistake.

You need to decide **where the new platform is deployed** — that personal
workspace, or HBA_Server alongside the old one. Then:

- **Provision a Postgres database** (production, and a second for staging)
- **Set the variables**: `DATABASE_URL` (Railway provides it), `APP_ENV`,
  `GO_LIVE_MONTH=2026-09`, `PUBLIC_BASE_URL`, the Shopify credentials, and the
  mail secret
- **Approve each operational action.** I will not create, deploy or change
  anything on Railway without you saying so for that specific action.

### 3. Shopify — confirm, do not re-scope

The credentials are read-only (`read_orders`, `read_all_orders`,
`read_discounts`) and stay that way. You will need to set the same values in
the deployed environment, and then run the historical import (§18.2 step 3).

**No write scope is ever added.** If something appears to need one, that is a
conversation, not a checkbox.

### 4. The data, which is yours by design

§18.2 step 4: every affiliate, every discount code verified against Shopify,
and **current compensation terms for everybody**. §6.5 makes this structurally
yours — the application form has no field for a rate, and it never will, so
this cannot be delegated to the models filling in their own details.

This is the largest block of your time in the next four days and the one thing
that cannot be shortened.

### 5. The gate, which I will keep asking about

§18.2 step 5: **verify a known month against manual calculation before opening
access.** Take August — nearly complete, real orders, real codes — run it
through the platform, and check the figures against how you would have worked
them out yourself.

If they match, the platform has earned the right to tell twenty people what
they are owed. If they do not, it is far better to find that out on 30 August
than in a message from a model on 6 September.

### 6. Your own password

Unchanged and unchangeable: the bootstrap account is yours to create, with a
password I never see and never set.

---

## How you will test the whole thing

This is the staging environment, and it is Task 4's second half.

**A separate Railway project, or a separate environment inside one, with its
own Postgres.** Same code, same build, different database and different
variables. Nothing in it can reach production data, because it has none — the
isolation is a different database, not a flag somebody has to remember.

Then you walk through the whole thing as both people:

**As the maintainer.** Bootstrap your account. Invite a model — use a second
email address of your own. Approve their application, set what they are paid,
register their code. Run the Shopify import. Open Payroll, look at the blockers,
approve a month. Record a payment with a screenshot. Reopen a month and watch
what the model is told.

**As the model.** Open the invitation email on your phone — not on a laptop,
because §12.5 built that portal for a phone and that is where twenty people
will open it. Accept it, apply, set your InstaPay address. Then look at
Earnings, Orders and Payments, and try to make the numbers meet the way a model
would.

**Set `GO_LIVE_MONTH` in staging to a month with real data in it** — August,
not September. September is empty until it starts, and testing against an empty
month proves only that empty months render. This is the single most useful
thing about having a staging environment: it can lie about the date in a way
production must not.

**Then throw it away and do it again.** Staging exists to be reset. The moment
it accumulates state you are reluctant to lose, it has stopped being a test
environment.

---

## What this phase deliberately does not do

**No SMS or WhatsApp.** §16 says email, and adding a channel means a second
delivery guarantee, a second failure mode and a second thing to be wrong about
somebody's money.

**No in-platform inbox for models.** §16 is explicit: that channel is the
maintainer's.

**No CSV export.** §19 mentions formula neutralisation *on export* and nothing
in V1B exports anything. Building the export in order to satisfy a security
note about the export is backwards.

**Reporting stays small.** The phase-table line says "reporting" and the spec
never defines it beyond one mention of *programme reporting* in §10.2. What
earns its place is a month-end summary the maintainer can read at a glance —
what the programme cost, who was paid, what is outstanding. Anything more
specific should come from somebody wanting a number they cannot currently get,
and nobody has asked for one yet.

---

## What "done" looks like

A model gets an email on 31 August from an address that looks like HBA's. They
open it on their phone, sets a password, fills in where they want to be paid,
and sees that September has not started yet.

In early October they get a second email: September is agreed, and here is what
they are owed. They open it, and every figure adds up against what they sold.

The gap between those two emails is five weeks in which they can watch their own
month forming and never has to ask anybody how it is going.

Nobody at HBA had to tell their any of that, and nobody had to remember to.
