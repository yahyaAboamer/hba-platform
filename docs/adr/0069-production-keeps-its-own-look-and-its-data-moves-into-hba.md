# 0069. Production keeps its own look, and its data moves into HBA's database

**Status:** Accepted — owner, 25 October 2026. **Not built yet**; waits on the source export from ChatGPT.
**Date:** 2026-10-25
**Builds on:** ADR 0065, ADR 0066, ADR 0067. **Excepts itself from:** ADR 0068's shared look, and RULES.md's single palette (ADR 0039), by the owner's decision.

## Context

Production already runs, as an app ChatGPT built and hosts:
`https://hba-production-os.yahianady.chatgpt.site/`, on the owner's ChatGPT
account. It was inspected read-only on 25 October 2026; nothing was signed in
to or changed.

- **It is a complete app.** Its own sidebar covers a dashboard, production
  orders, drop phases, production tasks, samples, problems, a timeline and a
  calendar; suppliers, products and SKUs, materials, bills of materials and
  route templates; quality control, costing and payments; and a supplier
  portal for outside suppliers.
- **Its look is its own:** dark, a lime-green accent, the Geist typeface, its
  own sidebar and top bar. It shares nothing with HBA's tokens.
- **It is a React front end with a small server of its own**, behind
  Cloudflare. The screens use five addresses: `/api/state`, `/api/actions`,
  `/api/documents`, `/api/session` and `/login`.
- **All its data is one document**, about 114 KB, read whole from `/api/state`
  and carrying a revision timestamp: 43 production orders, 39 products, 27
  samples, 16 suppliers, 18 tasks, 2 phases, 40 activity entries and no
  quality checks yet. No costs are recorded (EGP 0) and no supplier phone
  numbers are filled in.
- **It has its own accounts**: team usernames and passwords, supplier logins
  for the supplier portal, and the owner signing in with ChatGPT. None of them
  is an HBA platform account.
- **Anyone with the link can read all of it without signing in.**
  `/api/state` answers a signed-out request with every order, the suppliers'
  contact names and the staff names in the activity log.

On 25 October 2026 the owner decided Production joins the platform **as it is**:
its functions, screens, colours, themes and behaviour unchanged, knowing that
this departs from one consistent look.

## Decision

1. **Production keeps its own look and behaviour, exactly**: its screens,
   words, colours, typeface, theme and its own navigation. This divergence is
   deliberate. Nobody restyles Production to HBA's tokens, or HBA's screens to
   Production's, without a new ADR.
2. **Its front end comes into this repository unchanged**, from the source
   ChatGPT exports, as its own package with its own build. The platform serves
   it at `/production` on HBA's own domain, kept apart so that neither side's
   styles can reach the other.
3. **Its data moves into HBA's Postgres and belongs to the Production
   department** (ADR 0066). The platform answers the same five requests its
   own server answers today, with the same shapes and the same revision check,
   so the screens cannot tell they moved. To begin with, the workspace is
   stored as the same single document; it is split into tables only when
   another department needs to read it (Today, search, the order page,
   Finance). Every change it saves is also recorded in the platform's
   append-only audit trail (ADR 0008). Uploaded files move into the platform's
   own storage.
4. **Sign-in becomes HBA's.** Staff get Production levels in Team and access
   (ADR 0067). Suppliers get supplier accounts that reach only the work
   assigned to them, by owning it, as models reach their own records. Its own
   sign-in page, and signing in with ChatGPT, go away: **the one visible
   change**, made so each person has one account.
5. **Within the frame (ADR 0068)**, Production is a department in the sidebar.
   Because Production has a full sidebar of its own, how HBA's frame sits
   around it (the recommendation: HBA's sidebar narrows to a strip of
   department icons while Production is open) is drawn as a mockup and
   approved by the owner before it is built.
6. **Until the move is done**, the Production item opens the existing site in
   a new tab. The move is complete when every screen has been checked side by
   side against the live site, the data has been moved and reconciled count by
   count, and every person signs in with an HBA account. The ChatGPT copy is
   then retired. **From then on, Production changes in this repository only**,
   never in ChatGPT.
7. **Before the move**, the owner asks ChatGPT to require sign-in before
   anything can be read, and exports the source code, the data and the
   uploaded files. The export holds people's names, so it is kept outside the
   repository with the other private evidence; only the code comes in, after
   it has been read in full.
8. **Money waits for its own decision.** Production's costing and payments
   hold no figures yet. Before they record any, a separate decision settles how
   they meet the platform's money rules (integer piastres, ADR 0002; the Cairo
   month, ADR 0005) and how they meet Finance. Production's products and
   suppliers likewise stay its own until a later decision joins them to the
   Shopify catalogue and to Finance's suppliers.

## Consequences

- **Two looks in one product.** Staff learn two sets of patterns, and an item
  on Today or a search result that opens Production lands in a different
  style. The owner accepted this knowingly.
- **A second front-end toolchain** is built and kept up to date beside HBA's,
  inside the same deploy. Its versions are pinned as ADR 0016 pins HBA's.
- **Code the team did not write.** ChatGPT's code is read in full before it
  runs here. Its server is replaced, not reused, so its own handling of
  sessions and passwords never runs on the platform.
- **The screens may rely on how its server behaves**, including details its
  author never wrote down (the revision check, what an action returns). The
  side-by-side check against the live site is the gate for exactly that.
- **One document limits sharing.** Until it is split into tables, other
  departments cannot query Production's data, and two people saving at once
  depend on its revision check.
- **The owner can no longer change Production by asking ChatGPT** once it has
  moved; changes become ordinary work in this repository.

## Alternatives considered

- **Show the ChatGPT site inside the platform, permanently.** Identical on
  screen and fast, but the data stays outside the platform's backups, audit
  trail and sign-in; anyone with the link can read it; it depends on one
  personal ChatGPT account; and some browsers (Safari on iPhone among them)
  block signing in to another site shown inside a page. Kept only as the
  interim new-tab link.
- **Rebuild Production in HBA's look.** Rejected by the owner. A later ADR can
  revisit it.
- **Run its original server as a second service beside the platform.** Two
  backends and two account systems; ruled out by ADR 0065.
