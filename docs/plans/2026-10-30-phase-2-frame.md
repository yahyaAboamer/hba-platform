# Phase 2 — One frame for every department: plan

**Written:** 30 October 2026, from ADR 0068 (with ADR 0067 for access), the
approved mockup `docs/design/hba-os-shell-2026-10-25.html`, and the frontend
as it is on `main` at `7aaf2c3`.
**Status:** Approved by the owner on 30 October 2026, with the recommendation
on every one of the *Choices*. Batch 2.0 in progress. Each
batch is its own branch and its own pull request; **nothing is merged or
deployed without the owner's separate word for each** (`CLAUDE.md`).
**The approved mockup wins** over taste and over earlier internal decisions.
Where this plan departs from it, the departure is listed under *Choices* with
the reason, and nothing departing is built until the owner has chosen.

## In plain words

Today the staff side is three dashboards with a switch under the logo:
Affiliates (which owns `/`, `/payments`, `/targets`...), Operations and the
Inbox. Phase 2 replaces them with one frame:

1. **One sidebar** listing the departments a person holds — Today, Inbox,
   Operations, Affiliates — with Settings at the bottom. The department you are
   in shows its sections; the others stay folded and show a number only when
   something in them waits for you. The switch under the logo goes.
2. **Department addresses.** Affiliates' screens move under `/affiliates/…`
   (`/payments` becomes `/affiliates/payments`). Every old address keeps
   working by sending you to the new one, including links in emails already
   sent. Models' portal does not change at all.
3. **Today**, the start page for anyone who holds two or more departments:
   what waits for you in each, broken things first, then what has waited
   longest, each with one button to where it is done. Someone who holds one
   department skips it and lands in theirs.
4. **Settings in four parts:** Me (theme, two-step sign-in, devices) for every
   member of staff, and Team and access, Integrations and Company for the
   owner.
5. **Team and access by department:** each person's access shown as a level
   per department, with a sentence saying in words what it gives them.
6. **On a phone**, a top bar with a menu button that opens the same list full
   screen, instead of today's row of section names scrolling sideways.

The screens inside each department do not change; only the frame around them.

**Rough size: about three weeks**, in five batches.

## Not in Phase 2 (the roadmap puts them in Phase 3)

The approved mockup also draws **search** (frames 4 and 7), **one page per
order** (frames 3 and 7) and Today's **Opened recently** panel. The roadmap
(`hba-os-roadmap.md`, Batch 3.1) puts search and the order page in Phase 3,
because both need a read from every department, gated department by
department (ADR 0068, Consequences). *Opened recently* goes with them: most of
its entries open an order or a customer. Phase 2 leaves room for all three
and draws none of them half-built (*Choices*, 1).

## Before anything

- **No other branch is open** (handoff, 28 October), so the frontend can be
  rearranged now without conflicting with anyone (Batch 2.0).
- **Drive C: is full.** Every command runs with `TMP`/`TEMP` at
  `D:/claude-tmp` and writes output to files on D:.
- The owner answers the *Choices* below. Batches 2.0 and 2.1 need only
  choices 1, 2, 7 and 11; the others can be answered while those are built.

## Order, and why

| Batch | What | Can start | Rough size |
|---|---|---|---|
| 2.0 | Frontend department folders (moves only) | On the owner's word | 1 day |
| 2.1 | The frame: departments declared once, sidebar, phone layout, addresses and redirects | After 2.0 | 5–6 days |
| 2.2 | Today, and the sidebar's numbers from the same source | After 2.1 | 4–5 days |
| 2.3 | Settings split: Me, Integrations, Company; department settings move into their departments | After 2.1 (beside 2.2 if the owner wants speed) | 3–4 days |
| 2.4 | Team and access by department | After 2.3 | 4–5 days |

- **Folders first**, while nothing else is open: every later batch then
  writes its files where they will stay, and the move is proven on its own
  (Phase 1 did the same for the backend in Batch 1.4).
- **The frame before Today**, because Today is a screen inside the frame.
  Until 2.2 lands, someone holding several departments starts where they start
  now (the owner on Affiliates → Overview, the operations manager on Shopify),
  so 2.1 can ship alone without a start page that does not exist yet.
