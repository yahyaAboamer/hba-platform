import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { Link, useLocation, useSearchParams, useNavigate } from "react-router-dom";

import { Money } from "../../components/Money";
import { api } from "../../lib/api";
import { PAY_TYPE } from "../../lib/payouts";
import { formatMonth, shortMonth } from "../../lib/money";
import "./Affiliates.css";

/** The approved roster's segments. */
export type Segment = "active" | "applications" | "invitations" | "inactive";

/**
 * The approved roster's four filters, in its words and its order.
 *
 * *Invitations* is a filter rather than a panel above the table: the export
 * turns the same table into one row per invitation, so an invitation nobody
 * has opened sits exactly where the model it would become will sit. It used
 * to be a collapsible block over the list, and seven of them once buried the
 * four models this screen exists to show.
 *
 * *Inactive* covers paused and archived alike - both are somebody no longer
 * earning, and the export has one word for them.
 */
export const SEGMENTS: { key: Segment; label: string }[] = [
  { key: "active", label: "Active" },
  { key: "applications", label: "Applications" },
  { key: "invitations", label: "Invitations" },
  { key: "inactive", label: "Inactive" },
];

/** The export's status words for a roster row, and their tone. */
export const ROSTER_STATUS: Record<string, { label: string; tone: string }> = {
  pending: { label: "Application", tone: "owed" },
  active: { label: "Active", tone: "approved" },
  // ADR 0052: all three sit under the *Inactive* filter, and each says which
  // kind of inactive it is - they mean different things to her.
  inactive: { label: "Paused", tone: "owed" },
  archived: { label: "Archived", tone: "quiet" },
  declined: { label: "Declined", tone: "quiet" },
};

/** The export lists twelve to a page. */
const ROSTER_PAGE = 12;

export type Affiliate = {
  id: number;
  name: string;
  phone: string | null;
  status: "pending" | "active" | "inactive" | "archived" | "declined";
  account_kind: "model" | "house";
  is_payable: boolean;
  created_at: string | null;
  archived_at: string | null;
  has_verified_code?: boolean;
  has_terms?: boolean;
  /** Somewhere to send her money, or paid abroad by arrangement. */
  has_payout?: boolean;
  /** The raw arrangement she is on that month, labelled by `PAY_TYPE`. */
  arrangement?: string | null;
  /** The code they sell under this month, if they have one registered. */
  code?: string | null;
  /** The month the sales and content figures below belong to. */
  month?: string;
  /** Sales she generated that month — the models' own leaderboard figure
   *  (D03), not a payout and not anything owed to her. */
  sales_piastres?: number;
  uses?: number;
  /** What was asked of her that month and what she produced. `null` when
   *  nobody asked, which is not the same as having produced none. */
  content?: {
    required_videos: number | null;
    required_stories: number | null;
    actual_videos: number | null;
    actual_stories: number | null;
    last_update: string | null;
  } | null;
  /**
   * The month she actually started with HBA (H01).
   *
   * `null` means nobody has recorded it, which is a real answer and not a
   * missing one - her month list falls back to a derivation from her earliest
   * order, and the profile says so rather than showing a date it guessed.
   */
  collaboration_start_month?: string | null;
  /** Optional, hers to write and ours to read (A05). */
  height_cm?: number | null;
  weight_kg?: number | null;
  /**
   * Her one address (D07): the one she signs in with, and the one marketing
   * reaches her on. There is no second contact email, so screens say which
   * this is rather than calling it "email".
   */
  email?: string;
};

/** An invitation nobody has opened yet. Not a model, and still ours. */
export type Invited = {
  id: number;
  email: string;
  expires_at?: string;
  expired: boolean;
  /** Cancelled on purpose, as opposed to simply lapsed. */
  withdrawn: boolean;
  created_at: string;
};

/**
 * One invitation per person: the live one, else the newest.
 *
 * Resending issues a new invitation and lapses the old one, so the server
 * returns both. Listing both showed one address as *Link expired* and
 * *Awaiting application* at once, and counted her twice.
 */
export function onePerAddress(rows: Invited[]): Invited[] {
  const kept = new Map<string, Invited>();
  for (const row of rows) {
    const key = row.email.trim().toLowerCase();
    const held = kept.get(key);
    const live = !row.expired && !row.withdrawn;
    const heldLive = held && !held.expired && !held.withdrawn;
    if (!held || (live && !heldLive) || (live === heldLive && row.created_at > held.created_at)) {
      kept.set(key, row);
    }
  }
  return [...kept.values()];
}

