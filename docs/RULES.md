# The rules — one shared source, for every agent and every person

**This file is the single current statement of how HBA's platform must behave.**
`CLAUDE.md` and `AGENTS.md` both point here and neither repeats it, because two
copies of a rule are two rules the moment one is edited.

Everything below was moved here **verbatim** from `CLAUDE.md` on 24 September
2026. Nothing was reworded, relaxed or added. The move was a workflow reset,
not a rule change.

## How to change a rule

You do not change one here first. A rule that needs to move needs an **ADR**
saying what is being traded and what it costs (`docs/adr/README.md`), and then
this file follows it. A superseded ADR is never deleted; it is marked and left
in place, and so is the sentence here that it replaced.

## What this file is not

- **Not the workflow.** How to run the tests, which branch to push, how to
  take a screenshot: `CLAUDE.md`.
- **Not the reasoning.** Why a rule exists, in full: `docs/adr/`.
- **Not the specification.** What the system does:
  `docs/specs/2026-08-22-hba-platform-v1-design.md`.
- **Not the failure register.** What has broken and what it looked like:
  `docs/limits.md`.

---

## The two halves, and Operations

| | Who | Look |
|---|---|---|
| **Maintainer** | Owner, marketing and finance teams on laptops | Laptop-first; match the approved Admin HTML structure and styling |
| **Affiliate portal** (`.affiliate`) | Models on phones | Dark by default, denser, phone-shaped |
| **Operations** (ADR 0057) | The one operations manager, and the admin | Laptop-first, usable on a phone. Its own shell, built from the owner-approved mockup (`docs/design/operations-dashboard-2026-10-03.html`), because no approved export draws it. Same tokens and palette as the maintainer's tool. |
| **Inbox** (ADR 0059, being built) | Customer service, the operations manager, and the admin | Laptop-first, usable on a phone. Its own shell, built from the owner-approved mockup (`docs/design/whatsapp-inbox-2026-10-11.html`). Same tokens and palette. |
| **Production** (ADR 0069, decided, not built yet) | The production team, its suppliers through the supplier portal, and the owner | **Its own look, exactly as the app the owner approved**: dark, its own green, its own typeface and sidebar. The one department that does not use HBA's tokens, by the owner's decision. Not restyled either way without a new ADR. |

**Decided, not built yet: one frame for every department (ADR 0068)**, from
the owner-approved mockup `docs/design/hba-os-shell-2026-10-25.html`. One
sidebar lists the departments a person holds and replaces the dashboard switch
and Operations' and the Inbox's own shells; their screens inside do not change.
Until it is built, the rows above describe what runs.

**One palette across both, since ADR 0039** — HBA green, both themes, defined
once in `tokens.css` with the accent alone in `accent.css`. `portal.css` is
still scoped to `.affiliate`, but it now isolates *layout* rather than colour:
the phone's spacing, its tab-bar clearance, its furniture. **Keep that
isolation** — it is why the portal could be redesigned three weeks before
payroll without touching a maintainer screen.

## Rules that must not be broken

- **Money is integer piastres.** Never a float. Multiply first, divide once
  (ADR 0003), round once on the total (ADR 0004).
- **Nothing about money is calculated in the browser.** The server sends the
  figure; a second implementation is a second answer waiting to disagree in
  front of the one person guaranteed to check.
- **An agreed month's *money* is read from its snapshot**, never recalculated.
  A live recalculation under the word "paid" presents a working number as a
  debt. **Her sales and order counts are the opposite** (F13, ADR 0040): they
  describe what happened in the month, so a parcel refused in November
  corrects September's sales and chart while September's agreed total does not
  move. A difference after approval is settled as a correction (05C), never by
  restating the agreement.
- **A pending order counts** (F02, ADR 0040). Pending and delivered are paid;
  a failed delivery is not. Approval settles every order it counted, and
  `carried_into` now pays only what a *delivered-only* approval left out — a
  backlog that shrinks and is never added to.
- **A return freezes the order; a cancelled fulfilment carries nothing**
  (ADR 0051, amending how 0025 is applied). Delivered is judged on the
  fulfilments created up to the first delivery; on an order with a return,
  later ones (exchanges) are ignored, and so are cancelled ones anywhere. Its
  items are what those fulfilments carried; its base, when not already final,
  is the cash paid up to delivery less shipping and tax. Rebuilt from Shopify's
  history, so it is the same whenever the order was first seen.
