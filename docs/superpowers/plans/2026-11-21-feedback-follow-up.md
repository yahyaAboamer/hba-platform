# Feedback follow-up record and tidier screen — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every unhappy-customer follow-up gets an append-only history (no answer / note / resolved with a required note / couldn't reach), an automatic "we tried to call you" WhatsApp message after the 2nd unanswered call, and the Feedback screen is rebuilt around a "To follow up" list, 4 summary cards and a 7-column sheet.

**Architecture:** A new table `feedback_follow_up` holds one row per action; a new service module `app/modules/inbox/services/feedback_follow_up.py` owns writing it, the round rules and the tried-to-call job. `feedback.describe` / `chat_block` gain the history; the API gains three actions and the open-list read. The frontend gets a shared `FollowUp.tsx` (history, clock, action buttons, pop-up) used by both `InboxFeedback.tsx` and `ChatFeedbackBlock.tsx`.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Postgres; React + Vite + Vitest.

**Spec:** `docs/superpowers/specs/2026-11-21-feedback-follow-up-design.md` (read it first; it is the source of every rule below).

## Global Constraints

- Python: `"D:/Desktop/HBA/HBA Engineering/hba-platform/.venv/Scripts/python.exe"` (the worktree has no `.venv`). Call it `$PY` below.
- Tests only against the disposable DB: `DATABASE_URL='postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform_test' $PY -m pytest -q --color=no <file>`. Never bare pytest. Never two pytest processes at once.
- Frontend: `cd frontend && npm test -- <file>` and `npm run build` (the real type gate). If `frontend/node_modules` is missing, run `npm ci` in `frontend` first.
- Copy follows memory rules: plain words, "her/she" for the customer as the existing code does, no "programme".
- History is append-only: no endpoint or service edits or deletes a `feedback_follow_up` row.
- Notes: required for Resolved and Add note, optional for No answer; at most **1,000** characters, trimmed; a whitespace-only note is empty.
- Message after the **2nd** no-answer of a round; *Couldn't reach* allowed from the **3rd**; a *Couldn't reach* reopens on a typed message within **14 days**.
- Template name `feedback_tried_to_call`, language `en`, one body variable (the order name). Its approved words: `We tried to call you about your order {{1}}. Reply here or tell us a good time to call.`
- Chat-message default words (owner-editable key `tried_to_call`): `We tried to call you about your order {order}. Reply here or tell us a good time to call.`
- Everything in ADR 0059's sending rules and `INBOX_FEEDBACK_ENABLED` applies to the new message (use `sending.refusal` and `feedback.enabled()` / `feedback.is_test_survey` exactly as `ask_solved` does).
- Tests (`is_test` surveys) follow the same rules and are never counted in summaries or the open list.
- Commit after each task with a message ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.

## Review Focus

1. **Double send of the tried-to-call message** (job runs twice, or two people press No answer at once): exactly one message per survey per round — the survey row is locked (`with_for_update`) for every action, the job is deduped on `survey:round`, and the sender checks for an existing `InboxMessage.source_ref == f"fbt:{survey.id}:{round}"` before sending. Test in Task 3.
2. **An action on a follow-up that is no longer open** (another person resolved it a second ago, the page is stale): a 422 in words, nothing written. Test in Task 2.
3. **She writes back after Couldn't reach, but has several surveys, or it is a button tap, or it is day 15**: only the most recent unreached survey for her phone within 14 days reopens, only on a typed text. Tests in Task 2.
4. **Her 24 hours close between the 2nd no-answer and the job running**: the window is checked at send time; template goes. Test in Task 3.
5. **A long Arabic note / a note full of newlines on a phone**: stored as typed (trimmed, ≤1,000), shown with `dir="auto"` and wrapping, never breaking the card at 390 px. Test in Task 5 (render) and the 390 px screenshot in Task 7.

---

### Task 1: Rules, table and migration