/**
 * When an invitation went out, as the export writes it: the date in full,
 * *2 November 2026* (`i.sent`). It used to say *today at 14:20*, which the
 * export does not, and which is wrong the moment the screen is left open.
 */
export function formatSentAt(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

type View = "table" | "cards";

/** §12.5's breakpoint, in one place so the CSS and the component agree. */
const NARROW = "(max-width: 640px)";

/**
 * Whether the viewport is too narrow for a table.
 *
 * This has to be JavaScript rather than a `display: none` rule, because which
 * of the two layouts is *rendered* is component state. Hiding the table in CSS
 * while the cards were never mounted left a phone with a heading and nothing
 * under it — a blank screen, which is the one thing a list must never be.
 */
function useIsNarrow(): boolean {
  return useSyncExternalStore(
    (notify) => {
      const query = window.matchMedia(NARROW);
      query.addEventListener("change", notify);
      return () => query.removeEventListener("change", notify);
    },
    () => window.matchMedia(NARROW).matches,
    () => false,
  );
}

export const STATUS_LABEL: Record<string, string> = {
  pending: "Waiting to be approved",
  active: "Approved",
  inactive: "Paused",
  archived: "No longer active",
};

/**
 * What needs doing before this affiliate's month can be trusted.
 *
 * The two are **not** the same severity, and saying so would be a lie in
 * either direction:
 *
 * - *No pay terms* genuinely stops payroll. The month cannot be approved.
 * - *Code unconfirmed* stops nothing. Orders carrying the code are still
 *   attributed. What it means is that Shopify has never agreed the code
 *   exists, so it may have been mistyped or never created — in which case no
 *   order will ever carry it, and the first symptom is silence.
 *
 * A house account is never paid, so pay terms it will never use are not
 * missing. An archived affiliate is not meant to be earning at all.
 */
export function missingSetup(row: Affiliate): string[] {
  if (row.status === "archived" || row.status === "declined") return [];

  const missing: string[] = [];
  if (row.is_payable && row.has_terms === false) missing.push("no pay terms");
  if (row.has_verified_code === false) missing.push("code unconfirmed");
  // Admin Models audit: nothing can be sent to her without it.
  if (row.is_payable && row.has_payout === false) missing.push("no payout details");
  return missing;
}

/** Somebody who accepted her invitation and has not applied yet. */
export type Joined = {
  account_id: number;
  email: string;
  name: string | null;
  joined_at: string | null;
};

/**
 * *Needs you* (admin Models audit): the four things that stop a model earning
 * or being paid, each a count that is also a filter. Archived and declined
 * models are not expected to be set up, so they are never counted.
 */
export type Need = "applications" | "code" | "terms" | "payout";

export const NEEDS: { key: Need; label: string; tone: string }[] = [
  { key: "applications", label: "applications to review", tone: "info" },
  { key: "code", label: "codes Shopify hasn't confirmed", tone: "refused" },
  { key: "terms", label: "with no pay terms", tone: "owed" },
  { key: "payout", label: "with no payout details", tone: "owed" },
];

export function needs(row: Affiliate, need: Need): boolean {
  if (row.status === "archived" || row.status === "declined") return false;
  switch (need) {
    case "applications":
      return row.status === "pending";
    case "code":
      return row.has_verified_code === false;
    case "terms":
      return row.is_payable && row.has_terms === false;
    case "payout":
      return row.is_payable && row.has_payout === false;
  }
}

export type Sort = "name" | "sales" | "content";

/** Content done, as a fraction of what was asked; nothing asked sorts last. */
function contentDone(row: Affiliate): number {
  const content = row.content;
  if (!content || content.required_videos === null) return 2;
  const asked = (content.required_videos ?? 0) + (content.required_stories ?? 0);
  const done = (content.actual_videos ?? 0) + (content.actual_stories ?? 0);
  return asked === 0 ? 2 : done / asked;
}

export function sortRoster(rows: Affiliate[], sort: Sort): Affiliate[] {
  const sorted = [...rows];
  if (sort === "sales") sorted.sort((a, b) => (b.sales_piastres ?? 0) - (a.sales_piastres ?? 0));
  else if (sort === "content") sorted.sort((a, b) => contentDone(a) - contentDone(b));
  else sorted.sort((a, b) => a.name.localeCompare(b.name));
  return sorted;
}

/** The chosen rows as a spreadsheet, for the selection's export. */
export function rosterCsv(rows: Affiliate[]): string {
  const cell = (value: unknown) => {
    let text = value === null || value === undefined ? "" : String(value);
    // A name she typed herself must never run as a formula in the sheet it
    // is opened in: a leading = + - @ (or tab, return) is neutralised.
    if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const head = ["Name", "Code", "Status", "Month", "Sales (EGP)", "Content", "Terms", "Email", "Phone"];
  const lines = rows.map((row) =>
    [
      row.name,
      row.code ?? "",
      (ROSTER_STATUS[row.status] ?? ROSTER_STATUS.inactive).label,
      row.month ?? "",
      ((row.sales_piastres ?? 0) / 100).toFixed(2),
      contentSummary(row),
      row.arrangement ? PAY_TYPE[row.arrangement] ?? row.arrangement : "",
      row.email ?? "",
      row.phone ?? "",
    ]
      .map(cell)
      .join(","),
  );
  return [head.join(","), ...lines].join("\n");
}

/**
 * Who is on the programme.
 *
 * The decision this page supports is *who needs me*, so the figures at the top
 * are the ones that need an answer, not a count of everything (§12.3,
 * principle 5). "How many affiliates exist" is already next to the title, and
 * a second figure you can reach by subtracting two others earns no space.
 */
/**
 * The roster, narrowed to a segment and a search.
 *
 * **Search covers name and code**, because those are the two things anybody
 * knows a model by: HBA thinks of her by name, and an order knows her only by
 * the code on it. Matching one and not the other means the search fails
 * exactly when somebody is holding an order and asking whose it is.
 */
export function rosterMatches(
  rows: Affiliate[],
  segment: Segment,
  query: string,
): Affiliate[] {
  const needle = query.trim().toLowerCase();
  return rows.filter((row) => {
    // Invitations are not models; that filter lists them instead.
    if (segment === "invitations") return false;
    if (segment === "applications" && row.status !== "pending") return false;
    if (segment === "active" && row.status !== "active") return false;
    if (
      segment === "inactive" &&
      row.status !== "inactive" &&
      row.status !== "archived" &&
      row.status !== "declined"
    ) {
      return false;
    }
    return matchesSearch(row, needle);
  });
}

/** Name, code, or her sign-in address - often all somebody has in hand. */
export function matchesSearch(row: Affiliate, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return (
    row.name.toLowerCase().includes(needle) ||
    (row.code ?? "").toLowerCase().includes(needle) ||
    (row.email ?? "").toLowerCase().includes(needle)
  );
}

/**
 * *5 / 6 videos*, or why there is no figure.
 *
 * **Nobody asked is not the same as nothing produced**, and the roster has to
 * keep them apart for the same reason Home does: the first is HBA's own
 * omission and the second is a fact about her month.
 */
export function contentSummary(row: Affiliate): string {
  const content = row.content;
  if (!content || content.required_videos === null) return "Nothing asked for";
  const videos = `${content.actual_videos ?? 0}/${content.required_videos}`;
  const stories = `${content.actual_stories ?? 0}/${content.required_stories ?? 0}`;
  return `${videos} · ${stories}`;
}

export function Affiliates() {
  const [rows, setRows] = useState<Affiliate[] | null>(null);
  const [invited, setInvited] = useState<Invited[]>([]);
  const [error, setError] = useState<string | null>(null);
  /**
   * The approved roster filters and search.
   *
   * Both are applied here rather than asked of the server: this list is a
   * whole roster of about twenty people, and a round trip per keystroke would
   * be slower than the filter and would make an empty result ambiguous —
   * nobody matches, or the answer has not come back yet.
   */
  /**
   * **In the URL, not in the component.** A roster narrowed to one segment and
   * a search is a place somebody is working; opening a model and pressing back
   * used to drop them at the top of the unfiltered list, which is the moment a
   * screen stops being usable for the job it exists for.
   *
   * It also makes the view shareable — *the two waiting to be approved* is a
   * link now, rather than four words of instruction.
   */
  const [params, setParams] = useSearchParams();
  const arrivedWith = (useLocation().state as { notice?: string } | null)?.notice ?? null;
  // An address from before the filters were renamed (*all*, *waiting*)
  // lands on Active rather than on an empty table.
  const asked = params.get("segment");
  const segment: Segment = SEGMENTS.some((option) => option.key === asked)
    ? (asked as Segment)
    : "active";
  const navigate = useNavigate();
  const [page, setPage] = useState(0);
  const query = params.get("q") ?? "";
  // Admin Models audit: a *Needs you* filter, a sort and a month, kept in the
  // address like the segment and search so back and a shared link keep them.
  const askedNeed = params.get("need");
  const need: Need | null = NEEDS.some((option) => option.key === askedNeed)
    ? (askedNeed as Need)
    : null;
  const askedSort = params.get("sort");
  const sort: Sort = askedSort === "sales" || askedSort === "content" ? askedSort : "name";
  const chosenMonth = params.get("month") ?? "";
  const [joined, setJoined] = useState<Joined[]>([]);
  /** The working month, as the server answered with no month asked. */
  const [latest, setLatest] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  /** Phone cards show twelve at a time, like the table's pages. */
  const [cardLimit, setCardLimit] = useState(ROSTER_PAGE);
  const [reminded, setReminded] = useState<Record<number, string>>({});

  const narrow = useCallback(
    (next: { segment?: Segment; q?: string; need?: Need | ""; sort?: Sort; month?: string }) => {
      setParams(
        (previous) => {
          const updated = new URLSearchParams(previous);
          for (const [key, value] of Object.entries(next)) {
            // An empty value or a default leaves no trace: a URL carrying
            // `?q=` says a search happened and found everything.
            if (!value || value === "active" || (key === "sort" && value === "name")) {
              updated.delete(key);
            } else updated.set(key, value);
          }
          return updated;
        },
        { replace: true },
      );
    },
    [setParams],
  );
  const isNarrow = useIsNarrow();
  // The toggle is a preference, not an override: a table does not fit on a
  // phone however firmly somebody asked for one.
  // The export has one layout, a table; a phone gets cards because a table
  // does not fit there (§12.3's point), with no switch between them (D).
  const shown: View = isNarrow ? "cards" : "table";
  // A *Needs you* count filters across segments - an application and an
  // active model can both be missing payout details - so it replaces the
  // segment rather than narrowing inside it.
  const matched = rows
    ? need
      ? rows.filter((row) => needs(row, need) && matchesSearch(row, query))
      : rosterMatches(rows, segment, query)
    : [];
  const visible = sortRoster(matched, sort);
  // A new filter or a new search starts at the first page. Resetting on the
  // filter alone let a search typed on page 2 narrow the list to one page and
  // leave an empty table with no pager to get back.
  useEffect(() => {
    setPage(0);
    setCardLimit(ROSTER_PAGE);
    // A selection belongs to the view it was made in; carrying it across a
    // filter would export rows nobody can see.
    setSelected(new Set());
  }, [segment, query, need, sort, chosenMonth]);
  // The column header names the month it is showing, so a figure can never be
  // read as "this month" when the list is answering for another one.
  // *Sept sales*, as the export's `monthShort` writes it. The full month
  // name does not fit a 130px uppercase header and ran into the next column.
  const monthShort = rows?.[0]?.month ? shortMonth(rows[0].month) : "Month";

  // Archived models are always fetched. Fetching them only when Inactive was
  // chosen made that chip's count jump the moment it was pressed; the
  // segments already sort rows by status, so nobody else sees them.
  const reload = useCallback(() => {
    setError(null);
    api
      .get<{ affiliates: Affiliate[]; invited: Invited[]; joined?: Joined[]; working_month?: string }>(
        `/api/affiliates?include_archived=true${chosenMonth ? `&month=${encodeURIComponent(chosenMonth)}` : ""}`,
      )
      .then((body) => {
        setRows(body.affiliates);
        setInvited(onePerAddress(body.invited ?? []));
        setJoined(body.joined ?? []);
        setSelected(new Set());
        // The month picker counts back from the working month, which the
        // server names even when the link asked for another one.
        setLatest(body.working_month ?? body.affiliates[0]?.month ?? null);
      })
      .catch((caught) => setError(caught.message));
  }, [chosenMonth]);

  /** Twelve months back from the working month, newest first. */
  const monthChoices = latest
    ? Array.from({ length: 12 }, (_, back) => {
        const [year, month] = latest.split("-").map(Number);
        const date = new Date(Date.UTC(year, month - 1 - back, 1));
        return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
      })
    : [];

  function remind(person: Joined) {
    setReminded({ ...reminded, [person.account_id]: "Sending…" });
    api
      .post<{ emailed: boolean }>(`/api/affiliates/joined/${person.account_id}/remind`)
      .then((result) =>
        setReminded((now) => ({
          ...now,
          [person.account_id]: result.emailed ? "Reminder emailed" : "Email is off - tell her yourself",
        })),
      )
      .catch((caught) =>
        setReminded((now) => ({ ...now, [person.account_id]: (caught as Error).message })),
      );
  }

  function exportSelected() {
    const chosen = (rows ?? []).filter((row) => selected.has(row.id));
    // The byte-order mark tells Excel the file is UTF-8, or Arabic names
    // arrive garbled.
    const blob = new Blob(["﻿", rosterCsv(chosen)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `hba-models-${rows?.[0]?.month ?? "export"}.csv`;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function toggleSelected(id: number) {
    setSelected((now) => {
      const next = new Set(now);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  useEffect(reload, [reload]);

  // Live is what somebody is still waiting on; dead is history that should
  // not be in the way of it.
  // Live first, then lapsed and withdrawn - the export lists expired links in
  // the same table, and the ones somebody is still waiting on belong on top.
  const needle = query.trim().toLowerCase();
  const invitations = [
    ...invited.filter((row) => !row.expired),
    ...invited.filter((row) => row.expired),
  ].filter((row) => !needle || row.email.toLowerCase().includes(needle));
  const paged = visible.slice(page * ROSTER_PAGE, (page + 1) * ROSTER_PAGE);
  const showingInvitations = segment === "invitations" && !need;
  const joinedShown = joined.filter(
    (person) => !needle || person.email.toLowerCase().includes(needle) || (person.name ?? "").toLowerCase().includes(needle),
  );

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Models</h1>
          {rows && (
            <span className="page__subtitle">
              {/* The export's own subtitle, which is the *active* count and
               *  nothing else: `this.activeModels().length + " active"`. It
               *  said "19 of 22" here until 23 September - a count of what a
               *  filter was showing - and that is a different fact. How many
               *  models are collaborating does not change when somebody types
               *  in the search box, and the pager below already says what is
               *  on screen, in the export's words and with its suffix. */}
              {`${rosterMatches(rows, "active", "").length} active`}
            </span>
          )}
        </div>
      </div>

      {/*
       * *Needs you* (admin Models audit): who needs something from you, as
       * counts that are also filters. Only what is actually outstanding is
       * drawn, so a clean roster shows nothing here at all.
       */}
      {rows && NEEDS.some((option) => rows.some((row) => needs(row, option.key))) && (
        <div className="affiliates__needs" role="group" aria-label="Needs you">
          {NEEDS.map((option) => {
            const count = rows.filter((row) => needs(row, option.key)).length;
            if (count === 0) return null;
            return (
              <button
                key={option.key}
                type="button"
                className={`affiliates__need affiliates__need--${option.tone}${need === option.key ? " affiliates__need--on" : ""}`}
                aria-pressed={need === option.key}
                onClick={() => narrow({ need: need === option.key ? "" : option.key })}
              >
                <strong>{count}</strong>
                <span>{count === 1 ? option.label.replace(/^applications/, "application").replace(/^codes/, "code") : option.label}</span>
              </button>
            );
          })}
        </div>
      )}

      {/*
       * **One row, as the export draws it.** The filters take the left, the
       * search and the primary act take the right. This screen had the acts
       * up in the page heading and the filters on a line of their own
       * underneath, which is two toolbars for one table.
       */}
      <div className="affiliates__bar">
        <div className="affiliates__segments" role="group" aria-label="Segments">
          {SEGMENTS.map((option) => (
            <button
              key={option.key}
              type="button"
              className={!need && segment === option.key ? "chip chip--on" : "chip"}
              onClick={() => narrow({ segment: option.key, need: "" })}
              aria-pressed={!need && segment === option.key}
            >
              {option.label}
              {rows && (
                <span className="affiliates__segment-count">
                  {option.key === "invitations"
                    ? invited.length + joined.length
                    : rosterMatches(rows, option.key, "").length}
                </span>
              )}
            </button>
          ))}
        </div>

        <div className="affiliates__acts">
          <input
            type="search"
            className="input input--search"
            value={query}
            onChange={(event) => narrow({ q: event.target.value })}
            placeholder="Search name, code or email"
            aria-label="Search models by name, code or email"
          />


          {/* Brand codes are added under Settings → Brand codes, their one
              home (owner, 30 September: D2) - here, beside *Invite a model*,
              the button read as registering a model's code. */}

          {/*
           * The primary action on this screen, and it used to have no home at
           * all: inviting a model was neither here nor in Settings, whose role
           * list offers only staff. Phase 8 built the whole onboarding flow
           * and nothing could start it.
           *
           * It opens a screen now rather than a modal, because the export
           * gives the act one — and because the applications waiting to be
           * reviewed and the links already out belong beside it.
           */}
          <Link className="button button--primary" to="/affiliates/models/invite">
            Invite a model
          </Link>
        </div>
      </div>

      {/* Admin Models audit: which month the figures are for, and the order. */}
      {rows !== null && rows.length > 0 && !showingInvitations && (
        <div className="affiliates__view">
          <label className="affiliates__view-field">
            <span>Month</span>
            <select
              className="input affiliates__select"
              value={chosenMonth || latest || ""}
              onChange={(event) =>
                narrow({ month: event.target.value === latest ? "" : event.target.value })
              }
            >
              {monthChoices.map((month) => (
                <option key={month} value={month}>
                  {formatMonth(month)}
                </option>
              ))}
            </select>
          </label>
          <label className="affiliates__view-field">
            <span>Sort</span>
            <select
              className="input affiliates__select"
              value={sort}
              onChange={(event) => narrow({ sort: event.target.value as Sort })}
            >
              <option value="name">Name, A–Z</option>
              <option value="sales">Sales, highest first</option>
              <option value="content">Content, least done first</option>
            </select>
          </label>
          {need && (
            <button type="button" className="button button--row" onClick={() => narrow({ need: "" })}>
              Show everyone
            </button>
          )}
        </div>
      )}

      {selected.size > 0 && (
        <div className="affiliates__bulk" role="region" aria-label="Selected models">
          <strong>{selected.size} selected</strong>
          <button type="button" className="button button--row" onClick={exportSelected}>
            Export to spreadsheet
          </button>
          <button type="button" className="button button--row" onClick={() => setSelected(new Set())}>
            Clear
          </button>
        </div>
      )}

      {/* First run: nobody yet, so the screen explains how somebody arrives. */}
      {rows !== null && rows.length === 0 && invited.length === 0 && joined.length === 0 && (
        <div className="surface affiliates__first">
          <h2>No models yet</h2>
          <p>Models join by invitation. Here is what happens:</p>
          <ol className="affiliates__first-steps">
            <li>
              <strong>Invite</strong> You send a link to her email.
            </li>
            <li>
              <strong>She applies</strong> Her name and phone, her discount code, and where to pay her.
            </li>
            <li>
              <strong>You approve</strong> Check her code with Shopify, set her pay terms, approve.
            </li>
          </ol>
          <Link className="button button--primary" to="/affiliates/models/invite">
            Invite your first model
          </Link>
        </div>
      )}

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {/* Arriving from an erase (ADR 0052): her page is gone, so the
          confirmation is said here. */}
      {arrivedWith && (
        <p className="notice" role="status">
          {arrivedWith}
        </p>
      )}

      {/* Not while the error above is showing: a failed load is not still loading. */}
      {rows === null && !error && <p className="empty">Loading…</p>}

      {/*
       * Admin Models audit: she accepted her invitation and made an account
       * but never applied - no longer an invitation, not yet a model, so she
       * was on neither list. On top, because a reminder can move her on.
       */}
      {rows !== null && showingInvitations && joinedShown.length > 0 && (
        <div className="surface affiliates__joined">
          <h2 className="affiliates__joined-title">Joined, hasn&rsquo;t applied yet</h2>
          <ul>
            {joinedShown.map((person) => (
              <li key={person.account_id} className="affiliates__joined-row">
                <span className="affiliates__who-text">
                  <span className="affiliates__name">{person.name || person.email}</span>
                  <span className="affiliates__sub">
                    {person.email}
                    {person.joined_at ? ` · joined ${formatSentAt(person.joined_at)}` : ""}
                  </span>
                </span>
                {reminded[person.account_id] ? (
                  <span className="affiliates__sub" role="status">
                    {reminded[person.account_id]}
                  </span>
                ) : (
                  <button type="button" className="button button--row" onClick={() => remind(person)}>
                    Remind her
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {rows !== null && showingInvitations && (
        <div className="surface">
          {invitations.length === 0 ? (
            <p className="empty">No outstanding invitations.</p>
          ) : (
            <table className="table affiliates__table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th className="affiliates__status-cell">Status</th>
                  <th className="affiliates__figure">{monthShort} sales</th>
                  <th className="affiliates__figure">Content</th>
                  <th className="affiliates__terms">Sent</th>
                  <th aria-hidden="true" />
                </tr>
              </thead>
              <tbody>
                {invitations.map((row) => (
                  // The export's roster row opens the invitation (`onOpen` ->
                  // `vInvite`), where Resend and Withdraw are; the row itself
                  // carries neither. Whole row, control font, as the model rows.
                  <tr key={row.id} className="control-font affiliates__row"
                    onClick={() => navigate(`/affiliates/models/invite?email=${encodeURIComponent(row.email)}`)}>
                    <td>
                      <span className="affiliates__who">
                        <span className="affiliates__avatar" aria-hidden="true">
                          {row.email.charAt(0).toUpperCase()}
                        </span>
                        <span className="affiliates__who-text">
                          <Link className="affiliates__name" to={`/affiliates/models/invite?email=${encodeURIComponent(row.email)}`}>{row.email}</Link>
                          <span className="affiliates__sub">
                            {row.withdrawn
                              ? "Withdrawn"
                              : row.expired
                                ? "Link expired"
                                : "Awaiting application"}
                          </span>
                        </span>
                      </span>
                    </td>
                    <td className="affiliates__status-cell">
                      <span
                        className={`pill affiliates__tone--${
                          row.expired ? "refused" : "owed"
                        }`}
                      >
                        {row.withdrawn ? "Withdrawn" : row.expired ? "Expired" : "Invited"}
                      </span>
                    </td>
                    <td className="affiliates__figure affiliates__tone--quiet">—</td>
                    <td className="affiliates__figure affiliates__tone--quiet">—</td>
                    <td className="affiliates__terms">
                      {formatSentAt(row.created_at)}
                    </td>
                    <td aria-hidden="true" />
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {rows !== null && !showingInvitations && visible.length === 0 && (rows.length > 0 || invited.length + joined.length > 0) && (
        <div className="surface">
          <p className="empty">
            {query.trim()
              ? `No model matches “${query.trim()}”. Search looks at names, codes and sign-in emails${need ? "" : " in this filter"}.`
              : "Nothing in this view."}
          </p>
          {query.trim() && (
            <p className="affiliates__empty-acts">
              <button type="button" className="button button--row" onClick={() => narrow({ q: "" })}>
                Clear the search
              </button>
            </p>
          )}
        </div>
      )}

      {!showingInvitations && visible.length > 0 && shown === "table" && (
        <div className="surface">
          <table className="table affiliates__table">
            <thead>
              <tr>
                {/*
                 * Her name over her code, the way the approved roster stacks
                 * them. The code is how an order is recognised as somebody's,
                 * so it is how a person is recognised on this list.
                 */}
                <th className="affiliates__pick">
                  <input
                    type="checkbox"
                    aria-label="Select every model on this page"
                    checked={paged.length > 0 && paged.every((row) => selected.has(row.id))}
                    onChange={(event) =>
                      setSelected((now) => {
                        const next = new Set(now);
                        for (const row of paged) {
                          if (event.target.checked) next.add(row.id);
                          else next.delete(row.id);
                        }
                        return next;
                      })
                    }
                  />
                </th>
                <th>Model</th>
                <th className="affiliates__status-cell">Status</th>
                <th className="affiliates__figure">{monthShort} sales</th>
                <th className="affiliates__figure">Content</th>
                <th className="affiliates__terms">
                  {segment === "applications" && !need ? "Applied" : "Terms"}
                </th>
                <th aria-hidden="true" />
              </tr>
            </thead>
            <tbody>
              {paged.map((row) => {
                const status = ROSTER_STATUS[row.status] ?? ROSTER_STATUS.inactive;
                const applying = row.status === "pending";
                const nothingYet =
                  row.content?.required_videos != null &&
                  row.content?.last_update == null;
                return (
                  // The export's row is one button: the whole row opens her,
                  // and its words are in the control font (ADR 0044) - which
                  // is what makes its pill 20px. The name stays a link for
                  // the keyboard and a screen reader.
                  <tr key={row.id} className="control-font affiliates__row"
                    onClick={() => navigate(`/affiliates/models/${row.id}`)}>
                    <td className="affiliates__pick" onClick={(event) => event.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label={`Select ${row.name}`}
                        checked={selected.has(row.id)}
                        onChange={() => toggleSelected(row.id)}
                      />
                    </td>
                    <td>
                      <Link className="affiliates__who" to={`/affiliates/models/${row.id}`}>
                        <span className="affiliates__avatar" aria-hidden="true">
                          {row.name.charAt(0).toUpperCase()}
                        </span>
                        <span className="affiliates__who-text">
                          <span className="affiliates__name">{row.name}</span>
                          <span className="affiliates__sub">
                            {row.code ?? "no code yet"}
                            {/* Shopify has never agreed this code exists. It
                             *  stops nothing, and the first symptom of a typo
                             *  is silence - so it is said, quietly. */}
                            {row.code && row.has_verified_code === false && " · not confirmed"}
                            {row.account_kind === "house" && " · house"}
                          </span>
                          {/* What stops her earning or being paid, on the row
                              itself - it used to show only on a phone. */}
                          <Blockers row={row} />
                        </span>
                      </Link>
                    </td>
                    <td className="affiliates__status-cell">
                      <span className={`pill affiliates__tone--${status.tone}`}>
                        {status.label}
                      </span>
                    </td>
                    <td className="affiliates__figure">
                      {applying ? (
                        <span className="affiliates__tone--quiet">—</span>
                      ) : (
                        <Money piastres={row.sales_piastres ?? 0} kind="agreed" />
                      )}
                    </td>
                    <td
                      className={`affiliates__figure affiliates__content ${
                        applying
                          ? "affiliates__tone--quiet"
                          : nothingYet
                            ? "affiliates__tone--owed"
                            : ""
                      }`}
                    >
                      {applying ? "—" : nothingYet ? "No update yet" : contentSummary(row)}
                    </td>
                    {/*
                     * *Terms* for a working model, *Applied* for somebody
                     * waiting - the export's last column. No terms is the one
                     * thing on this row that actually stops payroll, so it is
                     * the one thing coloured.
                     */}
                    <td className="affiliates__terms">
                      {applying ? (
                        row.created_at ? (
                          new Date(row.created_at).toLocaleDateString("en-GB", {
                            day: "numeric",
                            month: "long",
                          })
                        ) : (
                          "—"
                        )
                      ) : row.arrangement ? (
                        PAY_TYPE[row.arrangement] ?? row.arrangement
                      ) : row.account_kind === "house" ? (
                        <span className="affiliates__tone--quiet">Never paid</span>
                      ) : (
                        <span className="affiliates__tone--refused">No terms set</span>
                      )}
                    </td>
                    <td className="affiliates__go" aria-hidden="true">→</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {!showingInvitations && visible.length > ROSTER_PAGE && shown === "table" && (
        <div className="affiliates__pager">
          <span>
            {/* `1–12 of 19`, and `of 19 matching` while a search is on -
             *  the export's exact sentence. The suffix is what stops the
             *  total reading as the whole roster when it is a result count. */}
            {`${page * ROSTER_PAGE + 1}–${page * ROSTER_PAGE + paged.length}`}
            {` of ${visible.length}${query.trim() ? " matching" : ""}`}
          </span>
          <span className="affiliates__pager-acts">
            <button
              type="button"
              className="button button--row"
              disabled={page === 0}
              onClick={() => setPage(page - 1)}
            >
              Previous
            </button>
            <button
              type="button"
              className="button button--row"
              disabled={(page + 1) * ROSTER_PAGE >= visible.length}
              onClick={() => setPage(page + 1)}
            >
              Next
            </button>
          </span>
        </div>
      )}

      {!showingInvitations && visible.length > 0 && shown === "cards" && (
        <>
          <ul className="affiliates__cards">
            {visible.slice(0, cardLimit).map((row) => {
              const status = ROSTER_STATUS[row.status] ?? ROSTER_STATUS.inactive;
              const applying = row.status === "pending";
              return (
                <li key={row.id} className="affiliates__card">
                  {/* Admin Models audit: a card keeps what the table row
                      says - her code, sales and content - not just her name. */}
                  <span className="affiliates__card-top">
                    <Link className="affiliates__name" to={`/affiliates/models/${row.id}`}>
                      {row.name}
                    </Link>
                    <span className={`pill affiliates__tone--${status.tone}`}>{status.label}</span>
                  </span>
                  <span className="affiliates__card-note">
                    {row.code ?? "no code yet"}
                    {row.code && row.has_verified_code === false && " · not confirmed"}
                    {row.account_kind === "house" && " · house account"}
                  </span>
                  <Blockers row={row} />
                  {!applying && (
                    <span className="affiliates__card-figures">
                      <span>
                        {monthShort} sales
                        <strong>
                          <Money piastres={row.sales_piastres ?? 0} kind="agreed" />
                        </strong>
                      </span>
                      <span>
                        Content
                        <strong>{contentSummary(row)}</strong>
                      </span>
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
          {visible.length > cardLimit && (
            <button
              type="button"
              className="button affiliates__more"
              onClick={() => setCardLimit(cardLimit + ROSTER_PAGE)}
            >
              Show {Math.min(ROSTER_PAGE, visible.length - cardLimit)} more
            </button>
          )}
        </>
      )}
    </>
  );
}

/** What stops her earning or being paid, as small tags under her name. */
function Blockers({ row }: { row: Affiliate }) {
  const missing = missingSetup(row);
  if (missing.length === 0) return null;
  return (
    <span className="affiliates__blockers">
      {missing.map((reason) => (
        <span
          key={reason}
          className={
            reason === "code unconfirmed" || reason === "no pay terms"
              ? "affiliates__blocker affiliates__blocker--refused"
              : "affiliates__blocker"
          }
        >
          {reason}
        </span>
      ))}
    </span>
  );
}