- **A code use is every order that used her code** (ADR 0049, superseding
  D03's definition): delivered, pending, failed delivery, cancelled or
  refunded alike. *Orders counted* is delivered and pending only (F02).
  Uses are a display figure and Ranking's tie-break; nothing about money
  reads them.
- **No component names a colour directly.** The accent lives in
  `frontend/src/styles/accent.css` — eight declarations, now covering both
  halves (ADR 0039) — and `styles/__tests__/accent-isolation.test.ts` fails the
  build if those values appear anywhere else.
- **No customer data.** `order_index` and `attributed_order` hold no name,
  address, phone or email, and a test keeps it structural. **The customer
  inbox's own tables are the one exception** (ADR 0059): a customer's phone,
  name, messages and files live there and nowhere else.
- **A correction settles money that moved; a balance is money that has not**
  (ADR 0041, amending 0035). Carrying a difference into a later month recovers
  it **there** — taking it off the source month as well recovers it twice, and
  reported E£800 still to send on a month agreed at E£2,000 with E£1,000 sent.
  Absorbing records an **`accepted`**, always: a `writeoff` means *we are not
  sending the rest* and still reduces a balance, which is the opposite of HBA
  taking a loss. Absorbing takes the whole remaining difference, so carry what
  is recoverable first.
- **One gate in front of every writer of a model's money**
  (`app/services/money_gate.py`). `approve_month`, `corrections.resolve` and
  `record_payment` all take it **before reading anything they decide on**, not
  before writing. It locks the *affiliate* row rather than a month because
  approval and `resolve` need the same two month rows in opposite orders, and
  one lock has no order to get wrong. It re-reads on the way in.
- **The payer sees the whole destination** (ADR 0042, amending 0028). The
  approved design puts the real number on the payments row, and the full
  details plus the submitted InstaPay link on the detail card **and on the
  model's profile**, with no reveal step - the owner asked for that
  explicitly. One component draws it (`components/DestinationDetails.tsx`) and
  one permission gates it (`payments.record`), because the screen that drifted
  was the second copy. `mask_destination` still governs every *record*: audit
  rows, logs, notices, change confirmations.
- **Money reads `EGP 1,062.00`**, with the space and a U+2212 minus - the
  approved export's `egp()`, character for character. It said `E£` on every
  screen until 23 September; that was ours, not the design's. Two formatters
  render it, `app/core/money.py` and `frontend/src/lib/money.ts`, and
  `money.test.ts` holds them to the same examples. Two implementations of a
  *format* are safe in a way two implementations of an *amount* are not - but
  they still have to agree.
- **The payments desk is a list of people on the programme** - not
  applications, and not months somebody had not started yet
  (`payments.on_the_desk`, the export's `participants(month)`). The sidebar
  badge counts through the same function: they were computed separately once,
  and the sidebar said 22 over a list of 19.
- **Historical finalisation is locked** until `HISTORICAL_FINALISATION_UNLOCKED`
  is set on that environment. The *review* is never locked - it is how the
  gaps are found. What HBA must supply first is listed in
  `docs/repair/HISTORICAL-INFORMATION-NEEDED.md`.
- **A settled month reads like any other month to the model** (ADR 0054): with
  terms recorded for it, her portal shows its calculated figure, breakdown and
  average order without it being approved. Only its pill (*Settled*) and its
  payment line (*Paid directly by HBA*) differ, and it is never owed. With no
  terms it shows her sales and says HBA settled it directly - never a guessed
  rate.
- **Append-only tables stay append-only**: `payroll_snapshot`,
  `payment_transaction`, `payment_allocation`, `payroll_adjustment`,
  `payout_destination`, `policy_version`. Guarded by triggers. **One
  exception (ADR 0052):** erasing a model who never earned lets her own
  `payout_destination` and `audit_event` rows be deleted, inside that one
  transaction (`SET LOCAL hba.erasing_affiliate`); update and truncate stay
  refused.
- **A model's life (ADR 0052).** Statuses are `pending`, `active`,
  `inactive` (*Paused*), `archived` and `declined`; every change carries a
  written reason.
  - *Pause* keeps her sign-in, her code and her earnings.
  - *Archive* closes her sign-in and ends her codes with the current month;
    reactivating clears `archived_at` and ~~she needs a new code~~ **restarts
    her own code from the current month** (ADR 0053, amending 0052).
  - *Decline* **deletes the application** (ADR 0058, amending 0052): her
    account, profile, code and details go, one audit entry keeps who declined
    it and why, and her address can be invited again. Only when an order,
    payroll, payment, parcel or proof is already hers, or she holds a staff
    role, is she kept as `declined`: her code released, *Reconsider* returning
    her to Applications, and no row on the Targets grid.
  - **Approval needs a verified code and, for a paid account, pay terms
    covering the working month.**
  - *Erase* is admin-only and only for a model with no order, payroll,
    payment, adjustment, parcel or proof file.
- **A code starts in the month it was created on Shopify, and so does the
  model who holds it** (ADR 0053, amended by 0055): the creation date, in
  Cairo, never before January 2026, for both her code's ownership and her
  start month. Never the code's *Active from* date, which a duplicated
  discount copies. Orders with the same code text from before its creation
  belong to whoever held the earlier code (ALI10 OLD). Her start is written
  when Shopify confirms her code, only if none is recorded; staff may still
  change it on her profile. **Her code is the one she applied
  with and is never replaced** - there is no route to register another or move
  her onto a new one. **While her application waits and no order is counted
  to her, her code may be changed, confirmed or not** (ADR 0058); a start
  month taken from the old code follows the new one.
- **Nobody grants access they do not hold** (`can_grant`). An invitation, a
  resend and a withdrawal are all held to it; nobody changes or suspends their
  own staff account.
- **Operations only reads, and never decides pay** (ADR 0057). It writes
  nothing to Shopify, Bosta or E-stebdal. Bosta's data is for operations only: delivery for pay is still
  read from Shopify (ADR 0023).
- **One operations manager, and Operations stands apart** (ADR 0057).
  - Exactly one person holds the role at a time, and the database refuses a
    second. Only an admin gives it, and he invites nobody.
  - He sees nothing of models, codes, targets, payroll or payments. Nobody but
    him and an admin sees Operations.
  - No customer name, phone, address or note is stored or shown there.
  - He also holds the customer inbox (ADR 0059).
- **The customer inbox stands apart, and holds the only customer data**
  (ADR 0059).
  - Customer service sees the inbox and nothing else. Any number of people
    may hold the role, and only an admin gives it.
  - Affiliate managers, content managers and models see nothing of it.
  - Only an admin sees or changes its keys. They are stored encrypted and
    never shown, logged or audited.
- **The platform writes to Shopify only to tag an order's confirmation**
  (ADR 0059) **and to ask Shopify to email an unpaid international order's
  invoice** (ADR 0062), and only through a second Shopify app.
  - The connection that reads money stays read-only (ADR 0015). The app it
    uses is refused as the second one.
  - The second app is refused unless it may change orders.
- **Nobody is messaged by accident** (ADR 0059).
  - Sending is off until an admin turns it on, and off again when the
    WhatsApp number is changed.
  - A server messages customers only when told it may
    (`INBOX_SEND_TO_CUSTOMERS`, set on production alone). Any other server
    messages only its listed test numbers. This does not rely on `APP_ENV`,
    which staging also sets to `production`.
  - Only an Egyptian mobile number is messaged; anything else is refused,
    not guessed at. The one exception is a payment request (below), which
    reads a foreign number with the shipping country's calling code.
  - An order gets one confirmation, and a paid order gets none.
- **An answer tagged in Shopify counts** (ADR 0063).
  - When exactly one of *Confirmed*, *Edit* or *Cancelled* is on an order in
    Shopify, that is the order's answer, recorded as given in Shopify. Two at
    once are left alone. Reading a tag never writes one back.
  - Inbox → Confirmations' action cards count only orders still open in
    Shopify: not cancelled and not shipped. Under each card, one line says
    how many already were. *Confirmed* and *Paid by link* count every order.
- **An international order is paid before it ships** (ADR 0062).
  - An order shipped outside Egypt that still owes money gets a WhatsApp
    payment request with Shopify's own payment link, instead of the
    confirmation. Shopify's invoice email is sent once as well.
  - The link is read from Shopify each time it is sent and is never stored.
    A link that doesn't begin with the approved template's link is not sent.
  - There is one reminder, 24 hours later, if it is still unpaid. After 72
    hours it is shown as needing a person. Nothing is cancelled
    automatically.
  - Off unless `INBOX_PAYMENT_REQUESTS_ENABLED` is set.
- **Operations' numbers are at most 10 minutes old** (ADR 0057).
  - The platform reads each source every 5 minutes.
  - A source that can't be read shows as a failure, never as 0.
  - Its day limits count working days in Cairo time, Saturday to Thursday.
- **A parcel is hers only when its number is hers** (ADR 0060). Her numbers
  are her profile phone and every number staff confirmed for her by
  assigning a gift. A number two models share attaches to neither. Free
  orders with a discount code that match nobody are listed in Settings for
  staff to assign or dismiss; nothing is matched by name.
- **A product can be assigned to a model by hand** (ADR 0061), for a piece
  she has without a gift order. It counts as received in her wardrobe and
  the product's coverage, once per model; removing it never touches a parcel.
- **Staff can look at a model's portal, read only** (ADR 0064). Anyone who
  may open her profile sees her real screens and figures, and changes
  nothing. The server has no write route for it and her payout details stay
  shortened. Each look is audited under the staff member, never as her.
  Her own `/api/me` routes still answer only to her.
- **No targets before her start** (ADR 0056). Once her start month is known,
  the server refuses creating, changing or counting a target before it, and
  *Whole year* skips those months. The Targets grid draws her row closed there.
- **Pay terms are set only for months that have begun, from her start month**
  (ADR 0055, replacing 0052's *twelve months ahead*). The server refuses an
  arrangement starting after the working month, or, once her start is known,
  one that changes a month before it. The latest arrangement runs on until further notice, so
  each new month takes the terms of the month before it. An approved month
  still cannot change.
- **One application and one database, arranged by department** (ADR 0065,
  ADR 0066; decided, not built yet). No department becomes a separate
  service, app or database. Every table belongs to one department and only its
  code writes it; other departments read through its functions. New tables
  carry their department's prefix. Customer details still live only in the
  inbox's tables.
- **A person may hold several roles** (ADR 0067; built, except two-step sign-in, which is decided and not built yet). What
  they may do is everything their live roles grant together; roles stay
  defined in code. Screens ask about permissions, never role names. Money is
  created, approved and paid under three separate permissions, and only the
  owner holds all three. Two-step sign-in is required for the owner and anyone
  who approves or pays money.
- **Production keeps its own look and changes only in this repository once it
  has moved** (ADR 0069; decided, not built yet). Its data belongs to the
  Production department in HBA's database; its sign-in is HBA's; suppliers
  reach only the work assigned to them. Its costing and payments record no
  money until a separate decision brings them under the money rules.
- **Three compensation types, not one.** `commission`,
  `fixed_plus_commission` (**both** are paid — the one most often got wrong),
  `base_guarantee` (`max(commission, base)`, only where targets were met *and*
  verified). No screen may hard-code an arrangement.

## Where the reasoning lives

- **`docs/adr/`** — 69 ADRs, indexed by hand in `docs/adr/README.md`. 0014 is
  superseded by 0036; 0027 is amended by 0038; **0035 is amended by 0041**, in
  one clause — a *write-off* closes a debt and a *credit* does not.
- **`docs/limits.md`** — every failure met, what it looked like from outside,
  and the fix. **Read this before debugging anything.**
- **`docs/plans/`** — what is being built and why.
- **`docs/specs/`** — the original design.
- **The code comments.** This codebase explains its own decisions; a docstring
  that says "and this caught us once" is describing a real incident.

---

## In force during the audit repair, and not a business rule

These are the owner's standing instructions for this branch, kept here because
an agent reading only the rules must still not do them:

- **No merge and no deployment.** Repair work stays on its branch. The
  build-phase instruction to push `main` and `production` together is
  **paused**, not retired - `CLAUDE.md` says by what and when it resumes.
- **Historical finalisation stays locked** behind
  `HISTORICAL_FINALISATION_UNLOCKED` until HBA supplies and verifies the five
  items in `docs/repair/HISTORICAL-INFORMATION-NEEDED.md`, and confirms order
  completeness for those months. The *review* is never locked.
- **Never run destructive fixtures against staging or production.** The test
  runner refuses any database that has not said inside itself that it is
  disposable; that guard is not to be worked around.
