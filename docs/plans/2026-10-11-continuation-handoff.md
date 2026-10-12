# Where the work is — 12 October 2026 (the Inbox's backend and screens are built, on the branch only)

Supersedes the 11 October evening version of this file; its open items are
carried under *Remaining*.

## The exact position

Re-read the remote before describing it (`git ls-remote --heads origin main production`).

| | |
|---|---|
| **Branch** | `feature/whatsapp-inbox`, cut from `repair/batch-2`. Code at `5ea7d0d`; a later commit carrying this file and the plan may be ahead. **Not pushed since `9834aec`**: the commits of 12 October for phase 4 are local only. |
| **Staging and production** | `origin/main` (staging) and `origin/production` are both on `6533260`, unchanged since 11 October. They have the inbox's phases 0 to 2 and nothing of phases 3 and 4. |
| **Migration head** | `c2e5a8b30014` on staging and production. The branch adds `d3f6b9c40015` (a confirmation can be "sending"), which runs at the first deploy of phase 3. |
| **Production config** | `INBOX_CONFIRMATIONS_ENABLED=true`. `INBOX_SEND_TO_CUSTOMERS` is **not** set anywhere, and must not be until the switch-over. `SETTINGS_ENCRYPTION_KEY` and the media bucket variables are set on both. |
| **Staging config** | No inbox switch is set: the engine is off there, so staging holds no customer data. |
| **Backend** | whole suite through `run-suite.sh`, 111/111 files, at `5ea7d0d`. |
| **Frontend** | `npm test` 46 files / 765 tests and `npm run build`, at `5ea7d0d`. |

## What was built since the last handoff

All on the branch. **n8n is still the thing that messages customers. Nothing
about what a customer receives has changed, and nothing built here is deployed.**

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

Phase 4 was looked at in a real browser on a local copy with a throwaway
database. It has **not** been tried on staging, and has not met real WhatsApp,
real Shopify tag writes or the real bucket.

## Remaining, in order

1. **The owner looks at the Inbox.** The quickest way is the branch on
   staging, which is his to order. That deploy runs migration
   `d3f6b9c40015`. To try it there he would then: type the WhatsApp keys and
   the second Shopify app into Settings → Shopify; set `INBOX_TEST_NUMBERS`
   on the staging service to the phones to test with; invite a
   customer-service test account. Staging can message only those test
   numbers.
2. **His choices from phase 4** (the plan's *Still open*): the filled green
   buttons in the dark theme; whether the payment method and the items
   belong beside a chat; searching inside one chat; the wording of new
   approved messages.
3. **What phase 4 still owes**: the harness's captured comparison against the
   mockup; the flows on staging; a real screen reader; a kept photo or voice
   note seen on screen.
4. **What phase 3 still owes**: an independent security review of the
   callback receiver and the media endpoint; meeting the real thing (phase 6).
5. **The seven-day comparison (inbox phase 2).** From 12 October, compare
   production's `order_confirmation` with n8n's `wa_sends`, daily, with
   `python -m app.services.inbox.shadow` (see its docstring). n8n's database
   is read through `railway ssh` into the `Postgres` service of the
   `order-confirmation-message` project, read-only, order ids only. Every
   difference needs a written reason; the plan lists the expected ones.
6. **Inbox phase 5**, importing the old chats, then phase 6 on staging.
7. **From the owner, for the inbox:** October's charges in WhatsApp Manager;
   who owns the Meta business account, app and number; the WhatsApp keys and
   the second Shopify app's credentials, typed into Settings when wanted.
8. **Owner acceptance of Operations, on production**: Shopify cards against
   Shopify admin; E-stebdal *Needs review* against its list; Bosta B5 against
   *Awaiting your action*, spot-check B1, B2, B6; one Bosta and one E-stebdal
   link (both addresses are assumed); sign in as the operations manager.
9. **Release gates**, open and behind production: reconciliation against a
   restored copy, the `SETTINGS_ENCRYPTION_KEY` cases, and `a6b1c4e20006` on a
   restored copy. The inbox migrations, now three, are part of what a rollback
   rehearsal has to cover. A restored copy of production contains customer
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
- **Do not invite a customer-service account on production yet.** Its screens
  exist on the branch only; on production it would still sign in to a shell
  that refuses it everything.
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
