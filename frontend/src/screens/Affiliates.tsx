import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Money } from "../components/Money";
import { api } from "../lib/api";
import { PAY_TYPE } from "../lib/payouts";
import { formatMonth } from "../lib/money";
import { AddHouseCode } from "./AddHouseCode";
import { InviteModel } from "./InviteModel";
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
  inactive: { label: "Inactive", tone: "quiet" },
  archived: { label: "Inactive", tone: "quiet" },
};

/** The export lists twelve to a page. */
const ROSTER_PAGE = 12;

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
    // Invitations are not models; that filter lists them instead.
    if (segment === "invitations") return false;
    if (segment === "applications" && row.status !== "pending") return false;
    if (segment === "active" && row.status !== "active") return false;
    if (
      segment === "inactive" &&
      row.status !== "inactive" &&
      row.status !== "archived"
    ) {
      return false;
    }
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
  // An address from before the filters were renamed (*all*, *waiting*)
  // lands on Active rather than on an empty table.
  const asked = params.get("segment");
  const segment: Segment = SEGMENTS.some((option) => option.key === asked)
    ? (asked as Segment)
    : "active";
  const [page, setPage] = useState(0);
  const query = params.get("q") ?? "";

  const narrow = useCallback(
    (next: { segment?: Segment; q?: string }) => {
      setParams(
        (previous) => {
          const updated = new URLSearchParams(previous);
          for (const [key, value] of Object.entries(next)) {
            // An empty search or the default segment leaves no trace: a URL
            // carrying `?q=` says a search happened and found everything.
            if (!value || value === "active") updated.delete(key);
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
    setIncludeArchived(segment === "inactive");
    setPage(0);
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
  // Live first, then lapsed and withdrawn - the export lists expired links in
  // the same table, and the ones somebody is still waiting on belong on top.
  const needle = query.trim().toLowerCase();
  const invitations = [
    ...invited.filter((row) => !row.expired),
    ...invited.filter((row) => row.expired),
  ].filter((row) => !needle || row.email.toLowerCase().includes(needle));
  const paged = visible.slice(page * ROSTER_PAGE, (page + 1) * ROSTER_PAGE);

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
                  {option.key === "invitations"
                    ? invited.length
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

      {rows === null && <p className="empty">Loading…</p>}

      {rows !== null && segment === "invitations" && (
        <div className="surface">
          {invitations.length === 0 ? (
            <p className="empty">No outstanding invitations.</p>
          ) : (
            <table className="table affiliates__table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th className="affiliates__status-cell">Status</th>
                  <th className="affiliates__figure">{monthLabel} sales</th>
                  <th className="affiliates__figure">Content</th>
                  <th className="affiliates__terms">Sent</th>
                  <th aria-hidden="true" />
                </tr>
              </thead>
              <tbody>
                {invitations.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <span className="affiliates__who">
                        <span className="affiliates__avatar" aria-hidden="true">
                          {row.email.charAt(0).toUpperCase()}
                        </span>
                        <span className="affiliates__who-text">
                          <span className="affiliates__name">{row.email}</span>
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
                      {/*
                       * Resend always; withdraw only where it can work. The
                       * export opens the invitation to act on it, and there is
                       * no invitation view here yet, so the two acts ride under
                       * the date rather than disappearing.
                       */}
                      <span className="affiliates__row-acts">
                        <button
                          type="button"
                          className="button button--quiet"
                          onClick={() =>
                            api
                              .post(`/api/staff/invitations/${row.id}/resend`)
                              .then(reload)
                              .catch((caught) => setError(caught.message))
                          }
                        >
                          Resend
                        </button>
                        {!row.expired && (
                          <button
                            type="button"
                            className="button button--quiet"
                            onClick={() =>
                              api
                                .post(`/api/staff/invitations/${row.id}/revoke`)
                                .then(reload)
                                .catch((caught) => setError(caught.message))
                            }
                          >
                            Withdraw
                          </button>
                        )}
                      </span>
                    </td>
                    <td aria-hidden="true" />
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {rows !== null && segment !== "invitations" && visible.length === 0 && (
        <div className="surface">
          <p className="empty">
            {query.trim()
              ? `No model matches “${query.trim()}”.`
              : "Nothing in this view."}
          </p>
        </div>
      )}

      {segment !== "invitations" && visible.length > 0 && shown === "table" && (
        <div className="surface">
          <table className="table affiliates__table">
            <thead>
              <tr>
                {/*
                 * Her name over her code, the way the approved roster stacks
                 * them. The code is how an order is recognised as somebody's,
                 * so it is how a person is recognised on this list.
                 */}
                <th>Model</th>
                <th className="affiliates__status-cell">Status</th>
                <th className="affiliates__figure">{monthLabel} sales</th>
                <th className="affiliates__figure">Content</th>
                <th className="affiliates__terms">
                  {segment === "applications" ? "Applied" : "Terms"}
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
                  <tr key={row.id}>
                    <td>
                      <Link className="affiliates__who" to={`/affiliates/${row.id}`}>
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
                        <span className="affiliates__tone--refused">Not set</span>
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

      {segment !== "invitations" && visible.length > ROSTER_PAGE && shown === "table" && (
        <div className="affiliates__pager">
          <span>
            {page * ROSTER_PAGE + 1}–{page * ROSTER_PAGE + paged.length} of {visible.length}
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

      {segment !== "invitations" && visible.length > 0 && shown === "cards" && (
        <ul className="affiliates__cards">
          {visible.map((row) => {
            const missing = missingSetup(row);
            return (
              <li key={row.id} className="affiliates__card">
                <Link className="affiliates__name" to={`/affiliates/${row.id}`}>
                  {row.name}
                </Link>
                <span className="affiliates__card-note">
                  {(ROSTER_STATUS[row.status] ?? ROSTER_STATUS.inactive).label}
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