**Files:**
- Create: `docs/adr/0087-a-follow-up-keeps-a-record-of-every-call.md` (template: `docs/adr/template.md`; content = the spec's "The rules" + "Settled after the builder check"; amends ADR 0083 decisions 4 and 6)
- Modify: `docs/RULES.md` (the Inbox feedback section near line 256: add the follow-up rules in 4–6 bullets, pointing to ADR 0087)
- Modify: `app/modules/inbox/models.py` (new `FeedbackFollowUp`; new columns on `FeedbackSurvey`)
- Create: `migrations/versions/a7c1e2f30040_feedback_follow_up.py` (down_revision `f1c2d3e40039`)
- Test: `tests/test_inbox_feedback_follow_up.py` (new)

**Interfaces — Produces:**
- `FOLLOW_UP_KINDS = ("no_answer", "note", "resolved", "unreached", "message_sent", "message_failed", "wrote_back", "returned")` in `models.py`
- `class FeedbackFollowUp(Base)`, table `feedback_follow_up`: `id` pk; `survey_id` int FK `feedback_survey.id` ondelete CASCADE not null; `round` int not null; `kind` String(16) not null (check in `FOLLOW_UP_KINDS`); `note` Text null; `actor_id` int FK `user_account.id` ondelete SET NULL null (null = the platform); `at` timestamptz not null default now(). Index `feedback_follow_up_survey` on `(survey_id, at)`.
- `FeedbackSurvey` gains: `follow_up_round` int not null server_default 0 (check `>= 0`); `round_started_at` timestamptz null; `unreached_at` timestamptz null; `unreached_by` int FK `user_account.id` SET NULL null.
- Migration backfill: for `rating = 'unhappy'`: `follow_up_round = reopened_count`, `round_started_at = CASE WHEN reopened_count > 0 THEN coalesce(solved_at, reason_at, rated_at) ELSE coalesce(reason_at, rated_at) END`. For every survey with `resolved_at IS NOT NULL`: insert one `resolved` entry (`round = reopened_count`, `note NULL`, `actor_id = resolved_by`, `at = resolved_at`). Downgrade drops the table and the four columns.

- [ ] **Step 1: Write the failing test** `test_the_follow_up_table_holds_an_entry` in `tests/test_inbox_feedback_follow_up.py`: using `tests/feedback_support.survey(db, rating="unhappy", step="support")`, add `FeedbackFollowUp(survey_id=s.id, round=0, kind="no_answer", note=None)`, flush, assert it reads back with `at` set; and `test_an_unknown_kind_is_refused` asserting `kind="call"` raises `IntegrityError` on flush.
- [ ] **Step 2: Run it, expect FAIL** (import error).
- [ ] **Step 3: Write model, migration, ADR, RULES.md.**
- [ ] **Step 4: Migrate the test DB and run the test:** `DATABASE_URL=... $PY -m alembic upgrade head`, then the test file. Expect PASS. Also run `DATABASE_URL=... $PY -m alembic downgrade -1 && ... upgrade head` and expect both to succeed.
- [ ] **Step 5: Commit** `feat(inbox): feedback follow-up history table (ADR 0087)`.

---

### Task 2: Follow-up actions and rounds (service)

**Files:**
- Create: `app/modules/inbox/services/feedback_follow_up.py`
- Modify: `app/modules/inbox/services/feedback_replies.py` (`resolve` takes a note; `record_tap` solved-no starts a round; `back_to_support` writes a `returned` entry)
- Modify: `app/modules/inbox/services/events.py:329-332` (call the wrote-back hook for typed text)
- Modify: `app/shared/services/jobs.py` (add `INBOX_FEEDBACK_TRIED_TO_CALL = "inbox_feedback_tried_to_call"` next to the other feedback kinds and to the same kinds tuple at ~line 176)
- Test: `tests/test_inbox_feedback_follow_up.py`

**Interfaces — Consumes:** Task 1 model. `chats.NotFound`, `chats.Refused` (import inside functions as `resolve` does). `record_audit`. `enqueue`.

**Produces (in `feedback_follow_up.py`):**
- Constants `NOTE_MAX = 1000`, `MESSAGE_AFTER_CALLS = 2`, `CLOSE_FROM_CALLS = 3`, `REOPEN_WITHIN = timedelta(days=14)`.
- `clean_note(note: str | None, *, required: bool, missing: str) -> str | None` — trims; empty → `None` or `Refused(missing)` when required; over 1,000 → `Refused("A note can be at most 1,000 characters.")`.
- `add_entry(db, survey: FeedbackSurvey, kind: str, *, note: str | None = None, actor_id: int | None = None, at: datetime | None = None) -> FeedbackFollowUp` — round = `survey.follow_up_round`.
- `no_answer_count(db, survey) -> int` — `no_answer` entries in the current round.
- `message_sent(db, survey) -> bool` — a `message_sent` entry in the current round.
- `start_round(survey, at: datetime) -> None` — `follow_up_round += 1`, `round_started_at = at`.
- `lock_open(db, survey_id) -> FeedbackSurvey` — `select ... with_for_update()`; `NotFound("No such feedback.")`; not (`rating == "unhappy"` and `step == "support"`) → `Refused("Only a follow-up that is still open can be updated.")`.
- `no_answer(db, survey_id, user, note: str | None, close: bool = False, now=None) -> FeedbackSurvey` — writes `no_answer`; if the count is now exactly `MESSAGE_AFTER_CALLS` and `not message_sent`, enqueue `JobKind.INBOX_FEEDBACK_TRIED_TO_CALL` `{"survey_id": id}`, `run_after=now`, `dedupe_key=f"{kind}:{id}:{round}"`. If `close`: count (after this one) < 3 → `Refused("It can be closed as couldn't reach from the third call with no answer.")` and nothing written (check before writing); else write `unreached` entry, `step = "done"`, `unreached_at = now`, `unreached_by = user.id`. Audit `inbox.feedback_no_answer` (after: count, closed).
- `add_note(db, survey_id, user, note: str, now=None) -> FeedbackSurvey` — required note, missing words `"Write the note first."`; audit `inbox.feedback_note`.
- `reopen_if_unreached(db, phone: str, at: datetime) -> bool` — most recent survey with that phone, `unreached_at` within `REOPEN_WITHIN` before `at`, `step == "done"`, prefer non-test (`order_by(is_test, unreached_at.desc())`); sets `step = "support"`, clears `unreached_at`/`unreached_by`, `start_round(survey, at)`, entry `wrote_back` (actor None). Returns whether it reopened.

**Changes elsewhere:**
- `feedback_replies.resolve(db, survey_id, user, note: str, now=None)` — `clean_note(note, required=True, missing="Write what you agreed with her before resolving.")` **before** any write; keep the existing refusal text for a non-open survey; add a `resolved` entry with the note.
- `record_tap`, solved == no branch: also `feedback_follow_up.start_round(survey, at)`.
- Unhappy reason tap (`step` becomes `support`): set `round_started_at = at` (round 0).
- `back_to_support(survey, why, now)`: also add a `returned` entry with `note=why`, using `sqlalchemy.orm.object_session(survey)`; if there is no session (a detached object in an old test), skip the entry.
- `events.py`: for `fields["kind"] == "text"`, after `capture_comment`, call `feedback_follow_up.reopen_if_unreached(db, phone, occurred_at)`. Taps never reach it.

- [ ] **Step 1: Write the failing tests** (all in `tests/test_inbox_feedback_follow_up.py`, using `feedback_support` fixtures; `user` = an existing admin fixture from `tests/conftest.py`):
  - `test_no_answer_keeps_it_open_and_records_who` — after `no_answer(db, s.id, user, " Phone off ")`: `s.step == "support"`, one entry `kind="no_answer"`, `note == "Phone off"`, `actor_id == user.id`, no job.
  - `test_the_second_no_answer_queues_one_message` — two calls → `jobs(db, "inbox_feedback_tried_to_call")` has exactly 1 with dedupe key `inbox_feedback_tried_to_call:{id}:0`; a third call queues none more.
  - `test_couldnt_reach_only_from_the_third_call` — `no_answer(..., close=True)` on call 2 raises `Refused` with the exact words and leaves 1 entry; on call 3 → `step == "done"`, `unreached_at` set, entries end `no_answer, unreached`, and no `INBOX_FEEDBACK_ASK_SOLVED` job.
  - `test_resolve_needs_a_note` — `resolve(db, id, user, "  ")` raises `Refused("Write what you agreed with her before resolving.")`, `step` unchanged; `resolve(..., "Exchange to L")` → `step == "solved"`, entry `resolved` with that note.
  - `test_an_action_on_a_closed_follow_up_is_refused` — after resolve, `no_answer` and `add_note` raise `Refused("Only a follow-up that is still open can be updated.")`; entry count unchanged.
  - `test_a_note_over_1000_characters_is_refused` and `test_add_note_needs_words`.
  - `test_she_says_not_solved_starts_a_new_round` — resolve, then a solved-no tap via `record_tap` → `follow_up_round == 1`, `round_started_at == tap time`, `no_answer_count == 0`; two more no-answers queue a job keyed `:1`.
  - `test_a_typed_message_reopens_couldnt_reach_within_14_days` — closed at T; `reopen_if_unreached(db, phone, T+13d)` → True, `step == "support"`, `unreached_at is None`, round +1, last entry `wrote_back`.
  - `test_day_15_or_a_tap_does_not_reopen` — T+15d → False; and through `events` an interactive tap from that phone leaves it closed (use the existing tap helper in `feedback_support.message`).
  - `test_back_to_support_writes_returned` — call `back_to_support(s, "why")` on a survey in step `solved` → last entry `returned`, note `"why"`, same round.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Update the existing callers of `resolve(...)` in tests (`tests/test_inbox_feedback*.py`) to pass a note.
- [ ] **Step 4: Run the new file and every `tests/test_inbox_feedback*.py` file one at a time; expect PASS.**
- [ ] **Step 5: Commit** `feat(inbox): record calls, notes and couldn't-reach on a follow-up`.

---

### Task 3: The "we tried to call you" message

**Files:**
- Modify: `app/modules/inbox/services/feedback_follow_up.py` (sender + job handler)
- Modify: `app/modules/inbox/services/feedback.py` (constants `TRIED_TEMPLATE = "feedback_tried_to_call"`, `TRIED_LANGUAGE = "en"`, `TRIED_CHAT = "We tried to call you about your order {order}. Reply here or tell us a good time to call."` — the words the chat shows for the template)
- Modify: `app/modules/inbox/services/feedback_messages.py` (a `text_item("tried_to_call", "unhappy", "We tried to call you", help, default, uses=("name", "order"))` with the default in Global Constraints — add `order` as an allowed placeholder; add the template to `TEMPLATES` with note `"Submit it to Meta in WhatsApp Manager. Until Meta approves it, a customer whose 24 hours have closed is not messaged and the chat tells your team to write to her."`; add it to `_flows()` under the unhappy flow after `support`, labelled `"After the second call with no answer"`)
- Test: `tests/test_inbox_feedback_follow_up.py`, `tests/test_inbox_feedback_messages.py`

**Interfaces — Consumes:** Task 2 `add_entry`, `message_sent`. `outbound.window_open`, `outbound.send_text`, `outbound.record_outbound`, `outbound._client`, `sending.refusal`, `_conversation` (from `events`), `feedback_messages.text`, `MetaError`, `NotSent`.

**Produces:**
- `send_tried_to_call(db, survey_id: int, *, client: MetaClient | None = None, now: datetime | None = None) -> FeedbackSurvey | None` — does nothing unless the survey is still open (`unhappy`/`support`) and `not message_sent`. Reference `f"fbt:{survey.id}:{survey.follow_up_round}"`; if an `InboxMessage` with that `source_ref` exists, only add the missing `message_sent` entry (if its status isn't `failed`) and return. `sending.refusal` → `message_failed` entry. Window open (checked now) → `send_text(..., origin="automatic", source_ref=reference)`; closed → template with one body parameter (the order name), recorded via `record_outbound(kind="template", body=TRIED_CHAT.format(order=...), template_name=TRIED_TEMPLATE, source_ref=reference, order_id=...)`, mirroring `_send_solved_template`. Retryable `MetaError` → re-raise (job retries); `NotSent`, non-retryable refusal or a `failed` message → `message_failed` entry with note `f"Couldn't send the WhatsApp message: {why} Write to her yourself."`; success → `message_sent` entry (note = the words sent).
- `@register_handler(JobKind.INBOX_FEEDBACK_TRIED_TO_CALL)` `_handle_tried_to_call(db, payload)` — `PermanentFailure` on a missing `survey_id`; if `not feedback.enabled() and not feedback.is_test_survey(db, id)` → `message_failed` entry with why `"feedback is switched off."` and return; else `send_tried_to_call`.
- Make sure the module is imported where the worker registers handlers (follow how `feedback_replies` is imported for its handlers).

- [ ] **Step 1: Write the failing tests** (Meta faked with `feedback_support.meta(asked)`; use `may_send`, `feature_on`, `conversation(db, wrote_ago=...)`):
  - `test_the_message_goes_as_chat_while_her_24_hours_are_open` — `wrote_ago=1h`: one free text sent with the default words filled with the order name; entry `message_sent`.
  - `test_the_template_goes_once_her_24_hours_closed` — `wrote_ago=30h`: `send_template` called with `"feedback_tried_to_call"`, `"en"`, body param = order name; chat shows `TRIED_CHAT` words.
  - `test_the_window_is_checked_when_sending` — queue while open, move `last_inbound_at` back 25h, run the handler → template.
  - `test_running_twice_sends_once` — call `send_tried_to_call` twice → Meta asked once, one `message_sent`.
  - `test_a_template_meta_refuses_tells_the_team` — Meta refuses non-retryably (e.g. template not approved): entry `message_failed`, note starts `"Couldn't send the WhatsApp message:"` and ends `"Write to her yourself."`; the follow-up stays open.
  - `test_feature_off_sends_nothing` — `feature_on` not applied → no Meta call, `message_failed` with `"feedback is switched off."`.
  - `test_resolved_before_the_job_ran_sends_nothing`.
  - In `test_inbox_feedback_messages.py`: `test_tried_to_call_words_are_editable_and_take_the_order` — saving `"Hi {name}, about {order}"` is accepted; `{code}` is refused.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run both files and `tests/test_worker.py`; expect PASS.**
- [ ] **Step 5: Commit** `feat(inbox): message her on WhatsApp after the second unanswered call`.

---

### Task 4: API, sheet, summary and download

**Files:**
- Modify: `app/modules/inbox/api.py` (~line 601)
- Modify: `app/modules/inbox/services/feedback.py` (`describe`, `rows`, `_filtered`, `summary`, `options`, `chat_block`, `SHEET_STATES`)
- Modify: `app/modules/inbox/services/feedback_follow_up.py` (`describe_many`)
- Modify: `app/modules/inbox/services/feedback_sheet.py` (`COLUMNS`, `_values`)
- Test: `tests/test_inbox_feedback_api.py`

**Interfaces — Consumes:** Tasks 1–3.

**Produces:**
- `feedback_follow_up.describe_many(db, surveys: list[FeedbackSurvey]) -> dict[int, dict]` — one query for all entries plus one for names; per survey: `{"history": [entry...] (oldest first), "no_answer_count": int, "message_sent": bool, "waiting_since": iso|None (round_started_at or rated_at), "unreached_at": iso|None, "unreached_by_name": str|None, "follow_up_round": int}`; entry = `{"id", "round", "kind", "note", "at", "by_name"}` (`by_name` None for the platform).
- `feedback.describe(row, resolved_by=None, follow_up: dict | None = None)` merges `follow_up` (empty defaults when None) and adds `"follow_up_state"`: `"needs_follow_up"` if open, `"unreached"` if `unreached_at`, `"resolved"` if `resolved_at`, else `None`. `rows()` and `needs_follow_up()` pass `describe_many`.
- `describe` also carries `"conversation_id"` (for *Open chat*).
- `_filtered`: `q` also matches product titles (`FeedbackSurvey.products.cast(Text).ilike(_like(words))`); `state == "unreached"` → `unreached_at IS NOT NULL`; `rating == "none"` → `rating IS NULL`. `SHEET_STATES` gains `"unreached"`; `options()["states"]` gains `{"id": "unreached", "title": "Couldn't reach"}`; titles become `"To follow up"` for `needs_follow_up`.
- `summary()` gains `"overdue"` (open and `coalesce(round_started_at, rated_at) < now - reply_hours`), `"solved_asked"` (`solved IS NOT NULL`), `"unreached"` (`unreached_at IS NOT NULL`).
- `chat_block()` merges `describe_many` for its row and adds `"reply_hours"`.
- API:
  - `class FollowUpNoteBody(BaseModel): note: str = ""` and `class NoAnswerBody(BaseModel): note: str | None = None; close: bool = False`.
  - `POST /feedback/{id}/resolve` takes `FollowUpNoteBody` (body optional for FastAPI → treat missing as `""`, which is refused in words).
  - `POST /feedback/{id}/no-answer` (`NoAnswerBody`) and `POST /feedback/{id}/note` (`FollowUpNoteBody`), both via `_answering`, commit, return `describe` with follow-up data (resolve returns the same shape).
  - `GET /feedback/follow-up` → `{"rows": [...], "reply_hours": int}`: every open non-test follow-up, longest waiting first (`coalesce(round_started_at, rated_at)`, id), regardless of sheet filters.
- Download `COLUMNS` gains, after `"Times reopened"`: `("Calls with no answer", 12)`, `("Last follow-up note", 50)`, `("Couldn't reach", 24)` (value `"<date> by <name>"`). Calls = total `no_answer` entries across rounds; last note = the newest non-empty note from a person.

- [ ] **Step 1: Write the failing tests** in `tests/test_inbox_feedback_api.py`:
  - `test_resolved_needs_a_note_in_words` — POST without body → 422 `"Write what you agreed with her before resolving."`; with `{"note": "Exchange"}` → 200, `history[-1] == {kind:"resolved", note:"Exchange", by_name: <admin name>, ...}`.
  - `test_no_answer_and_note_endpoints` — no-answer twice → `no_answer_count == 2`, one queued job; note → history grows; close on call 2 → 422 in words; close on call 3 → `follow_up_state == "unreached"`.
  - `test_the_follow_up_list_ignores_the_sheet_filters_and_tests` — an open follow-up delivered 60 days ago and a test one: `/feedback/follow-up` lists the first only, oldest first, `reply_hours` 24.
  - `test_the_summary_counts_overdue_unreached_and_solved_asked`.
  - `test_filters_couldnt_reach_and_no_answer_yet` — `state=unreached`, `rating=none`.
  - `test_the_download_has_the_follow_up_columns`.
  - `test_the_chat_carries_the_history` — extend the existing chat test: `history`, `waiting_since`, `reply_hours` present.
  - Update `test_one_row_has_everything_the_screen_needs` for the new keys.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run every `tests/test_inbox_feedback*.py` and `tests/test_inbox_chats.py` one at a time; expect PASS.**
- [ ] **Step 5: Commit** `feat(inbox): follow-up history in the sheet, the chat and the download`.

---

### Task 5: Shared follow-up pieces and the chat block (frontend)

**Files:**
- Modify: `frontend/src/lib/inbox.ts` (types)
- Create: `frontend/src/departments/inbox/FollowUp.tsx`
- Modify: `frontend/src/departments/inbox/ChatFeedbackBlock.tsx`
- Modify: `frontend/src/departments/inbox/Inbox.css` (classes prefixed `inbox-fu`)
- Test: `frontend/src/departments/inbox/__tests__/FollowUp.test.tsx` (new), `InboxChats.test.tsx` (update any Resolved expectation)

**Interfaces — Consumes:** Task 4 JSON.

**Produces:**
- Types: `FollowUpKind` (the 8 kinds); `FollowUpEntry = { id: number; round: number; kind: FollowUpKind; note: string | null; at: string; by_name: string | null }`; `FollowUpFields = { history: FollowUpEntry[]; no_answer_count: number; message_sent: boolean; waiting_since: string | null; unreached_at: string | null; unreached_by_name: string | null; follow_up_round: number; follow_up_state: "needs_follow_up" | "resolved" | "unreached" | null }`; `FeedbackRow` and `ChatFeedback` extend it (`ChatFeedback` also `reply_hours: number`); `FeedbackFollowUp` adds `"unreached"`; `FeedbackSummary` adds `overdue`, `solved_asked`, `unreached`; `FollowUpListPage = { rows: FeedbackRow[]; reply_hours: number }`.
- `FollowUpHistory({ entries, limit = 3 })` — oldest-first list; when more than `limit`, shows the newest `limit` and a "Show all (N)" button. Lines: `No answer · Mona · 21 Nov 10:40 · "note"`; `Note · …`; `Resolved · …`; `Closed: couldn't reach · …`; `WhatsApp sent by the platform · …`; `Couldn't send the WhatsApp message …` (its note, owed tone); `She wrote back · …`; `Back to your team: <note>`. Notes `dir="auto"`, wrap.
- `WaitingClock({ since, hours, now })` — `Waiting 6 h · 18 h left`, or `Waiting 27 h · past the 24 h promise` in the refused tone; under an hour `Waiting 40 min`; over 48 h `Waiting 3 days`.
- `FollowUpActions({ survey: FeedbackRow | ChatFeedback (id, order_name, customer_name, rating reason title, no_answer_count, message_sent), onDone(updated: FeedbackRow) })` — three buttons `Resolved…` (filled), `No answer`, `Add note`; each opens `FollowUpDialog`.
- `FollowUpDialog` — a native `<dialog>` following the pattern in `frontend/src/screens/settings/Team.tsx`; focus to the textarea; Esc/Cancel closes; keeps typed text and shows the server's words on failure; submit disabled while saving or when a required note is empty. Copy exactly as the mockup/spec:
  - Resolve: title `Resolve {order}`, label `What did you agree with her?` (required), hint `Tomorrow she'll get a WhatsApp message: "Was your issue solved?" If she says no, she comes back to To follow up.`, buttons `Cancel` / `Save and resolve`. POST `/resolve` `{note}`.
  - No answer: title `No answer: {order}`, sub `This is call {n}` (n = count + 1), label `Note (optional)`. Hint when n == 2 and not message_sent: `After this call she'll get a WhatsApp message from the platform: "We tried to call you about order {order}. Reply here or tell us a good time to call."`; when n > 2 and message_sent: `She has already been sent the WhatsApp message.` When n ≥ 3, unticked checkbox `Close as Couldn't reach. She won't be asked "Was your issue solved?". If she writes back within 14 days, it opens again.` Buttons `Cancel` / `Save call`. POST `/no-answer` `{note, close}`.
  - Add note: title `Add a note: {order}`, label `Note` (required), buttons `Cancel` / `Save note`. POST `/note`.
- `ChatFeedbackBlock`: keep its existing facts; add `WaitingClock` while open, `FollowUpHistory`, and `FollowUpActions` replacing the bare Resolved button (still only when open and not a just-resolved state); `onResolved` prop renamed `onChanged` (update `ChatOrderPanel.tsx:83`). After a closed *Couldn't reach*, show `Closed as couldn't reach by {name} on {date}.`

- [ ] **Step 1: Write the failing tests** in `FollowUp.test.tsx` (mock `api.post` as the existing Inbox tests do):
  - `resolve needs a note before it can be saved` — Save disabled when empty; typing enables; posts `{note}` to `/api/inbox/feedback/7/resolve`; `onDone` gets the response.
  - `the second no-answer warns about the WhatsApp message` / `the third offers couldn't reach, unticked`.
  - `a refusal keeps the typed note and shows the server's words`.
  - `history shows the newest three and opens to all`.
  - `a long Arabic note wraps and reads right to left` — `dir="auto"` on the note element.
  - `the clock turns past the promise after the promised hours`.
- [ ] **Step 2: Run** `npm test -- FollowUp`, expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `npm test -- inbox` and `npm run build`; expect PASS.**
- [ ] **Step 5: Commit** `feat(inbox): follow-up history, clock and pop-ups beside the chat`.

---

### Task 6: The Feedback screen

**Files:**
- Modify: `frontend/src/departments/inbox/InboxFeedback.tsx` (split into `FeedbackCards`, `FollowUpList`, the sheet; may move pieces into `FeedbackSheet.tsx` if the file passes ~600 lines)
- Modify: `frontend/src/departments/inbox/Inbox.css`
- Test: `frontend/src/departments/inbox/__tests__/InboxFeedback.test.tsx`

**Interfaces — Consumes:** Task 5 components and types; `GET /api/inbox/feedback` (unchanged shape plus new fields) and `GET /api/inbox/feedback/follow-up`.

**Produces (behaviour, copy as in the spec section "What the screen shows"):**
- Cards (4): `Answered` (`{answered}` big, `of {asked} asked` small; foot `{pct}% answered` + ` · {not_reached} couldn't be reached` when > 0); `How they felt` (one bar loved/okay/unhappy, legend with counts; a legend item is a button that toggles the rating filter, `aria-pressed`); `To follow up` (`needs_follow_up`, owed tone, foot `{overdue} past the {hours}-hour promise` when > 0; pressing scrolls to the list and moves focus to its heading); `Reward codes used` (`{codes_used}` of `{codes_sent} sent`; foot `Problems solved: {solved} of {solved_asked} asked` when `solved_asked` > 0). Zero asked → percentage hidden.
- `FollowUpList`: fetched separately, hidden when empty, heading `To follow up` + count chip, `Longest-waiting first`; a card per row: name (`dir="auto"`), phone, order; `WaitingClock`; answer chip + reason; her words (two-line clamp, `dir="auto"`, or `No comment written`); `FollowUpHistory` or `Not called yet`; `FollowUpActions` plus `Open chat` link (`/inbox/chats?view=follow_up` + the conversation if the row carries `conversation_id`; add `conversation_id` to `describe` in Task 4 if absent). After an action the list and the sheet/cards are read again. Cards stack at ≤ 860 px; at 390 px the buttons sit in a row under the card.
- Sheet: columns `Asked · Customer · Order · Answer · What she said · Follow-up · Reward code` with second lines as in the mockup; Follow-up cell = chip (`To follow up` owed, `Resolved` settled, `Couldn't reach` plain) + one line (`Not called yet` / `{n} calls, no answer` (+ ` · WhatsApp sent`) / the latest note-bearing entry `"{note}"` / `Reopened {n}×`).
- Filters: date range (two inputs as today), Answer segmented control (`All`, `Loved it`, `It was okay`, `Not happy`, `No answer yet` → `rating=none`) with `aria-pressed`, Follow-up select (adds `Couldn't reach`), one search box `Order, name, phone or product` (sends `q`; the server's `q` gains product matching in Task 4 — add `FeedbackSurvey.products.cast(Text).ilike` to its clauses), `More filters` disclosure holding Courier and Reason (Reason disabled until an answer is chosen, as today; opens by itself when either is set). `Clear filters` as today. The old separate Product box goes; a `product=` address still filters (kept for old links).
- Phone (narrow): cards as today but with the same content order as the table.

- [ ] **Step 1: Update/write failing tests** in `InboxFeedback.test.tsx`: `four cards and the bar`, `the follow-up list shows only when someone waits and ignores filters`, `an action re-reads the list and the sheet`, `the sheet has seven columns`, `no answer yet filters rating=none`, `more filters holds courier and reason and opens when one is set`, `search covers products`. Remove tests for the removed tiles/columns.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: `npm test` (whole frontend) and `npm run build`; expect PASS.**
- [ ] **Step 5: Commit** `feat(inbox): tidier Feedback screen with the to-follow-up list first`.

---

### Task 7: Verify end to end and write it down

**Files:**
- Create: `docs/design-refinement/feedback/JOURNAL.md` (from `.claude/skills/screen-refinement/references/journal-template.md`: what changed, why, the screenshots taken)
- Modify: `docs/repair/batch-2/visual/seed_feedback.py` (seed: one open follow-up past the promise with 2 no-answers + message_sent, one with a note, one resolved with a note, one couldn't reach)

- [ ] **Step 1:** `bash docs/repair/batch-1/run-suite.sh` until it reports nothing remaining (re-run after each slice). Expect all files passing.
- [ ] **Step 2:** `cd frontend && npm test && npm run build` — PASS.
- [ ] **Step 3:** Run the visual harness per `docs/repair/batch-2/visual/README.md` with the seed; capture `/inbox/feedback` and a chat with a follow-up at 1280 and 390, light and dark; open each pop-up. Compare with the approved mockup and note differences in the journal.
- [ ] **Step 4:** Whole-branch review (fresh reviewer on the most capable model); fix findings; re-run steps 1–2 for touched areas.
- [ ] **Step 5: Commit** `docs: feedback follow-up journal and seed`.
