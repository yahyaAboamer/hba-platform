# Where the work is — 15 October 2026 (gifts to unknown numbers and hand-assigned products are live; the Inbox is on staging and production)

Supersedes the earlier 12 October version of this file; its open items are
carried under *Remaining*.

## The exact position

Re-read the remote before describing it (`git ls-remote --heads origin main production`).

| | |
|---|---|
| **Branch** | `feature/whatsapp-inbox`, pushed. Code at `fdcbd73` (ADR 0060 and 0061); the commit carrying this file is ahead of it. |
| **Staging and production** | `origin/main` and `origin/production` both on `fdcbd73`, deployed 15 October on the owner's order (fast-forwards from `aae38ee`). Both built, ran migration `e4a7c1d50016` and answered `/api/health/ready` 200. |
| **Migration head** | `e4a7c1d50016` on staging and production (rehearsed down and up on a throwaway database). |
| **Production config** | `INBOX_CONFIRMATIONS_ENABLED=true`. `INBOX_SEND_TO_CUSTOMERS` is **not** set, per the previous handoff (a cloud session may not read the variables), and must not be until the switch-over. No WhatsApp keys are typed into Settings there, so nothing can be sent. `SETTINGS_ENCRYPTION_KEY` and the media bucket variables are set. |
| **Staging config** | No inbox switch is set: the engine is off there. |
| **Backend** | whole suite through `run-suite.sh`, 114/114 files, on the `fdcbd73` tree before commit. |
| **Frontend** | `npm test` 48 files / 781 tests and `npm run build`, on the `fdcbd73` tree. |

**n8n is still the only thing that messages customers.** Deploying phases 3
and 4 changed nothing a customer receives.

## 15 October: gifts that reached no model, and products assigned by hand

The owner found models' products missing after *Read the catalogue* and
*Match parcels*. Cause: a parcel matches a model only by the phone on it, and
HBA ships many gifts (code `sponsordis`, zero price) to a number that is not
on her profile; those were filed as customers and shown nowhere.

- **ADR 0060**: Settings → Shopify and sync → *Needs attention* lists free
  orders with a discount code that matched nobody. *Attach* gives the parcel,
  and every parcel to its number, to the chosen model, and remembers the number
  (`match_reason = 'assigned'`). *Not a model* drops it from the list.
  `+20 010…` is now read as an Egyptian mobile.
- **ADR 0061**: a product's *Model coverage* has *Assign manually*, for pieces
  collected from the warehouse with no order. New table `manual_wardrobe_item`.
