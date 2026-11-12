import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { ApiError, api } from "../../lib/api";
import { RATING_WORDS, REORDER_WORDS, feedbackStateNote, formatPhone } from "../../lib/inbox";
import type {
  FeedbackFollowUp,
  FeedbackOptions,
  FeedbackPage,
  FeedbackRating,
  FeedbackRow,
  FeedbackSettings,
  FeedbackSummary,
} from "../../lib/inbox";
import { OpsIcon, dayAndTime, dayMonth, useIsNarrow } from "../../components/OpsSource";
import "../operations/OperationsDashboard.css";
import "./Inbox.css";

/**
 * Inbox → Feedback: every answer to "how did your order go?", one row per
 * asked order, like the sheet Google Forms gives (ADR 0083, decision 6).
 *
 * Nothing in the sheet is written here: a chat is where a person follows an
 * unhappy answer up and presses *Resolved*. The sheet reads, filters and
 * downloads.
 *
 * Every filter lives in the address, so a filtered view can be linked and
 * survives a reload. No approved export draws this screen; it is built from
 * the Inbox's and Operations' own pieces (the Confirmations cards, the
 * Operations table and phone rows, the Chats chips).
 */

const RATINGS: FeedbackRating[] = ["loved", "okay", "unhappy"];
const FOLLOW_UPS: FeedbackFollowUp[] = ["needs_follow_up", "resolved", "reopened"];
const FOLLOW_UP_WORDS: Record<FeedbackFollowUp, string> = {
  needs_follow_up: "Needs follow-up",
  resolved: "Resolved",
  reopened: "Reopened",
};

/** The sheet opens on the last 30 days: today and the 29 before it. */
const DEFAULT_DAYS = 30;
/** A comment longer than this can be opened out; every one carries its full text as a tooltip. */
const LONG_COMMENT = 60;
const SEARCH_AFTER_MS = 300;

