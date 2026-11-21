import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError, api } from "../../lib/api";
import { RATING_WORDS } from "../../lib/inbox";
import type {
  FeedbackFollowUp,
  FeedbackOptions,
  FeedbackPage,
  FeedbackRating,
  FeedbackRow,
  FeedbackSummary,
  FollowUpListPage,
} from "../../lib/inbox";
import { OpsIcon, useIsNarrow, useNow } from "../../components/OpsSource";
import { FollowUpList } from "./FeedbackFollowUpList";
import { SheetCards, SheetTable } from "./FeedbackSheet";
import { InboxIcon } from "./InboxIcon";
import "../operations/OperationsDashboard.css";
import "./Inbox.css";

/**
 * Inbox → Feedback: every answer to "how did your order go?" (ADR 0083,
 * decision 6), rebuilt around the follow-up (ADR 0087). Top to bottom: four
 * summary cards, *To follow up* (everyone still waiting on a person, whatever
 * the filters say), and *All answers*, the sheet.
 *
 * The follow-up is recorded here and beside the chat (`FollowUp.tsx`); the
 * sheet itself only reads, filters and downloads. Every filter lives in the
 * address, so a filtered view can be linked and survives a reload. The
 * approved mockup is `feedback-layout.html` part 1; it is drawn with the
 * Inbox's and Operations' own pieces.
 */

const RATINGS: FeedbackRating[] = ["loved", "okay", "unhappy"];
type AnswerFilter = FeedbackRating | "none" | "";
/** The Answer control, left to right. `none` is "No answer yet". */
const ANSWERS: { id: AnswerFilter; title: string }[] = [
  { id: "", title: "All" },
  ...RATINGS.map((id) => ({ id, title: RATING_WORDS[id] })),
  { id: "none", title: "No answer yet" },
];
const FOLLOW_UPS: FeedbackFollowUp[] = ["needs_follow_up", "resolved", "reopened", "unreached"];
const FOLLOW_UP_WORDS: Record<FeedbackFollowUp, string> = {
  needs_follow_up: "To follow up",
  resolved: "Resolved",
  reopened: "Reopened",
  unreached: "Couldn't reach",
};

/** The sheet opens on the last 30 days: today and the 29 before it. */
const DEFAULT_DAYS = 30;
const SEARCH_AFTER_MS = 300;
/** What the promise is until the list says otherwise (Feedback setup's default). */
const DEFAULT_REPLY_HOURS = 24;

type Filters = {
  since: string;
  until: string;
  rating: AnswerFilter;
  reason: string;
  courier: string;
  state: FeedbackFollowUp | "";
  /** No box of its own any more (search covers products); kept so old links still filter. */
  product: string;
  q: string;
};

// ── Dates, in Cairo ─────────────────────────────────────────────────────────

const CAIRO_DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Cairo" });

/** The day `daysAgo` days back in Cairo, as the date input wants it. */
function cairoDay(daysAgo: number): string {
  const [year, month, day] = CAIRO_DAY.format(new Date()).split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day - daysAgo)).toISOString().slice(0, 10);
}

const isDay = (value: string | null): value is string => /^\d{4}-\d{2}-\d{2}$/.test(value ?? "");
const isRating = (value: string): value is FeedbackRating => RATINGS.includes(value as FeedbackRating);

// ── Filters in the address ──────────────────────────────────────────────────

function readFilters(params: URLSearchParams, defaultSince: string): Filters {
  const rating = params.get("rating") ?? "";
  const state = params.get("state");
  const chosen: AnswerFilter = isRating(rating) || rating === "none" ? rating : "";
  const since = params.get("since");
  const until = params.get("until");
  return {
    // Left out means the default; given but empty means no start at all.
    since: params.has("since") ? (isDay(since) ? since : "") : defaultSince,
    until: isDay(until) ? until : "",
    rating: chosen,
    // A reason belongs to an answer: without one it is not asked for.
    reason: isRating(chosen) ? (params.get("reason") ?? "") : "",
    courier: params.get("courier") ?? "",
    state: FOLLOW_UPS.includes(state as FeedbackFollowUp) ? (state as FeedbackFollowUp) : "",
    product: params.get("product") ?? "",
    q: params.get("q") ?? "",
  };
}