- **The phone layout is inside 2.1**, not after it: the frame replaces
  today's phone layout, so it cannot ship desktop-only.
- **Settings before Team and access**, because the Team page sits inside the
  new Settings and reuses its parts (two-step, devices).

## How every batch is worked

- Branch `claude/phase-2-<batch>` from `main`, one pull request per batch.
- **Subagents as the handoff describes:** the API contract written first;
  backend (Opus, high effort) and frontend (Sonnet, medium) built in parallel
  where a batch has both; **an independent Opus review before the pull
  request**, every finding above Low fixed, the reasoning in the PR.
- New backend code in its department's folder; other departments reached only
  through `public.py`; `lint-imports` passes before pushing.
- Backend tests only through `bash docs/repair/batch-1/run-suite.sh` on a
  disposable database; frontend `npm test` and `npm run build`.
- **Visual comparison against the mockup at 390 and 1280:** the mockup served
  with `python -m http.server 8899` from `docs/design`, each frame's
  `.screen--1280` / `.screen--390` element captured (not the review page
  around it), the app captured at the same widths with the harness in
  `docs/repair/batch-2/visual/` on a throwaway database, then `compare.mjs`.
  Captures are named for the width used. Each role in the mockup's *View as*
  (owner, operations manager, customer service, affiliate manager) is compared
  against the same person in the app.
- **Order of permissions:** the pull request waits for the owner's word to
  merge. Merging deploys staging (`main` deploys staging), so the real-browser
  check on staging comes after the merge, with `playwright-cli` (session
  `hbacheck`), the owner typing passwords, writes only on staging test
  records. Then the owner's separate word to deploy to production, and the
  same check there, read-only.
- At the end of each batch: the roadmap's row updated; at the end of Phase 2,
  the continuation handoff replaced.

---

## Batch 2.0 — Frontend department folders (moves only)

**What changes:** files move, nothing else.

| Folder | What moves into it |
|---|---|
| `frontend/src/frame/` | The new frame's parts (empty until 2.1) |
| `frontend/src/departments/inbox/` | `InboxChats`, `InboxConfirmations`, `Chat*`, `InboxIcon`, `InboxLayout`, `Inbox.css` |
| `frontend/src/departments/operations/` | The `Operations*` screens and `OperationsDashboard.css` (which the Inbox's screens also import: see 2.1). `OpsSource` (Inbox and Operations) stays in `components/`, and so do `IntegrationKey`, `ShopifyConnection` and `InboxConnection`, which Settings uses and Integrations (2.3) will |
| `frontend/src/departments/affiliates/` | Overview, Affiliates, AffiliateDetail, Compensation, Payments and Payment*, Payroll*, Targets, Products, Orders, InvitePage, PortalPreview, Bonuses, Corrections, the money and month components they alone use |
| `frontend/src/portal/` | The model portal (`AffiliatePortal`, `My*`, `AffiliateLayout`, `Apply`, `ApplicationPending`, `PortalSkeleton`...) — moved, not changed |
| `frontend/src/screens/` | What belongs to nobody in particular: sign-in, first run, invitations, password reset, two-step, Settings, Glossary |

A component two departments use stays in `frontend/src/components/`.
Tests move with the files they test.

*As done (PR review, 30 October):* one deliberate exception, `HistoricalReview`,
moved to Affiliates although only Settings imports it, because 2.3 moves it
into Affiliates anyway. Three crossings left for 2.1 to tidy: the Inbox
imports `OperationsDashboard.css` (its shared rules go to a shared
stylesheet), Settings and `DataPanel` import two Affiliates stylesheets
(settled by 2.3), and `AffiliatePayout` imports `instapayProblem` from the
portal's `Apply` (moves to `lib/`).

**Done when** `npm test` and `npm run build` pass, the diff is only moves and
import lines, and every screen is unchanged. *As done:* the built bundle came
out byte-identical to `main`'s (every file under `app/web`, same SHA-256), which
proves every screen unchanged more strongly than captures would, so the
harness was not run for this batch.

**Risk:** small. A wrong import fails the build, which is the gate.

---

## Batch 2.1 — The frame

### 2.1.1 Departments declared once

`frontend/src/departments/<name>/department.ts`, one per department, and one
list that reads them. Each says:

- its name and icon, and **what a person must hold** to have it, as a
  permission (`inbox.use`, `order_ops.view`, `affiliates.view`), never a
  role's name (ADR 0067, decision 9);
- its address (`/inbox`, `/operations`, `/affiliates`) and its first section;
- its sections in the mockup's order, each with its address and, where one
  exists, the number beside it;
- its routes;
- its old addresses and where each now goes.

Settings is declared the same way, its sections gated by permission.

`App.tsx` stops choosing between three route trees: signed-in staff get one
tree built from the list; the person's departments are those whose permission
they hold. `deskFor` shrinks to "portal or staff". The portal, first run,
two-step set-up and the preview frame are decided before the router exactly as
now.

### 2.1.2 The frame's parts

One `Shell` made of parts — `Shell.Sidebar`, `Shell.Head`, `Shell.Main`, and a
full-width part for Chats — replacing `SideShell`'s `flush` and `immersive`
flags (ADR 0068). `Layout`, `SideShell`, `OperationsLayout`, `InboxLayout`'s
frame and `DashboardSwitch` are deleted; the Inbox keeps its unread reading and
its outlet context.

The sidebar as the mockup draws it, 216 pixels wide as now (so the Inbox's
three columns keep their width):

- the brand: the HBA mark, **HBA**, and under it the department you are in
  (today it says "Admin" and "hbawear.store");
- the departments you hold, in the order Today, Inbox, Operations, Affiliates;
  the one you are in open with its sections; the others folded, with a number
  or a red dot only when something waits; clicking a folded one opens it in
  place, as the mockup's does, without leaving the screen;
- Settings at the bottom;
- the account: initials, name, the role words, and a menu with *Sign out*.
  The theme moves from the account menu to Settings → Me (2.3); until then it
  stays in the menu so nobody loses it.

Numbers in 2.1 come from where they come from now: the Inbox's unread count,
*Models* (applications waiting) and *Payments* (waiting for approval) from
`/api/operations/counts`, and a red dot on Operations and on the failing
section when a source's last read failed (Operations' freshness, already
read). 2.2 moves them all to one source.