- **Production data, 15 October, on the owner's word**: 13 gift orders attached
  through `assign_gift` (audited under the owner's account): Mahmoud
  eldahshan 6 (number …882), MOHAMED FAYTOURY 2 (…190), Mohamed Hany 1 (…054),
  Mohamed ahmed 4 (…413). Their products were read; the wardrobes filled.
- **Left for the owner to do on the new screen**: the other ~32 unlinked gifts
  (Ziad Ahmed …442 and Ziad C/G …546 may be Ziad Mohamed; the rest look like
  people not on the roster), and hand assignments. Ahmad Radwan has no gift
  order at all; Anas ouijjane's phone is not an Egyptian mobile.
- Not clicked through on staging or production in a browser (Jev did not
  connect); checked locally in the browser pane, and on staging the gift list
  was read against real Shopify data from inside the container.

## What was built before 15 October

Deployed to staging and production on 12 October. **n8n is still the thing
that messages customers. Nothing about what a customer receives has changed.**

The plan, with an "as built" section per phase, is
`docs/plans/2026-10-11-whatsapp-inbox-and-order-confirmation.md`. In short:

- **Phase 3, the backend** (11 to 12 October): Meta's callback receiver;
  sending the confirmation, the two automatic replies and the order's tag;
  what the chat screens read and what staff do from them; a chat's files,
  copied to the bucket and served through the server.
- **Phase 4, the screens** (12 October), from the approved mockup
  `docs/design/whatsapp-inbox-2026-10-11.html`: the Inbox shell and who lands
  where; Operations → WhatsApp; Inbox → Confirmations; Inbox → Chats with the
  open chat and the order beside it; the composer with files, voice notes and
  the approved messages; two lines on the Settings WhatsApp card.

- **The owner's phase 4 choices** (12 October, `4f939f5`): search inside one
  chat, built; the dark theme's filled green darkened slightly
  (`--accent-fill`); payment method and items left in Shopify.

Phase 4 was looked at in a real browser on a local copy with a throwaway
database. On staging it is deployed but nobody has clicked through it: the
cloud session that deployed has no Jev password origin and the staging
address is outside its network. It has not met real WhatsApp, real Shopify
tag writes or the real bucket.

**Superseded on 12 October, 13:35 UTC (`b121508`): the owner dropped phase 6
on staging and the rest of the seven-day comparison, and goes straight to the
switch-over.** The plan's section *The owner's change of course* says what
that gives up and what stands in for it. The list below is rewritten to
match. `origin/main` and `origin/production` were on `aae38ee` on 14 October,
which carries the importer (`f9fdde3`); that Railway deployed it cleanly was
not checked.

## Remaining, in order

1. **Inbox phase 7, the switch-over** (the plan's *Phase 7*). Needs the
   owner's explicit go-ahead, and these first:
   - the WhatsApp keys and the second Shopify app's credentials typed into
     Settings → Shopify **on production** (none were on 12 October);
   - who owns the Meta business account, app and number, so the callback
     address can be changed;
   - a quiet hour, and whoever answers customers told.

   Then: run the import on production (`app/services/inbox/importer.py`,
   `--dry-run`, for real, then `--check`; n8n's address in
   `N8N_DATABASE_URL`, never written down) — it no longer waits for
   19 October; turn off n8n's sending and tagging workflows, leaving n8n
   running; point Meta's callback at the platform; switch sending on and set
   `INBOX_SEND_TO_CUSTOMERS=true` on production; one real order from the
   owner's own phone; Send again for any order n8n did not message; watch
   the health strip and the failed list for the day.
2. **After the import on production**: read twenty chats against n8n's by
   eye (what is left of phase 5).
3. **What phase 4 still owes**: the harness's captured comparison against the
   mockup; a real screen reader; a kept photo or voice note seen on screen.
   Staging is no longer where the flows are first tried; production is, at
   the switch-over.
4. **What phase 3 still owes**: an independent security review of the
   callback receiver and the media endpoint, before the switch-over if it can
   be had.
5. **Phase 8, retiring n8n**, after two clean weeks and only on the owner's
   word. Until then n8n's workflows stay switchable as the way back.
6. **Dropped on the owner's order, 12 October:** phase 6 on staging and the
   rest of the seven-day comparison (it had one day: 6 differences, each
   explained).
7. **From the owner, for the inbox:** October's charges in WhatsApp Manager.
8. **Owner acceptance of Operations, on production**: Shopify cards against
   Shopify admin; E-stebdal *Needs review* against its list; Bosta B5 against
   *Awaiting your action*, spot-check B1, B2, B6; one Bosta and one E-stebdal
   link (both addresses are assumed); sign in as the operations manager.
9. **Release gates**, open and behind production: reconciliation against a
   restored copy, the `SETTINGS_ENCRYPTION_KEY` cases, and `a6b1c4e20006` on a
   restored copy. The inbox migrations, now three, and `e4a7c1d50016`
   (ADR 0061) are part of what a rollback rehearsal has to cover. A restored copy of production contains customer
   phones and first names (`order_confirmation`) and must be handled as
   customer data.
10. **One security point raised and not agreed.** The reset-email limits are
    skipped when the caller's address is unknown (`app/api/auth.py`). On
    Railway the address is known, so it does not bite today. Proposed: count
    those against one shared bucket. The owner has not decided.
11. **Optional, from the database review:** a partial index for
    `ops_bosta_delivery`; a 500 when two operations-manager invitations are
    accepted in the same instant; no foreign key on
    `ops_integration_key.updated_by`.
12. Carried: the shell at 390 (account row under the tabs; the Inbox shares
    it); owner acceptance of the Models tab; the admin sidebar's sideways
    scroll at 390; mapping the flows with real data, then the admin audit tab
    by tab (Payments next). The `feature/operations-dashboard` worktree can go.

## Decisions not to reopen

- ADR 0057, as amended by 0059 now that the screens exist: Operations only
  reads; Bosta never decides pay; one operations manager; no customer details
  shown in Operations. Its fourth tab, WhatsApp, follows the same rules.
- ADR 0059, all owner decisions of 11 October: code inside the platform, not
  n8n; Inbox is its own dashboard with a customer-service role; staff keep
  chatting on the API number and the per-message cost is accepted; old chats
  are imported; the operations manager holds the inbox; Operations gains a
  WhatsApp tab; no automatic reply after Confirm, Edit kept, Cancel reworded.
- The confirmation engine runs on production and not on staging.
- **An order's confirmation is never sent from a chat.** It goes out on its
  own for a new order, and from Confirmations for an order that never got
  it. From a chat only an approved message with nothing to fill in is sent.
- **WhatsApp is "quiet" when a send went unacknowledged for 10 minutes**, not
  when nothing has arrived for a while.
- A tap is believed only from the order's own phone.
- Staging stays: it costs about $5 a month, measured on 11 October.
- A source that fails is a dashboard state, not a failed job.
- A staff member may manage another account only if they hold all of that
  account's access — the same rule as invitations.

## Corrections worth knowing

- **Staging and production both report `APP_ENV=production`.** Nothing may be
  decided from it that should differ between them.
- **A customer-service account on production now lands in the Inbox**, which
  is empty until the import and the switch-over. Invite one there only when
  there is something for it to do.
- **`tests/test_reachability.py` reads the frontend's calls as text.** A route
  is seen only where the call is written out, `` api.get(`/api/inbox/…`) ``. A
  path built into a variable first is not seen, and the test then reports the
  route as having no way in.
- **To look at the Inbox locally**: a throwaway database named
  `hba_browser_inbox` (migrate it, then run
  `docs/repair/batch-2/visual/seed_inbox.py`), the app on the built frontend,
  and the address `http://127.0.0.1:8123`. `localhost` did not work in the
  desktop app's browser pane. A reply typed there is refused with the reason:
  nothing real is connected. Photos cannot be shown locally; there is no
  bucket.
- **This machine's edit gate refuses the first write of every new file, and
  the first edit of every existing one, in each session.** State who calls the
  file and the instruction, then send the same write again.
- A shell command whose text holds an unpaired apostrophe is refused whole,
  heredoc or not. Write such text with the file tools.
- **n8n's "failed" count means nothing**: all 220 are paid orders it never
  meant to message. Its chat page is opened with one shared key in its address,
  and a Shopify secret sits in plain text in its workflows; that secret is to
  be replaced when n8n is retired.
- `run-suite.sh` keys passes on the HEAD commit: commit first, or use a fresh
  `OUT_DIR`, or earlier passes are trusted for code they did not test.
- **Two runs of `run-suite.sh` at once spoil each other**: they share one
  database and one log, and each empties the tables under the other. It
  happened on 12 October, when a second was started while a first ran in the
  background, and both logged failures that were not real. Git Bash's `ps`
  does not show the Python processes; `tasklist` or PowerShell does. Run it in
  the foreground, one at a time.
- `tests/test_reconcile.py` passes on its own, as the runner runs it, and one
  of its tests fails when run in the same process as `tests/test_worker.py`.
- The disposable Postgres container was killed for memory once during a run
  (exit 137). `docker start hba-platform-postgres-1`, then run again.
- Bosta's search wants `stateCodes` as strings; E-stebdal answers a wrong key
  with a 500.