/** The question put to the server for these filters, without a page. */
function queryFor(filters: Filters): string {
  const query = new URLSearchParams();
  if (filters.since) query.set("since", filters.since);
  if (filters.until) query.set("until", filters.until);
  if (filters.rating) query.set("rating", filters.rating);
  if (filters.reason) query.set("reason", filters.reason);
  if (filters.courier) query.set("courier", filters.courier);
  if (filters.state) query.set("state", filters.state);
  if (filters.product) query.set("product", filters.product);
  if (filters.q) query.set("q", filters.q);
  return query.toString();
}

/**
 * A text box that waits for the typing to stop before it asks the server, and
 * follows the address when something else changes it (Clear filters, Back).
 */
function useTyped(value: string, commit: (value: string) => void): [string, (value: string) => void] {
  const [typed, setTyped] = useState(value);
  // What this box last wrote to the address, so its own write is not read back
  // as somebody else's and does not eat a letter typed since.
  const wrote = useRef(value);
  useEffect(() => {
    if (value !== wrote.current) {
      wrote.current = value;
      setTyped(value);
    }
  }, [value]);
  const later = useRef(commit);
  later.current = commit;
  useEffect(() => {
    const next = typed.trim();
    if (next === wrote.current) return undefined;
    const timer = window.setTimeout(() => {
      wrote.current = next;
      later.current(next);
    }, SEARCH_AFTER_MS);
    return () => window.clearTimeout(timer);
  }, [typed]);
  return [typed, setTyped];
}

// ── The four cards ──────────────────────────────────────────────────────────

const count = (n: number) => n.toLocaleString("en-US");