### 2.1.3 The phone layout

Below 800 pixels, as frame 7 draws it: a top bar with a menu button, the
screen's title, and (from Phase 3) search; the menu opens full screen with the
same list and a close button. An open chat keeps taking the whole display, as
now.

### 2.1.4 Addresses and redirects

| Old | New |
|---|---|
| `/` (Affiliates Home) | `/affiliates/overview` for people with Affiliates; `/` itself sends each person to their start (below) |
| `/affiliates` (Models) | `/affiliates/models` — `/affiliates` itself opens the department on Overview |
| `/affiliates/invite` | `/affiliates/models/invite` |
| `/affiliates/:id` and everything under it | `/affiliates/models/:id/…` (only numbers are read as an id) |
| `/products`, `/products/:id` | `/affiliates/products`, `/affiliates/products/:id` |
| `/targets` | `/affiliates/targets` |
| `/payments` and everything under it | `/affiliates/payments/…` |
| `/payroll`, `/payroll/:month/approve` | `/affiliates/payroll/…` (off the sidebar, as now) |
| `/orders`, `/orders/:id` | `/affiliates/orders/…` (off the sidebar, as now) — frees `/orders` for Phase 3's order page |
| `/settings?section=…` | `/settings` until 2.3 splits it |
| `/operations/…`, `/inbox/…` | Unchanged |

- **Where each person starts:** two or more departments → Today (from 2.2;
  until then, their first department as today); one department → that
  department's first section (customer service → Chats, the affiliate and
  content managers → Affiliates → Overview, an operations manager without the
  Inbox → Shopify).
