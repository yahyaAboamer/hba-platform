# 0068. One frame for every department

**Status:** Accepted — owner, 25 October 2026, with the mockup `docs/design/hba-os-shell-2026-10-25.html`. **Not built yet.**
**Date:** 2026-10-25
**Builds on:** ADR 0065, ADR 0066, ADR 0067. **Amends:** ADR 0057 and ADR 0059, which gave Operations and the Inbox shells of their own (their screens stand; their frames give way to this one). **Excepts:** Production, by ADR 0069.

## Context

The staff side is three dashboards stitched together:

- Three frames: the affiliate side's `Layout`, and the `SideShell` that
  `OperationsLayout` and `InboxLayout` share, joined by a switch under the logo
  (`DashboardSwitch`) that shows only the dashboards a person holds.
- `frontend/src/App.tsx` picks a whole tree of routes by the role's name. Each
  new role or department means another branch there.
- The affiliate side owns the general addresses: `/` is its Home, and
  `/payments`, `/payroll`, `/orders`, `/products` and `/targets` are all about
  models. Finance will need "payments" and People will need "payroll".
- Nothing shows one order whole, although every department holds part of it
  (ADR 0066), and there is no search across departments.

Adding Production, Finance and People the same way would make five dashboards
and a five-way switch.

## Decision

**One frame for every department, as drawn in the approved mockup.**

- **One sidebar** lists the departments a person holds, in this order: Today,
  Inbox, Operations, Affiliates, Production, Finance, People, with Settings at
  the bottom. Only the department a person is in shows its sections; the
  others stay folded and show a count only when something in them waits for
  that person.
- **Each person sees only the departments they hold** (ADR 0067). Someone who
  holds one department skips Today and lands in it, as customer service lands
  on Chats today.
- **Today** is the start page for anyone holding two or more departments. Each
  department contributes what waits for that person; broken things come
  first, then what has waited longest; each item opens where it is done.
  It is called Today, not Home, because the affiliate side and the model
  portal already have screens called Home. The affiliate side's Home becomes
  Affiliates → Overview.
- **Search** sits at the top of the sidebar and opens with Ctrl K. It finds
  customers, orders, models and products, and returns only what the person
  may see: someone without the Inbox cannot find a customer by name.
- **Every order has one page**, reached from any department and found by
  Shopify's order id. Its path runs across the top, naming the department that
  holds each step; each section below belongs to one department and shows only
  to people who hold it. The customer's name and phone still show only to
  Inbox holders (ADR 0059).
- **Department screens keep their names and look.** Their addresses move under
  the department (`/affiliates/payments`, `/operations/shopify`), and **every
  old address redirects**, including those in emails already sent
  (`app/services/notifications.py` links to `/targets` and `/payments`). New
  departments use different words where a name would repeat (Salaries, Bills).
- **Settings splits** into Me (theme, two-step sign-in, devices), Team and
  access (ADR 0067), Integrations (every outside connection and whether it is
  working) and Company. Only the owner sees the last three.
- **On a phone**, the sidebar becomes a top bar and a full-screen menu.
- **The model portal is not part of this frame** and does not change.
- **How it is built:** each department declares itself once (name, icon, what
  a person must hold, its sections, what it adds to Today and to search), and
  the sidebar, Today, search and the address rules are built from that list.
  It replaces the role branches in `App.tsx` and the `DashboardSwitch`. The
  frame is one component made of parts, replacing `SideShell`'s `flush` and
  `immersive` flags with parts of their own.

## Consequences

- Every staff address changes. The redirects are permanent, because emails
  and bookmarks outlive any migration window.
- Today and search are new work in every department: each must say what waits
  and what can be found, filtered by what the reader may see. A search that
  returned a customer to someone without the Inbox would break ADR 0059, so
  each department's search is tested against each level.
- The order page needs a read from every department that holds part of an
  order, joined by Shopify's order id, with each section gated separately.
- Operations' and the Inbox's approved mockups keep governing their screens;
  only the frame around them changes. The parity checks for those screens
  re-run inside the new frame.
- Production, Finance and People appear in the mockup only to show where they
  fit. Each gets its own decision when its turn comes, and Production's look is
  settled differently (ADR 0069).

## Alternatives considered

- **Keep separate dashboards with a switch** (today). Grows a switch option per
  department, and moving between departments means changing app.
- **A narrow strip of department icons with a second column for sections.**
  Takes about 64 pixels that the Inbox's three columns need, and icons without
  names make people guess. Kept as an option only for framing Production,
  which has a sidebar of its own (ADR 0069).
- **A separate app per department.** Separate sign-ins and no order page,
  Today or search across them; ruled out with ADR 0065.