function Cards({
  summary,
  rating,
  old,
  hours,
  canGoToList,
  onRating,
  onGoToList,
}: {
  summary: FeedbackSummary;
  rating: AnswerFilter;
  /** The numbers are from the last question, while the next is on its way. */
  old: boolean;
  hours: number;
  /** Whether anyone is in the *To follow up* list to go to. */
  canGoToList: boolean;
  onRating: (rating: FeedbackRating, on: boolean) => void;
  onGoToList: () => void;
}) {
  const answeredFoot = [
    summary.asked > 0 ? `${Math.round((summary.answered / summary.asked) * 100)}% answered` : null,
    summary.not_reached > 0 ? `${count(summary.not_reached)} couldn't be reached` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const felt = summary.loved + summary.okay + summary.unhappy;
  const overdue = summary.overdue ?? 0;
  const solvedAsked = summary.solved_asked ?? 0;

  const followUpBody = (
    <>
      <span className="ops-tile__label">To follow up</span>
      <span className="ops-tile__value">{count(summary.needs_follow_up)}</span>
      {overdue > 0 && (
        <span className="ops-tile__note inbox-fb__late">
          {count(overdue)} past the {hours}-hour promise
        </span>
      )}
    </>
  );
  const owed = summary.needs_follow_up > 0 ? " inbox-fb__tile--owed" : "";

  return (
    <div
      className={old ? "ops-tiles inbox-fb__tiles ops-tiles--old" : "ops-tiles inbox-fb__tiles"}
      role="group"
      aria-label="Summary of these answers"
    >
      <div className="ops-tile inbox-fb__tile">
        <span className="ops-tile__label">Answered</span>
        <span className="ops-tile__value">
          {count(summary.answered)}
          <span className="inbox-fb__of"> of {count(summary.asked)} asked</span>
        </span>
        {answeredFoot && <span className="ops-tile__note">{answeredFoot}</span>}
      </div>

      <div className="ops-tile inbox-fb__tile inbox-fb__tile--felt">
        <span className="ops-tile__label">How they felt</span>
        <div className="inbox-fb__bar" aria-hidden="true">
          {felt > 0 &&
            RATINGS.map((id) => (
              <span
                key={id}
                className={`inbox-fb__bar-${id}`}
                style={{ width: `${(summary[id] / felt) * 100}%` }}
              />
            ))}
        </div>
        <div className="inbox-fb__legend">
          {RATINGS.map((id) => {
            const pressed = rating === id;
            return (
              <button
                key={id}
                type="button"
                aria-pressed={pressed}
                disabled={summary[id] === 0 && !pressed}
                onClick={() => onRating(id, !pressed)}
              >
                <i className={`inbox-fb__dot inbox-fb__bar-${id}`} aria-hidden="true" />
                {RATING_WORDS[id]} <span className="num">{count(summary[id])}</span>
              </button>
            );
          })}
        </div>
      </div>

      {canGoToList ? (
        <button type="button" className={`ops-tile inbox-fb__tile${owed}`} onClick={onGoToList}>
          {followUpBody}
        </button>
      ) : (
        <div className={`ops-tile inbox-fb__tile inbox-fb__tile--static${owed}`}>{followUpBody}</div>
      )}

      <div className="ops-tile inbox-fb__tile">
        <span className="ops-tile__label">Reward codes used</span>
        <span className="ops-tile__value">
          {count(summary.codes_used)}
          <span className="inbox-fb__of"> of {count(summary.codes_sent)} sent</span>
        </span>
        {solvedAsked > 0 && (
          <span className="ops-tile__note">
            Problems solved: {count(summary.solved)} of {count(solvedAsked)} asked
          </span>
        )}
      </div>
    </div>
  );
}

// ── The screen ──────────────────────────────────────────────────────────────

/** A saved file, named by the server. */
function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function InboxFeedback() {
  const [params, setParams] = useSearchParams();
  const narrow = useIsNarrow();
  const now = useNow();
  const ids = useId();
  const [defaultSince] = useState(() => cairoDay(DEFAULT_DAYS - 1));
  const filters = readFilters(params, defaultSince);
  const query = queryFor(filters);
  const untouched = params.toString() === "";

  // The newest address, for a write that must not undo another's.
  const latest = useRef(params);
  latest.current = params;
  const change = useCallback(
    (patch: Partial<Record<keyof Filters, string>>) => {
      const next = new URLSearchParams(latest.current);
      for (const [key, value] of Object.entries(patch)) {
        if (key === "since") {
          // Left alone it is the default; emptied it means no start.
          if (value === defaultSince) next.delete(key);
          else next.set(key, value);
        } else if (value === "") {
          next.delete(key);
        } else {
          next.set(key, value);
        }
      }
      latest.current = next;
      setParams(next, { replace: true });
    },
    [defaultSince, setParams],
  );

  // ── The sheet, its numbers and its menus ──
  const [rows, setRows] = useState<FeedbackRow[] | null>(null);
  const [next, setNext] = useState<number | null>(null);
  const [summary, setSummary] = useState<FeedbackSummary | null>(null);
  const [options, setOptions] = useState<FeedbackOptions | null>(null);
  const [failed, setFailed] = useState(false);
  // A refusal the server explained (dates out of range): its own words, not ours.
  const [refusal, setRefusal] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [off, setOff] = useState(false);
  const [readingMore, setReadingMore] = useState(false);
  const [moreFailed, setMoreFailed] = useState(false);
  // Which question is current, so an answer to an older one is ignored.
  const asked = useRef(0);

  useEffect(() => {
    const question = ++asked.current;
    setRows(null);
    setNext(null);
    setFailed(false);
    setRefusal(null);
    setMoreFailed(false);
    setReadingMore(false);
    api
      .get<FeedbackPage>(`/api/inbox/feedback?${query}`)
      .then((page) => {
        if (question !== asked.current) return;
        setRows(page.rows);
        setNext(page.next_offset);
        setSummary(page.summary);
        setOptions(page.options);
        // Whether the questions are being sent at all comes with the sheet
        // (no second read, and none that asks Shopify).
        setOff(page.enabled === false);
      })
      .catch((error: unknown) => {
        if (question !== asked.current) return;
        setFailed(true);
        setRefusal(error instanceof ApiError && error.status === 422 ? error.message : null);
      });
  }, [query, attempt]);

  function readMore() {
    if (next === null || readingMore) return;
    const question = asked.current;
    setReadingMore(true);
    setMoreFailed(false);
    api
      .get<FeedbackPage>(`/api/inbox/feedback?${query}&offset=${next}`)
      .then((page) => {
        if (question !== asked.current) return;
        setRows((held) => {
          const have = new Set((held ?? []).map((row) => row.id));
          return [...(held ?? []), ...page.rows.filter((row) => !have.has(row.id))];
        });
        setNext(page.next_offset);
        setSummary(page.summary);
      })
      .catch((error: unknown) => {
        if (question !== asked.current) return;
        setMoreFailed(true);
        setRefusal(error instanceof ApiError && error.status === 422 ? error.message : null);
      })
      .finally(() => {
        if (question === asked.current) setReadingMore(false);
      });
  }

  // ── To follow up: its own read, deaf to the filters ──
  const [waiting, setWaiting] = useState<FollowUpListPage | null>(null);
  const [waitingFailed, setWaitingFailed] = useState(false);
  const [waitingAttempt, setWaitingAttempt] = useState(0);
  const waitingAsked = useRef(0);
  const listHeading = useRef<HTMLHeadingElement>(null);
  // After an action the card may be gone; focus must not be left on nothing.
  const refocus = useRef(false);

  useEffect(() => {
    const question = ++waitingAsked.current;
    setWaitingFailed(false);
    api
      .get<FollowUpListPage>("/api/inbox/feedback/follow-up")
      .then((page) => {
        if (question !== waitingAsked.current) return;
        setWaiting(page);
      })
      .catch(() => {
        if (question !== waitingAsked.current) return;
        setWaitingFailed(true);
      });
  }, [waitingAttempt]);

  useEffect(() => {
    if (!refocus.current || waiting === null) return;
    refocus.current = false;
    const lost = !document.activeElement || document.activeElement === document.body;
    if (lost) listHeading.current?.focus();
  }, [waiting]);

  function recorded() {
    // The server's answer wins: the list, the cards and the sheet are read again.
    refocus.current = true;
    setWaitingAttempt((n) => n + 1);
    setAttempt((n) => n + 1);
  }

  function goToList() {
    const heading = listHeading.current;
    if (!heading) return;
    heading.scrollIntoView?.({ block: "start" });
    heading.focus({ preventScroll: true });
  }

  const [searchTyped, setSearchTyped] = useTyped(filters.q, (value) => change({ q: value }));

  // ── More filters: courier and reason, open by itself when one is set ──
  const moreSet = (filters.courier ? 1 : 0) + (filters.reason ? 1 : 0);
  const [moreOpen, setMoreOpen] = useState(moreSet > 0);
  useEffect(() => {
    if (filters.courier || filters.reason) setMoreOpen(true);
  }, [filters.courier, filters.reason]);

  const [downloading, setDownloading] = useState(false);
  const [downloadProblem, setDownloadProblem] = useState<string | null>(null);
  async function download() {
    setDownloading(true);
    setDownloadProblem(null);
    try {
      const file = await api.download(`/api/inbox/feedback/download?${query}`);
      save(file.blob, file.filename ?? `feedback-${cairoDay(0)}.xlsx`);
    } catch (error) {
      setDownloadProblem(
        error instanceof ApiError ? error.message : "The file could not be downloaded. Try again.",
      );
    } finally {
      setDownloading(false);
    }
  }

  const reasons = isRating(filters.rating) ? (options?.reasons[filters.rating] ?? []) : [];
  const couriers = options?.couriers ?? [];
  const courierMenu = filters.courier && !couriers.includes(filters.courier) ? [...couriers, filters.courier] : couriers;
  const stateMenu = options?.states ?? FOLLOW_UPS.map((id) => ({ id, title: FOLLOW_UP_WORDS[id] }));
  const hours = waiting?.reply_hours ?? DEFAULT_REPLY_HOURS;
  const answerLabel = `${ids}-answer`;
  const moreId = `${ids}-more`;

  return (
    <>
      <header className="page__head">
        <div className="page__title">
          <h1>Feedback</h1>
          <span className="page__subtitle">
            What customers said about their delivered orders, and where each follow-up stands
          </span>
        </div>
        <div className="inbox-fb__headacts">
          <Link className="inbox-btn inbox-btn--quiet" to="/inbox/feedback/setup">
            <InboxIcon name="settings" />
            Feedback setup
          </Link>
          <button
            type="button"
            className="inbox-btn inbox-btn--quiet inbox-fb__download"
            disabled={downloading || rows === null || rows.length === 0}
            onClick={() => void download()}
          >
            {downloading ? "Preparing the file…" : "Download"}
            <span className="visually-hidden"> these answers as a spreadsheet</span>
          </button>
        </div>
      </header>

      {off && (
        <p className="ops-banner ops-banner--off" role="status">
          <OpsIcon name="plug" />
          <span>Feedback questions are switched off. Nothing is being sent.</span>
        </p>
      )}

      {downloadProblem && (
        <p className="notice notice--refused inbox-said" role="alert">
          {downloadProblem}
        </p>
      )}

      {summary && (
        <Cards
          summary={summary}
          rating={filters.rating}
          old={rows === null}
          hours={hours}
          canGoToList={(waiting?.rows.length ?? 0) > 0}
          onRating={(rating, on) => change({ rating: on ? rating : "", reason: "" })}
          onGoToList={goToList}
        />
      )}

      {waitingFailed && (
        <p className="notice notice--refused inbox-fbq__problem" role="alert">
          Couldn't load who is waiting for a follow-up.{" "}
          <button type="button" className="ops-linkbtn" onClick={() => setWaitingAttempt((n) => n + 1)}>
            Try again
          </button>
        </p>
      )}

      {waiting && (
        <FollowUpList
          rows={waiting.rows}
          hours={hours}
          options={options}
          now={now}
          headingRef={listHeading}
          onChanged={recorded}
          feedbackOff={off}
        />
      )}

      <section className="panel inbox-fb" aria-labelledby={`${ids}-all`}>
        <div className="inbox-fb__head">
          <h2 id={`${ids}-all`}>All answers</h2>
          {summary && <span className="inbox-fb__count num">{count(summary.asked)} asked</span>}
        </div>
        <form className="inbox-fb__filters" role="search" aria-label="Filter the answers" onSubmit={(event) => event.preventDefault()}>
          <div className="inbox-fb__answers" role="group" aria-labelledby={answerLabel}>
            <span id={answerLabel} className="field__label">
              Answer
            </span>
            <div className="inbox-fb__seg">
              {ANSWERS.map((choice) => (
                <button
                  key={choice.id || "all"}
                  type="button"
                  className="ops-chip"
                  aria-pressed={filters.rating === choice.id}
                  onClick={() => change({ rating: choice.id, reason: "" })}
                >
                  {choice.title}
                </button>
              ))}
            </div>
          </div>
          <div className="inbox-fb__fields">
            <label className="field">
              <span className="field__label">From</span>
              <input
                className="input"
                type="date"
                value={filters.since}
                max={filters.until || undefined}
                onChange={(event) => change({ since: event.target.value })}
              />
            </label>
            <label className="field">
              <span className="field__label">To</span>
              <input
                className="input"
                type="date"
                value={filters.until}
                min={filters.since || undefined}
                onChange={(event) => change({ until: event.target.value })}
              />
            </label>
            <label className="field">
              <span className="field__label">Follow-up</span>
              <select
                className="input"
                value={filters.state}
                onChange={(event) => change({ state: event.target.value })}
              >
                <option value="">Any</option>
                {stateMenu.map((choice) => (
                  <option key={choice.id} value={choice.id}>
                    {choice.title}
                  </option>
                ))}
              </select>
            </label>
            <label className="field inbox-fb__search">
              <span className="field__label">Search</span>
              <input
                className="input"
                type="search"
                value={searchTyped}
                maxLength={120}
                autoComplete="off"
                placeholder="Order, name, phone or product"
                onChange={(event) => setSearchTyped(event.target.value)}
              />
            </label>
          </div>
          <div className="inbox-fb__morebar">
            <button
              type="button"
              className="ops-linkbtn inbox-fb__moretoggle"
              aria-expanded={moreOpen}
              aria-controls={moreId}
              onClick={() => setMoreOpen(!moreOpen)}
            >
              More filters{moreSet > 0 ? ` (${moreSet})` : ""}
              <span className="inbox-fb__caret" aria-hidden="true">
                {moreOpen ? "▴" : "▾"}
              </span>
            </button>
            {filters.product && (
              <button
                type="button"
                className="ops-chip inbox-fb__oldfilter"
                title="Remove this filter"
                onClick={() => change({ product: "" })}
              >
                <span dir="auto">Product: {filters.product}</span>
                <span className="visually-hidden">, remove this filter</span>
                <span aria-hidden="true">×</span>
              </button>
            )}
            {!untouched && (
              <button
                type="button"
                className="ops-linkbtn inbox-fb__clear"
                onClick={() => setParams({}, { replace: true })}
              >
                Clear filters
              </button>
            )}
          </div>
          <div id={moreId} className="inbox-fb__morefields" hidden={!moreOpen}>
            {moreOpen && (
              <>
                <label className="field">
                  <span className="field__label">Courier</span>
                  <select
                    className="input"
                    value={filters.courier}
                    onChange={(event) => change({ courier: event.target.value })}
                  >
                    <option value="">Any courier</option>
                    {courierMenu.map((courier) => (
                      <option key={courier} value={courier}>
                        {courier}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span className="field__label">Reason</span>
                  <select
                    className="input"
                    value={filters.reason}
                    disabled={!isRating(filters.rating)}
                    title={isRating(filters.rating) ? undefined : "Choose an answer first"}
                    onChange={(event) => change({ reason: event.target.value })}
                  >
                    <option value="">Any reason</option>
                    {reasons.map((choice) => (
                      <option key={choice.id} value={choice.id}>
                        {choice.title}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
          </div>
        </form>

        {failed && (
          <p className="notice notice--refused inbox-notice" role="alert">
            {refusal ?? (
              <>
                Couldn't load the feedback.{" "}
                <button type="button" className="ops-linkbtn" onClick={() => setAttempt(attempt + 1)}>
                  Try again
                </button>
              </>
            )}
          </p>
        )}

        {rows === null && !failed && <p className="loading">Loading…</p>}

        {rows !== null && rows.length === 0 && (
          <p className="empty">
            {untouched
              ? `No one has been asked in the last ${DEFAULT_DAYS} days.`
              : "Nothing matches these filters."}
          </p>
        )}

        {rows !== null && rows.length > 0 && (narrow ? <SheetCards rows={rows} options={options} /> : <SheetTable rows={rows} options={options} />)}

        {rows !== null && next !== null && (
          <div className="ops-foot inbox-fb__foot">
            <button type="button" className="ops-linkbtn" disabled={readingMore} onClick={readMore}>
              {readingMore ? "Loading more…" : "Show more"}
            </button>
            {moreFailed && (
              <span className="inbox-fb__problem" role="alert">
                {refusal ?? "Couldn't load more. Try again."}
              </span>
            )}
          </div>
        )}
      </section>
    </>
  );
}