- **The redirects are permanent** and keep the rest of the address (a
  payment's month and model) and its query.
- **Models are untouched.** `/payments` and `/targets` are also the portal's
  addresses, and emails to models link to them; the portal is decided before
  the staff routes, so a model following an old email still lands in her
  portal. A test covers both.
- **The preview frame** (`/affiliates/:id/portal/frame`, ADR 0064): its
  address moves with the model's, and `app/main.py`'s `_PREVIEW_FRAME`
  pattern accepts both, with a test, so the frame is never refused.
- **Emails sent from now on** use the new addresses
  (`app/shared/services/notifications.py`: a new application links to
  `/affiliates/models`; the staff email about a changed payout to
  `/affiliates/payments`). Emails to models keep their portal links.
- About 80 links inside the staff screens change to the new addresses;
  links in the portal's screens do not.

**Done when**
- Tests: each person's departments and start from their permissions (owner,
  operations manager with and without the Inbox, customer service, affiliate
  manager, content manager); every row of the table above redirects with its
  ids and query; a model at `/payments` and `/targets` stays in her portal; an
  address a person does not hold refuses them inside the frame ("not here");
  the preview frame's header on both addresses.
- `npm test`, `npm run build`, the backend suite (one file changes), and
  `lint-imports` pass.
- **Visual:** frame 2 (Operations inside the frame) and frame 8 (the new
  sidebar) at 1280, frame 7's open menu at 390, for each *View as* role. The
  approved Operations and Inbox screens are re-captured inside the frame and
  compared with their own approved mockups
  (`docs/design/operations-dashboard-2026-10-03.html`,
  `docs/design/whatsapp-inbox-2026-10-11.html`): only the frame may differ.
- On staging after the merge: every department opened, old bookmarks
  followed, a phone-width pass, as the owner and the test affiliate manager.

**Risks**
- *A missed link* goes to an old address: the redirect still lands it, and
  the test that walks every `to=` in the staff screens catches it.
- *React Router cannot tell `/affiliates/overview` from an old
  `/affiliates/:id`* by pattern alone: the old-id redirect is a component that
  accepts digits only and otherwise shows "not here".
- *The Inbox's full-width Chats and open chat on a phone* are the parts most
  likely to break; they are compared against the Inbox mockup at 390 and 1280.

---

## Batch 2.2 — Today

### Backend

- Each department gets `today.py` in its folder, offered through its
  `public.py`: given the person, it returns what waits for them in that
  department — what, a line of detail, since when, whether it is broken, and
  where to go. Only for a person who holds the department, and computed by the
  **same functions the department's own screens use**, so Today and the screen
  can never disagree.
- `GET /api/today` (in `app/shared/api/`, reaching departments only through
  `public`): every department's items for this person, broken first, then the
  longest waiting; and the numbers for the sidebar, from the same items.
  Today's import line is added to the import check as a contract of its own.
- **What each department says today** (from the mockup, limited to what the
  platform already knows):

| Department | Items |
|---|---|
| Operations | A source that could not be read (Bosta, Shopify, E-stebdal) and since when — **broken**; confirmed orders that never reached Bosta |
| Inbox | Customers waiting for a reply and the oldest; WhatsApp not working — **broken** |
| Affiliates | Applications to review; next month's targets not set, from the 24th; payments waiting for approval (for whoever approves) |

  The mockup's "customers asked to change their order" has no record behind
  it today, so it is not shown (*Choices*, 8).

- **Orders, last 7 days** (for people holding the Inbox and Operations): the
  week's orders by where they are — waiting for an answer, confirmed and not
  with Bosta, with Bosta, delivered, cancelled or returned — from the order
  index and the existing Operations and Inbox records. The five must add up to
  the number placed, checked in a test, as the mockup checks it.

### Frontend

Frame 1 at 1280 (Waiting for you on the left; Orders, last 7 days on the
right) and frame 7's Today at 390. "Updated … ago" as the other screens say
it. The sidebar's numbers switch to `/api/today`, read again every 30 seconds
as the Inbox's count is now.

**Done when**
- Tests: each department's items for each kind of person, and nothing for a
  person who does not hold it (customer service sees no Affiliates item, the
  affiliate manager no Inbox item); the order of items; the week's figures
  adding up; Today and each department's own screen giving the same number.
- **Visual:** frame 1 at 1280 and frame 7 (Today) at 390, for the owner and the
  operations manager; customer service and the affiliate manager land in their
  department.
- On staging: the owner and the operations manager start on Today and every
  button lands where the thing is done.

**Risks**
- *A number on Today that disagrees with the screen it opens* — prevented by
  sharing the function, proven by the test that compares them.
