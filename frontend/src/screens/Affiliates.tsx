import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Money } from "../components/Money";
import { api } from "../lib/api";
import { formatMonth } from "../lib/money";
import { AddHouseCode } from "./AddHouseCode";
import { InviteModel } from "./InviteModel";
import "./Affiliates.css";

/** The approved roster's segments. */
export type Segment = "all" | "waiting" | "active" | "archived";

export const SEGMENTS: { key: Segment; label: string }[] = [
  { key: "all", label: "All" },
  { key: "waiting", label: "Waiting to be approved" },
  { key: "active", label: "Active" },
  { key: "archived", label: "Archived" },
];

export type Affiliate = {
  id: number;
  name: string;
  phone: string | null;
  status: "pending" | "active" | "inactive" | "archived";
  account_kind: "model" | "house";
  is_payable: boolean;
  created_at: string | null;
  archived_at: string | null;
  has_verified_code?: boolean;
  has_terms?: boolean;
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
type Invited = {
  id: number;
  email: string;
  expires_at: string;
  expired: boolean;
  /** Cancelled on purpose, as opposed to simply lapsed. */
  withdrawn: boolean;
  created_at: string;
};

/**
 * When an invitation went out, said the way somebody actually reads it.
 *
 * "today at 14:20" and "yesterday" answer the question being asked - which of
 * these two identical rows is the recent one - where a full date makes the
 * reader do the arithmetic themselves.
 */
function formatSentAt(iso: string): string {
  const sent = new Date(iso);
  const time = sent.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
  });
  const days = Math.floor(
    (new Date().setHours(0, 0, 0, 0) - new Date(sent).setHours(0, 0, 0, 0)) /
      86_400_000,
  );
  if (days === 0) return `today at ${time}`;
  if (days === 1) return `yesterday at ${time}`;
  return sent.toLocaleDateString("en-GB", { day: "numeric", month: "long" });
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
  if (row.status === "archived") return [];

  const missing: string[] = [];
  if (row.is_payable && row.has_terms === false) missing.push("no pay terms");
  if (row.has_verified_code === false) missing.push("code unconfirmed");
  return missing;
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
    if (segment === "waiting" && row.status !== "pending") return false;
    if (segment === "active" && row.status !== "active") return false;
    if (segment === "archived" && row.status !== "archived") return false;
    if (!needle) return true;
    return (
      row.name.toLowerCase().includes(needle) ||
      (row.code ?? "").toLowerCase().includes(needle)
    );
  });
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
  const [view, setView] = useState<View>("table");
  const [includeArchived, setIncludeArchived] = useState(false);
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
  const segment = (params.get("segment") as Segment) ?? "all";
  const query = params.get("q") ?? "";

  const narrow = useCallback(
    (next: { segment?: Segment; q?: string }) => {
      setParams(
        (previous) => {
          const updated = new URLSearchParams(previous);
          for (const [key, value] of Object.entries(next)) {
            // An empty search or the default segment leaves no trace: a URL
            // carrying `?q=` says a search happened and found everything.
            if (!value || value === "all") updated.delete(key);
            else updated.set(key, value);
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
  const shown: View = isNarrow ? "cards" : view;
  const visible = rows ? rosterMatches(rows, segment, query) : [];
  // Archived is a segment now rather than a checkbox, so asking for it is what
  // fetches it. Keeping both controls would let them contradict each other.
  useEffect(() => {
    setIncludeArchived(segment === "archived");
  }, [segment]);
  // The column header names the month it is showing, so a figure can never be
  // read as "this month" when the list is answering for another one.
  const monthLabel = rows?.[0]?.month ? formatMonth(rows[0].month) : "Month";

  const reload = useCallback(() => {
    setError(null);
    api
      .get<{ affiliates: Affiliate[]; invited: Invited[] }>(
        `/api/affiliates?include_archived=${includeArchived}`,
      )
      .then((body) => {
        setRows(body.affiliates);
        setInvited(body.invited ?? []);
      })
      .catch((caught) => setError(caught.message));
  }, [includeArchived]);

  useEffect(reload, [reload]);

  // Live is what somebody is still waiting on; dead is history that should
  // not be in the way of it.
  const live = invited.filter((row) => !row.expired);
  const dead = invited.filter((row) => row.expired);

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Models</h1>
          {rows && (
            <span className="page__subtitle">
              {/* While a search or segment is narrowing the list, the count
               *  says what is on screen as well as what exists — a bare
               *  "6 on file" above one visible row reads as a bug. */}
              {visible.length === rows.length
                ? `${rows.length} on file`
                : `${visible.length} of ${rows.length}`}
            </span>
          )}
        </div>
      </div>

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
              className={segment === option.key ? "chip chip--on" : "chip"}
              onClick={() => narrow({ segment: option.key })}
              aria-pressed={segment === option.key}
            >
              {option.label}
              {rows && (
                <span className="affiliates__segment-count">
                  {rosterMatches(rows, option.key, "").length}
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
            placeholder="Search name or code"
            aria-label="Search models by name or code"
          />

          {/*
           * §12.3 keeps this toggle even though width alone already chooses a
           * table on a laptop and cards on a phone — it was asked for after
           * reviewing mockups, and that is a good enough reason. It is drawn
           * as the export's segmented switch because that is the export's
           * word for *one of these two*.
           *
           * It disappears on a phone, where it could only be ignored: a table
           * does not fit there however firmly somebody asked for one, and a
           * control that does nothing teaches people the tool is unreliable.
           */}
          {!isNarrow && (
            <div className="seg" role="group" aria-label="Layout">
              <label className="seg-opt">
                <input type="radio" name="roster-view" checked={view === "table"}
                  onChange={() => setView("table")} />
                <span>Table</span>
              </label>
              <label className="seg-opt">
                <input type="radio" name="roster-view" checked={view === "cards"}
                  onChange={() => setView("cards")} />
                <span>Cards</span>
              </label>
            </div>
          )}

          {/*
           * Deliberately its own button, not a second option folded into
           * inviting a model. The two create opposite things - a person who
           * signs in and gets paid, versus a code that never does either -
           * and one control offering both invites exactly the mistake this
           * exists to prevent. It is the quieter of the two, because it is
           * the rarer of the two.
           */}
          <AddHouseCode onCreated={reload} />

          {/*
           * The primary action on this screen, and it used to have no home at
           * all: inviting a model was neither here nor in Settings, whose role
           * list offers only staff. Phase 8 built the whole onboarding flow
           * and nothing could start it.
           */}
          <InviteModel onInvited={reload} />
        </div>
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {/*
       * Invitations nobody has opened. They belong here rather than on the
       * staff panel - a model is not staff - and they have to be somewhere, or
       * an invitation sent to the wrong address could never be withdrawn.
       */}
      {invited.length > 0 && (
        <details className="panel affiliates__invited">
          {/*
           * Collapsed to one line. An invitation waiting on somebody is worth
           * seeing, so it stays at the top rather than moving to the bottom -
           * but seven of them once buried the four models this screen exists
           * to show. Closing an address when its owner accepts (server side)
           * keeps this short; collapsing keeps it short even when it is not.
           */}
          {/*
           * **The count is of live ones only.** Dead invitations are not
           * outstanding - nobody is waiting on them - and counting them made
           * the number grow for ever while meaning less each time.
           */}
          <summary className="affiliates__invited-summary">
            {live.length > 0 ? (
              <>
                <strong>{live.length}</strong>{" "}
                {live.length === 1 ? "invitation" : "invitations"} outstanding
              </>
            ) : (
              <>No invitations outstanding</>
            )}
          </summary>
          <ul className="affiliates__invited-list">
            {live.map((row) => (
              <li key={row.id}>
                <span className="affiliates__invited-who">
                  <span>{row.email}</span>
                  {/*
                   * Sent-when, because two rows for one address were otherwise
                   * identical and there was no way to tell which was which.
                   */}
                  <span className="affiliates__invited-when">
                    sent {formatSentAt(row.created_at)}
                  </span>
                </span>
                <span className="affiliates__invited-state">
                  Still waiting
                </span>
                {/*
                 * Resend always; withdraw only where it can actually work.
                 * Withdrawing backdates the expiry and the server refuses an
                 * invitation that has already lapsed - so offering Withdraw on
                 * a row marked "Link expired" was offering an action that
                 * could only fail, which is exactly what it did.
                 */}
                <button
                  type="button"
                  className="button"
                  onClick={() =>
                    api
                      .post(`/api/staff/invitations/${row.id}/resend`)
                      .then(reload)
                      .catch((caught) => setError(caught.message))
                  }
                >
                  Resend
                </button>
                {/*
                 * No guard needed: this list holds live invitations only, and
                 * withdrawing is refused on anything already lapsed. The
                 * condition that used to be here described a row that can no
                 * longer appear.
                 */}
                <button
                  type="button"
                  className="button"
                  onClick={() =>
                    api
                      .post(`/api/staff/invitations/${row.id}/revoke`)
                      .then(reload)
                      .catch((caught) => setError(caught.message))
                  }
                >
                  Withdraw
                </button>
              </li>
            ))}
          </ul>

          {/*
           * **Kept, not deleted, and not in the way.** Twenty models onboarded
           * means a long tail of typos and lapsed links, and every one of them
           * was sitting above the list of people who actually matter. They are
           * still here when somebody wants to know whether a link expired -
           * which is the only question they answer.
           */}
          {dead.length > 0 && (
            <details className="affiliates__invited-dead">
              <summary>
                {dead.length} {dead.length === 1 ? "link" : "links"} no longer
                usable
              </summary>
              <ul className="affiliates__invited-list">
                {dead.map((row) => (
                  <li key={row.id}>
                    <span className="affiliates__invited-who">
                      <span>{row.email}</span>
                      <span className="affiliates__invited-when">
                        sent {formatSentAt(row.created_at)}
                      </span>
                    </span>
                    <span className="affiliates__invited-state">
                      {row.withdrawn ? "Withdrawn" : "Link expired"}
                    </span>
                    <button
                      type="button"
                      className="button"
                      onClick={() =>
                        api
                          .post(`/api/staff/invitations/${row.id}/resend`)
                          .then(reload)
                          .catch((caught) => setError(caught.message))
                      }
                    >
                      Resend
                    </button>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </details>
      )}

      {rows === null && <p className="empty">Loading…</p>}

      {rows?.length === 0 && (
        <p className="empty">
          Nobody yet. An affiliate appears here once they have applied and you
          have created their record.
        </p>
      )}

      {rows && rows.length > 0 && visible.length === 0 && (
        <p className="empty">
          Nobody here matches. Clear the search, or try another segment.
        </p>
      )}

      {visible.length > 0 && shown === "table" && (
        <table className="table affiliates__table">
          <thead>
            <tr>
              {/*
               * Her name over her code, the way the approved roster stacks
               * them. The code is how an order is recognised as somebody's,
               * so it is how a person is recognised on this list — asked for
               * by name during the walkthrough, and kept beside the name
               * rather than in a column of its own.
               */}
              <th>Model</th>
              <th className="affiliates__status-cell">Status</th>
              <th className="affiliates__figure">{monthLabel} sales</th>
              <th className="affiliates__figure">Content</th>
              <th className="affiliates__attention">Needs attention</th>
              <th aria-hidden="true" />
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => {
              const missing = missingSetup(row);
              return (
                <tr key={row.id}>
                  <td>
                    <Link className="affiliates__who" to={`/affiliates/${row.id}`}>
                      <span className="affiliates__avatar" aria-hidden="true">
                        {row.name.charAt(0).toUpperCase()}
                      </span>
                      <span className="affiliates__who-text">
                        <span className="affiliates__name">{row.name}</span>
                        {row.code ? (
                          <span className="code">{row.code}</span>
                        ) : (
                          <span className="affiliates__no-code">no code yet</span>
                        )}
                      </span>
                    </Link>
                  </td>
                  <td className="affiliates__status-cell">
                    <span className={`affiliates__status affiliates__status--${row.status}`}>
                      {STATUS_LABEL[row.status]}
                    </span>
                    {row.account_kind === "house" && (
                      <span className="affiliates__kind">House</span>
                    )}
                  </td>
                  <td className="affiliates__figure">
                    <Money piastres={row.sales_piastres ?? 0} />
                  </td>
                  <td className="affiliates__figure">{contentSummary(row)}</td>
                  {/*
                   * Empty when there is nothing wrong. Marking the healthy rows
                   * too would spend the one signal the page has on the rows
                   * that need nothing (ADR 0027).
                   */}
                  <td className="affiliates__attention">
                    {missing.length > 0 && (
                      <span className="blocker">{missing.join(", ")}</span>
                    )}
                  </td>
                  <td className="affiliates__go" aria-hidden="true">→</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {visible.length > 0 && shown === "cards" && (
        <ul className="affiliates__cards">
          {visible.map((row) => {
            const missing = missingSetup(row);
            return (
              <li key={row.id} className="affiliates__card">
                <Link className="affiliates__name" to={`/affiliates/${row.id}`}>
                  {row.name}
                </Link>
                <span className="affiliates__card-note">
                  {STATUS_LABEL[row.status]}
                  {row.account_kind === "house" && " · house account"}
                </span>
                {missing.length > 0 && (
                  <span className="blocker">{missing.join(", ")}</span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