type Filters = {
  since: string;
  until: string;
  rating: FeedbackRating | "";
  reason: string;
  courier: string;
  state: FeedbackFollowUp | "";
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

// ── Filters in the address ──────────────────────────────────────────────────

function readFilters(params: URLSearchParams, defaultSince: string): Filters {
  const rating = params.get("rating");
  const state = params.get("state");
  const chosen = RATINGS.includes(rating as FeedbackRating) ? (rating as FeedbackRating) : "";
  const since = params.get("since");
  const until = params.get("until");
  return {
    // Left out means the default; given but empty means no start at all.
    since: params.has("since") ? (isDay(since) ? since : "") : defaultSince,
    until: isDay(until) ? until : "",
    rating: chosen,
    // A reason belongs to an answer: without one it is not asked for.
    reason: chosen ? (params.get("reason") ?? "") : "",
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

// ── What a row says ─────────────────────────────────────────────────────────

function titleCase(id: string): string {
  const words = id.replace(/_/g, " ");
  return `${words.charAt(0).toUpperCase()}${words.slice(1)}`;
}

function reasonTitle(row: FeedbackRow, options: FeedbackOptions | null): string | null {
  if (!row.reason) return null;
  const menu = row.rating ? options?.reasons[row.rating] : undefined;
  return menu?.find((choice) => choice.id === row.reason)?.title ?? titleCase(row.reason);
}

type Line = { text: string; tone?: "owed" };

/** Where the follow-up stands, a line each. */
function followUpLines(row: FeedbackRow): Line[] {
  const lines: Line[] = [];
  if (row.needs_follow_up) {
    lines.push({ text: "Needs follow-up", tone: "owed" });
  } else if (row.resolved_at) {
    lines.push({
      text: row.resolved_by_name
        ? `Resolved by ${row.resolved_by_name} on ${dayMonth(row.resolved_at)}`
        : `Resolved on ${dayMonth(row.resolved_at)}`,
    });
  }
  if (row.reopened_count > 0) lines.push({ text: `Reopened ${row.reopened_count}×` });
  if (row.solved !== null) lines.push({ text: `Solved: ${row.solved ? "yes" : "no"}` });
  if (row.reorder) lines.push({ text: `Order again: ${REORDER_WORDS[row.reorder]}` });
  return lines;
}

/** A quiet note on a question that did not go as it should have. */
function problemNote(row: FeedbackRow): string | null {
  const words = [feedbackStateNote(row.state), row.last_error].filter(Boolean);
  return words.length ? words.join(": ") : null;
}

function askedAt(row: FeedbackRow): string {
  const at = row.asked_at ?? row.sent_at;
  return at ? dayAndTime(at) : "—";
}

function Answer({ row }: { row: FeedbackRow }) {
  if (!row.rating) return <span className="ops-muted">No answer yet</span>;
  const tone = row.rating === "loved" ? "settled" : row.rating === "unhappy" ? "refused" : "plain";
  return <span className={`inbox-status inbox-status--${tone}`}>{RATING_WORDS[row.rating]}</span>;
}

function Lines({ lines }: { lines: Line[] }) {
  if (lines.length === 0) return <span className="ops-muted">—</span>;
  return (
    <>
      {lines.map((line) => (
        <span key={line.text} className={line.tone ? "inbox-fb__line inbox-fb__line--owed" : "inbox-fb__line"}>
          {line.text}
        </span>
      ))}
    </>
  );
}

function Code({ row }: { row: FeedbackRow }) {
  if (!row.code) return <span className="ops-muted">—</span>;
  return (
    <>
      <span className="num inbox-fb__code">{row.code}</span>
      <span className="inbox-fb__line ops-muted">
        {row.code_used_at ? (row.code_order_name ? `Used on ${row.code_order_name}` : "Used") : "Not used"}
      </span>
    </>
  );
}

/** What she wrote: two lines, the whole of it on a tap and as a tooltip. */
function Comment({ text }: { text: string | null }) {
  const [open, setOpen] = useState(false);
  if (!text) return <span className="ops-muted">—</span>;
  return (
    <>
      <span className={open ? "inbox-fb__comment inbox-fb__comment--open" : "inbox-fb__comment"} title={text}>
        {text}
      </span>
      {text.length > LONG_COMMENT && (
        <button type="button" className="ops-linkbtn inbox-fb__more" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Show less" : "Show all"}
        </button>
      )}
    </>
  );
}

function Note({ row }: { row: FeedbackRow }) {
  const note = problemNote(row);
  return note ? <span className="inbox-fb__line inbox-fb__note">{note}</span> : null;
}

function Customer({ row }: { row: FeedbackRow }) {
  return (
    <>
      <span className="inbox-fb__name">{row.customer_name?.trim() || <span className="ops-muted">No name</span>}</span>
      <span className="inbox-fb__line ops-muted num">{formatPhone(row.phone) || "—"}</span>
    </>
  );
}

const productsOf = (row: FeedbackRow) => row.products.join(", ");

function Products({ row }: { row: FeedbackRow }) {
  const products = productsOf(row);
  if (!products) return <span className="ops-muted">—</span>;
  return (
    <span className="inbox-fb__products" title={products}>
      {products}
    </span>
  );
}

function SheetTable({ rows, options }: { rows: FeedbackRow[]; options: FeedbackOptions | null }) {
  return (
    <div className="inbox-fb__scroll">
      <table className="ops-table inbox-fb__table">
        <caption className="visually-hidden">Answers to the delivery question, newest first</caption>
        <thead>
          <tr>
            <th scope="col">Asked</th>
            <th scope="col">Customer</th>
            <th scope="col">Order</th>
            <th scope="col">Products</th>
            <th scope="col">Courier</th>
            <th scope="col">Answer</th>
            <th scope="col">Reason</th>
            <th scope="col">Comment</th>
            <th scope="col">Follow-up</th>
            <th scope="col">Code</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td className="num inbox-fb__nowrap">
                {askedAt(row)}
                <Note row={row} />
              </td>
              <td>
                <Customer row={row} />
              </td>
              <td className="num">{row.order_name ?? row.order_id}</td>
              <td>
                <Products row={row} />
              </td>
              <td>{row.courier ?? <span className="ops-muted">—</span>}</td>
              <td>
                <Answer row={row} />
              </td>
              <td>{reasonTitle(row, options) ?? <span className="ops-muted">—</span>}</td>
              <td className="inbox-fb__commentcell">
                <Comment text={row.comment} />
              </td>
              <td>
                <Lines lines={followUpLines(row)} />
              </td>
              <td>
                <Code row={row} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** On a phone each answer is a card, never a row to scroll sideways. */
function SheetCards({ rows, options }: { rows: FeedbackRow[]; options: FeedbackOptions | null }) {
  return (
    <ul className="ops-rows">
      {rows.map((row) => {
        const reason = reasonTitle(row, options);
        const lines = followUpLines(row);
        return (
          <li key={row.id} className="inbox-fb__card">
            <div className="ops-rows__top">
              <span className="num">{row.order_name ?? row.order_id}</span>
              <span className="ops-muted num">{askedAt(row)}</span>
            </div>
            <div className="inbox-fb__who">
              <Customer row={row} />
            </div>
            <div className="inbox-fb__said">
              <Answer row={row} />
              {reason && <span>{reason}</span>}
            </div>
            {row.comment && (
              <div className="inbox-fb__block">
                <Comment text={row.comment} />
              </div>
            )}
            {(row.products.length > 0 || row.courier) && (
              <div className="inbox-fb__block ops-muted">
                {[productsOf(row), row.courier].filter(Boolean).join(" · ")}
              </div>
            )}
            {lines.length > 0 && (
              <div className="inbox-fb__block">
                <Lines lines={lines} />
              </div>
            )}
            {row.code && (
              <div className="inbox-fb__block">
                <Code row={row} />
              </div>
            )}
            <Note row={row} />
          </li>
        );
      })}
    </ul>
  );
}

// ── The summary row ─────────────────────────────────────────────────────────

type TileFilter = { rating: FeedbackRating } | { state: FeedbackFollowUp } | null;

const TILES: { key: keyof FeedbackSummary; label: string; filter: TileFilter }[] = [
  { key: "asked", label: "Asked", filter: null },
  { key: "answered", label: "Answered", filter: null },
  { key: "loved", label: "Loved it", filter: { rating: "loved" } },
  { key: "okay", label: "It was okay", filter: { rating: "okay" } },
  { key: "unhappy", label: "Not happy", filter: { rating: "unhappy" } },
  { key: "needs_follow_up", label: "Needs follow-up", filter: { state: "needs_follow_up" } },
  { key: "solved", label: "Solved", filter: null },
  { key: "codes_sent", label: "Codes sent", filter: null },
  { key: "codes_used", label: "Codes used", filter: null },
];

function Tiles({
  summary,
  filters,
  old,
  onFilter,
}: {
  summary: FeedbackSummary;
  filters: Filters;
  /** The numbers are from the last question, while the next is on its way. */
  old: boolean;
  onFilter: (tile: NonNullable<TileFilter>, on: boolean) => void;
}) {
  return (
    <div
      className={old ? "ops-tiles inbox-fb__tiles ops-tiles--old" : "ops-tiles inbox-fb__tiles"}
      role="group"
      aria-label="Summary of these answers"
    >
      {TILES.map(({ key, label, filter }) => {
        const count = summary[key];
        const body = (
          <>
            <span className="ops-tile__label">{label}</span>
            <span className="ops-tile__value">{count.toLocaleString("en-US")}</span>
            {key === "asked" && (summary.not_reached ?? 0) > 0 && (
              <span className="ops-tile__note ops-muted">
                {summary.not_reached.toLocaleString("en-US")} could not be reached
              </span>
            )}
          </>
        );
        const pressed =
          filter !== null &&
          ("rating" in filter ? filters.rating === filter.rating : filters.state === filter.state);
        // A card with nothing behind it cannot be opened, unless it is the
        // one that is already narrowing the sheet: that one switches off.
        if (filter === null || (count === 0 && !pressed)) {
          return (
            <div
              key={key}
              className={count === 0 ? "ops-tile ops-tile--zero inbox-fb__tile inbox-fb__tile--static" : "ops-tile inbox-fb__tile inbox-fb__tile--static"}
            >
              {body}
            </div>
          );
        }
        return (
          <button
            key={key}
            type="button"
            className="ops-tile inbox-fb__tile"
            aria-pressed={pressed}
            onClick={() => onFilter(filter, !pressed)}
          >
            {body}
          </button>
        );
      })}
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

  const [rows, setRows] = useState<FeedbackRow[] | null>(null);
  const [next, setNext] = useState<number | null>(null);
  const [summary, setSummary] = useState<FeedbackSummary | null>(null);
  const [options, setOptions] = useState<FeedbackOptions | null>(null);
  const [failed, setFailed] = useState(false);
  // A refusal the server explained (dates out of range): its own words, not ours.
  const [refusal, setRefusal] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
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

  // Whether the questions are being sent at all. Read apart from the sheet,
  // and never waited for: the sheet is the same either way.
  const [off, setOff] = useState(false);
  useEffect(() => {
    let current = true;
    api
      .get<FeedbackSettings>("/api/inbox/feedback/settings")
      .then((settings) => {
        if (current) setOff(settings.enabled === false);
      })
      .catch(() => undefined);
    return () => {
      current = false;
    };
  }, []);

  const [productTyped, setProductTyped] = useTyped(filters.product, (value) => change({ product: value }));
  const [searchTyped, setSearchTyped] = useTyped(filters.q, (value) => change({ q: value }));

  function filterByTile(tile: NonNullable<TileFilter>, on: boolean) {
    if ("rating" in tile) change({ rating: on ? tile.rating : "", reason: "" });
    else change({ state: on ? tile.state : "" });
  }

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

  const reasons = filters.rating ? (options?.reasons[filters.rating] ?? []) : [];
  const couriers = options?.couriers ?? [];
  const courierMenu = filters.courier && !couriers.includes(filters.courier) ? [...couriers, filters.courier] : couriers;
  const ratingMenu = options?.ratings ?? RATINGS.map((id) => ({ id, title: RATING_WORDS[id] }));
  const stateMenu = options?.states ?? FOLLOW_UPS.map((id) => ({ id, title: FOLLOW_UP_WORDS[id] }));

  return (
    <>
      <header className="page__head">
        <div className="page__title">
          <h1>Feedback</h1>
          <span className="page__subtitle">
            What customers said about their delivered orders, and where each follow-up stands
          </span>
        </div>
        <button
          type="button"
          className="inbox-btn inbox-btn--quiet"
          disabled={downloading || rows === null || rows.length === 0}
          onClick={() => void download()}
        >
          {downloading ? "Preparing the file…" : "Download"}
          <span className="visually-hidden"> these answers as a spreadsheet</span>
        </button>
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
        <Tiles summary={summary} filters={filters} old={rows === null} onFilter={filterByTile} />
      )}

      <section className="panel inbox-fb" aria-label="Answers">
        <form className="inbox-fb__filters" role="search" aria-label="Filter the answers" onSubmit={(event) => event.preventDefault()}>
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
            <span className="field__label">Answer</span>
            <select
              className="input"
              value={filters.rating}
              onChange={(event) => change({ rating: event.target.value, reason: "" })}
            >
              <option value="">Any answer</option>
              {ratingMenu.map((choice) => (
                <option key={choice.id} value={choice.id}>
                  {choice.title}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field__label">Reason</span>
            <select
              className="input"
              value={filters.reason}
              disabled={!filters.rating}
              onChange={(event) => change({ reason: event.target.value })}
            >
              <option value="">{filters.rating ? "Any reason" : "Choose an answer first"}</option>
              {reasons.map((choice) => (
                <option key={choice.id} value={choice.id}>
                  {choice.title}
                </option>
              ))}
            </select>
          </label>
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
          <label className="field">
            <span className="field__label">Product</span>
            <input
              className="input"
              type="search"
              value={productTyped}
              maxLength={120}
              autoComplete="off"
              placeholder="Part of a product name"
              onChange={(event) => setProductTyped(event.target.value)}
            />
          </label>
          <label className="field">
            <span className="field__label">Search</span>
            <input
              className="input"
              type="search"
              value={searchTyped}
              maxLength={120}
              autoComplete="off"
              placeholder="Order, name or phone"
              onChange={(event) => setSearchTyped(event.target.value)}
            />
          </label>
          {!untouched && (
            <button
              type="button"
              className="ops-linkbtn inbox-fb__clear"
              onClick={() => setParams({}, { replace: true })}
            >
              Clear filters
            </button>
          )}
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