- *The cost of reading every department every 30 seconds* — measured on the
  restored production copy before the pull request; each item is a count, not
  a list.

---

## Batch 2.3 — Settings split

Settings becomes four addresses, as the mockup's sidebar draws them:

| Section | Who | What |
|---|---|---|
| `/settings/me` | Every member of staff | Theme, two-step sign-in, *Signed in on*, email preferences. The operations manager and customer service, who have no Settings today, gain this |
| `/settings/team` | Owner | Batch 2.4; until then today's Team section |
| `/settings/integrations` | Owner | Frame 6: every connection, which departments rely on it, whether it works now, when it was last read, and its key |
| `/settings/company` | Owner | Pay policy, go-live month, the whole activity log |

**Where today's Settings sections go** (*Choices*, 3):

| Today | Goes to |
|---|---|
| Team | Settings → Team and access |
| Shopify and sync | Settings → Integrations (the read-only version others see today goes; Today shows a broken Shopify instead) |
| Historical setup | Affiliates, linked from Payments while months are open; off the sidebar |
| Brand codes | Affiliates, linked from Models; off the sidebar |
| Pay policy | Settings → Company |
| Activity log | Settings → Company for the owner (everything); for others who may read it, their own department's entries only (ADR 0067, decision 7), linked from their department |
| My preferences | Settings → Me |

- **Integrations backend:** `GET /api/integrations` (owner only) built from
  what each department already knows: Shopify's sync state, Bosta's and
  E-stebdal's freshness, the WhatsApp connection, the last email sent or
  failed, and whether file storage answers. Where the platform cannot know a
  figure, the row leaves it out rather than invent it. The key forms are the
  existing components; the Operations screens keep theirs as their approved
  mockup draws them (*Choices*, 10).
- **The activity log by department:** `/api/audit` filters by the reader's
  departments (entries already carry a department since Batch 1.2); entries
  with none stay the owner's. This narrows what the affiliate and content
  managers read today, as ADR 0067 decided.
- Old `/settings?section=…` links redirect to the new home of each section.

**Done when**
- Tests: who sees each section and each route refused otherwise; the
  activity filter for each department and for entries with none; the
  integrations answer for a working and a failed source; every old section
  link.
- **Visual:** frame 6 (Integrations) at 1280 and 390. Settings → Me and
  Company have no frame of their own: they use the mockup's panels and type,
  and are shown to the owner in screenshots before the PR.
- On staging: the owner opens all four; the test affiliate manager sees Me
  only and finds Brand codes, Historical setup and their activity inside
  Affiliates.

**Risks**
- *Somebody loses a page they use:* the table above is the full list of what
  moves, each with a test that the person who used it can still reach it.
- *The activity filter shows too much:* a test per department per level.

---

## Batch 2.4 — Team and access by department

Frame 5, for the owner:

