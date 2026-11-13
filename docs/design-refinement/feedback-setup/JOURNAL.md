# Feedback setup refinement journal

**Started:** 2026-11-13 · **Branch:** `claude/feedback-messages` (backend half is `5ba4b24`; this is the frontend half, uncommitted)
**Scope:** a new page, Inbox → Feedback → Setup (`/inbox/feedback/setup`); the Feedback card in Settings → Integrations (made short); the Feedback sheet's head (a link to the setup page); a review of the whole Integrations screen.
**Not in scope:** what any other Integrations card does; the Feedback sheet's table, filters and tiles; the backend (read only: `app/modules/inbox/services/feedback_messages.py` and the two `/api/inbox/feedback/messages` routes).
**Evidence:** `design-preview/feedback-setup/` in the worktree (gitignored). Not zipped: the owner has not been shown it yet.

The owner's words (condensed): add a way to edit the WhatsApp feedback messages whenever, to whatever; the frontend is the hard part, so review the current screens, change the whole integration screen if it helps, take references, use the relevant skills.

---

## 1. Skills used, and why

| Skill | Why | What it actually contributed |
|---|---|---|
| `screen-refinement` (project) | The owner's standard for any screen edit | Order of work: map every state first (loading, error, read-only, edited, refused), then build, then verify at 390 and 1440 in both themes with the real server |
| `ui-ux-pro-max` (vendored search, `ux` domain) | Cross-check on forms and errors | "Error messages must be announced" (every field's error is an `aria-live` line and a failed save raises a `role=alert` summary); "Focusable error summary ... retain inline errors" (the bar says how many were refused, the first refused field takes focus, the errors stay under their fields); "Validate as the user types or on blur" (errors show as she types, only on fields that changed) |
| `web-design-guidelines` (Vercel) | Forms, focus and copy checklist | Labels on every field, visible focus ring, `aria-describedby` for counter and error, text 16px on a phone so it does not zoom, no placeholder used as a label |
| `design-taste-frontend` (app-screens rules) | Restraint | One accent, no new colours: the phone preview is drawn in the product's own tokens (so it follows dark mode) and not in WhatsApp's green; no decoration beyond what carries meaning |
| `apple-design` | Touch targets and order on a phone | 44px controls under 800px, answer-first order (the path's tabs, then each message with its own preview under it) |

## 2. Research: references, and what was taken

| Source | Principle | Verdict |
|---|---|---|
| Meta WhatsApp Manager, template editor | Fields on the left, a live phone preview on the right; buttons that insert a variable at the cursor; a character counter on each field | **Adopted.** The words he may use are buttons ("Her first name", "Her personal code") that put `{name}` or `{code}` at the cursor; required ones are marked "(needed)". The counter is `typed / limit` and turns amber at 90% and red over |
| Intercom / Klaviyo message editors | Edit each step inside the flow it belongs to, not in a flat list of strings | **Adopted.** Three paths as tabs, each the conversation top to bottom, each step headed by *when* it is sent. A flat list of 40 strings was the alternative and lost: nobody can tell where "Her code" lands |
| Stripe / Linear settings pages | Short cards; one primary action; a sticky save bar that appears only when something changed, saying how many | **Adopted.** "3 messages changed · Discard · Save" at the bottom edge; nothing there when nothing changed |
| Meta's list-message layout | A list question is a bubble with one button; the options live in a sheet that opens | **Adopted for the preview**: the bubble carries the button, the options are drawn beneath it as the sheet |

## 3. How the screen was explored

**Before.** One card inside Settings → Integrations → WhatsApp → Details: a status line, reward-code line, review link and reply hours (behind "Change"), and a "Send a test" row. It was the longest block on that screen and held three jobs that are not a connection. There was no way to see or change a message's words.

**Routes.** Inbox's `department.tsx`: `chats`, `chats/:id`, `confirmations`, `feedback`. Added `feedback/setup`. The sidebar matches a section by `within(pathname, section.to)`, so the setup page shows *Feedback* as current without a sidebar entry of its own.

**States the code can render** (each one has a test): loading; the wording could not be read (with Try again, and the status cards still show); read-only (not admin); nothing changed; edited and saved; changed and unsaved; over the limit; a required word missing; a word the message may not use; two options the same; refused by the server (one or several, on this path or another); a failed save for another reason (403, network); saved; discarded; no review link set (dimmed line); a review link set (invitation replaced); her name unknown.

**Server meaning.** `feedback_messages.text` fills only known `{words}`, in one pass, and drops `{name}` with the comma or space before it when she has no name; the preview does exactly that (`lib/feedbackMessages.ts: fill`, with tests). `describe` gives `flows` with `with_previous` (lines joined with a blank line into one WhatsApp message) and `sample`. The server checks everything again on save and answers 422 with `{detail: {errors: {key: why}}}` and saves nothing.

## 4. Findings and decisions

| ID | Where | Finding | Decision (and why it won) |
|---|---|---|---|
| F1 | Integrations card | Three jobs in one card on the screen for connections; the longest card there | Moved the review link, reply time and test to the setup page. The card keeps its title, the one status line, the reward-code line **only when codes cannot be made** (that is a Shopify permission: a connection fault, so it stays where connections are) and one link, "Open feedback setup" |
| F2 | Where the page lives | Settings is for the owner only; the Feedback sheet is for everyone who holds the Inbox | In the Inbox, under Feedback. No sidebar entry: it is rarely opened, a fourth item would sit beside Chats, Confirmations and Feedback as if it were equal to them. A "Feedback setup" button on the sheet's head (beside Download) and the Integrations link reach it |
| F3 | Editing 40 strings | A flat list does not say where a string is used or whether it is joined to its neighbour | Tabs per path; each step headed by *when*; lines joined into one WhatsApp message sit in one framed block with an accent edge and one sentence saying so |
| F4 | A list question | Three kinds of text (question, button, options) with three limits (1024 / 20 / 24) | One block per list: question as a textarea, button and options as short inputs, each with its own counter; the preview shows the bubble, its button and the sheet |
| F5 | Shared wording | "Her code", "Invitation to write", "Ask what it was", the list button are used on more than one path | "Also used on: ..." under the field, computed from `flows` (not from the group name), so it stays true if the paths change |
| F6 | The two Meta messages | They look like messages but cannot be edited here | Shown dashed with a lock and "Approved by Meta", the server's note, and, for the second, a plain sentence that it goes out instead of the question above when more than 24 hours have passed since her last message |
| F7 | Leaving with unsaved wording | The app uses `BrowserRouter`; `useBlocker` needs a data router | `useUnsavedGuard`: the browser's own question on tab close/reload (Targets already does this) and one `confirm` before an in-app link is followed (captured on the document before the router sees the click). **Not covered: the browser's Back button.** Moving the whole app to a data router to cover it is bigger than this change |
| F8 | Phone | A two-column editor cannot fit 390px | Under 1100px the preview column goes and each field carries its own preview bubble under it (one column, no sideways scroll). 1100 and not 1024 because the shell's sidebar takes 216px and 1024 left the fields 400px |
| F9 | Settings errors in `api.ts` | Only a string `detail` was understood; the per-field 422 became "The platform returned 422." | `ApiError.fieldErrors` is filled only when `detail.errors` is a map of strings. Every other answer reads exactly as before (tested) |
| F10 | Preview colours | WhatsApp's own greens would add a second brand colour and break in dark mode | The phone is drawn in the product's tokens, bubbles dashed for what is locked or not sent |

Things the owner might be surprised by, so recorded: blank text means the original wording (the server does the same); wording typed that equals the original is sent as `null`, so a later improvement to the built-in wording still reaches it; Save is held while anything is over a limit, missing a needed word or a duplicate option.

## 5. Not built, proposed (Integrations)

- The Integrations list shows server setting names to the owner ("SETTINGS_ENCRYPTION_KEY is not set"). Say what to do in plain words and keep the name in a "technical detail" line.
- WhatsApp's Replace key / Details buttons and the Connect buttons use two different button styles (`conns__btn`, `button--quiet`).
- The help text the server sends for "Was it solved? (in the chat)" names `feedback_resolved`. It should read "the approved message" only (backend wording).
- Settings → Integrations opens one connection's details under the list, far from the row on a long list. An inline expand under its own row would keep the owner's place.
- Browser Back is not guarded while wording is unsaved (needs a data router app-wide).

## 6. Verification

- `npm test`: 73 files, 1401 tests, all pass. `npm run build`: passes (it type-checks the tests too).
- `tests/test_reachability.py`: 3 passed (it failed before, only for GET and PUT `/api/inbox/feedback/messages`).
- Browser: Playwright headless against the real server on a throwaway database (`hba_browser_feedback`, seeded with `seed_inbox.py` and `seed_feedback.py`, dropped afterwards), as the owner and as customer service (read-only). 40 captures at 390 and 1440, light and dark, in `design-preview/feedback-setup/`. At 390: no sideways scroll, no control under 44px, no input text under 16px, on the setup page and the Integrations details. The only console error is the 401 the sign-in page produces before login.
- Fixed from looking at the captures: textarea in a monospace font; raw `{{1}}` shown in the locked first question; counter on its own line under every field; two heading levels wrong on Integrations; 38 to 40px buttons on a phone; the locked message shown twice on a phone.
- **Not verified:** a real phone or screen reader; the browser's Back button with unsaved wording (not guarded); Arabic typed on a real Arabic keyboard (checked with pasted Arabic text, alignment follows the text); saving through the real server from the browser (the captures stop before Save: the server's own save is covered by the backend tests and the page by mocked tests).

## 7. Mistakes and lessons

1. The first version put the "(needed)" marker's space inside the span; the accessible name read "Her personal code(needed)". Put the space beside the element, not inside it.
2. An existing routing test looked for the sidebar's Feedback link with `/^Feedback/`; the new "Feedback setup" button matched it too. A link added next to a link needs its own name that does not start with the other's.
3. Resetting editor state after a save in an effect left one frame showing the old text; reset it during the render that receives the response instead.