- **The people list:** each person, the words for their access ("Operations
  manager · Inbox staff"), a lock where two-step sign-in is on, and invitations
  not yet accepted, grouped below.
- **A person's page:** a row per department with the levels No access,
  Viewer, Staff, Manager; under them, **What this gives** in a sentence, built
  from the permissions their levels grant and checked in a test against the
  server's own list. Two-step sign-in (with *Send a reminder*), *Signed in on*
  with *Sign out of every device*, and *Suspend* — all of which exist since
  Batch 1.3 and move onto this page.
- **Invite someone** chooses a department and a level instead of a role.
- **Underneath, nothing about how access is stored changes:** a level is one
  of today's roles, given and taken with the existing *add a role* / *remove a
  role* actions and their rules (nobody changes their own access, the last
  owner stays, one operations manager at a time, nobody grants what they do
  not hold). The words change: admin → Owner, operations manager → Operations
  manager, customer service → Inbox staff, affiliate manager → Affiliates
  manager, content manager → Affiliates staff (*Choices*, 5 and 6).
- A level that does not exist yet is drawn but cannot be chosen, with a
  line saying so (*Choices*, 5).

**Done when**
- Tests: each level maps to exactly the role it names and back; choosing a
  level adds and removes the right roles, audited; every existing rule still
  refuses; *What this gives* for every level matches the permissions the
  server grants; an invitation by level grants the same as by role.
- **Visual:** frame 5 at 1280 and at 390.
- On staging: the owner gives the test account a level and takes it back, and
  the test account sees its sidebar change after signing in again.

**Risks:** this page changes who can do what, so it gets the security
review the handoff asks for (an independent Opus review of the access rules
in particular), and is checked on staging only with the test account.

---

## Choices: where the mockup and the app disagree

Each with a recommendation. Nothing departing from the mockup is built until
the owner chooses.

1. **Search in the sidebar before search exists.** The mockup puts *Search
   Ctrl K* at the top of the sidebar and a search button in the phone bar;
   search itself is Phase 3. *Recommended:* leave both out until Phase 3
   brings search, rather than a box that finds nothing.
2. **Production, Finance and People as "Planned" rows.** The mockup shows them
   to the owner in the sidebar and in Team and access, to show where they fit.
   *Recommended:* leave them out until each is built; a row that opens nothing
   is a question the owner has to answer every day.
3. **Where today's Settings sections go.** The mockup gives everyone but the
   owner only Settings → Me, and Affiliates five sections that do not include
   Brand codes, Historical setup or the activity log, which the affiliate and
   content managers use today. *Recommended:* the table in 2.3 — they move into
   Affiliates as pages off the sidebar (as Payroll and Orders already are),
   so the sidebar stays as drawn and nobody loses a page.
4. **Inviting staff.** Today the affiliate manager may invite a content
   manager (Settings → Team, invitations only). The mockup gives Team and
   access to the owner alone. *Recommended:* follow the mockup — staff
   invitations become the owner's; inviting **models** is unchanged
   (Affiliates → Models → Invite).
5. **Four levels in every department, when few exist.** Today's permissions
   give each department one or two real levels: Inbox staff; Operations
   manager; Affiliates manager and content manager. An Inbox viewer (reading
   without replying) or an Affiliates viewer ("no pay figures") need new
   permissions and checks that every screen hides pay. *Recommended:* draw all
   four, make the levels that exist choosable, show the rest as "Not offered
   yet", and add a level (with its own ADR line and tests) when someone needs
   it. If the owner wants the mockup's Affiliates viewer now, it is added to
   2.4 with a check of every Affiliates answer for pay figures.
6. **Renaming roles.** ADR 0067 renames today's roles. *Recommended:* change
   the words shown, not the names stored, so invitations, the audit trail and
   the database's rules are untouched. Content manager is shown as *Affiliates
   staff*, which is what the mockup's levels need (ADR 0067 had kept it as
   *Affiliates content manager*; the mockup wins).
7. **The operations manager's start.** Today he lands on Shopify. Holding
   Inbox and Operations, the mockup's rule puts him on Today. *Recommended:*
   follow the mockup. Likewise the owner starts on Today instead of
   Affiliates Home.
8. **Today's rows without a source.** "Customers asked to change their order"
   has no record behind it, and *Opened recently* mostly opens order pages,
   which come in Phase 3. *Recommended:* Today shows what departments can
   compute now (2.2's table); *Opened recently* comes with Phase 3.
9. **Integrations' Email and File storage rows.** The mockup gives storage
   "2.1 GB stored" and email "last sent". *Recommended:* show what the
   platform can read without new outside calls (last email sent or failed;
   whether storage answers) and leave out a figure it cannot read.
10. **Where keys are changed.** The mockup puts *Replace key* on
    Integrations; the Operations screens have their key forms today.
    *Recommended:* both, the same component — Integrations for the owner, and
    the Operations screens unchanged, since their approved mockup stands.
11. **Frontend folders first (Batch 2.0).** Not in the mockup; promised by
    the Phase 1 plan. *Recommended:* yes, now, while no other branch is open.

## Decisions already made, not to reopen

- One frame, one sidebar, the department order, Today's name, the Settings
  split, the phone menu, the model portal untouched (ADR 0068, the approved
  mockup).
- Several roles per person, levels by department, permissions never role
  names (ADR 0067); the server checks every request, the sidebar only hides
  what the server already refuses.
- Search, the order page and *Opened recently* are Phase 3 (roadmap).
- No merge and no deploy without the owner's word for each (`CLAUDE.md`).
