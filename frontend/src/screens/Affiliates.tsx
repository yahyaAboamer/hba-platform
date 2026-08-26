import { useEffect, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import "./Affiliates.css";

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
};

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
  active: "On the programme",
  inactive: "Paused",
  archived: "No longer on the programme",
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
export function Affiliates() {
  const [rows, setRows] = useState<Affiliate[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("table");
  const [includeArchived, setIncludeArchived] = useState(false);
  const isNarrow = useIsNarrow();
  // The toggle is a preference, not an override: a table does not fit on a
  // phone however firmly somebody asked for one.
  const shown: View = isNarrow ? "cards" : view;

  useEffect(() => {
    setError(null);
    api
      .get<{ affiliates: Affiliate[] }>(
        `/api/affiliates?include_archived=${includeArchived}`,
      )
      .then((body) => setRows(body.affiliates))
      .catch((caught) => setError(caught.message));
  }, [includeArchived]);

  const waiting = rows?.filter((row) => row.status === "pending") ?? [];
  const stuck = rows?.filter((row) => missingSetup(row).length > 0) ?? [];

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Affiliates</h1>
          {rows && (
            <span className="page__subtitle">{rows.length} on file</span>
          )}
        </div>

        <div className="affiliates__controls">
          <label className="affiliates__toggle-archived">
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(event) => setIncludeArchived(event.target.checked)}
            />
            Show archived
          </label>

          {/*
           * §12.3 keeps this toggle even though width alone already chooses a
           * table on a laptop and cards on a phone — it was asked for after
           * reviewing mockups, and that is a good enough reason.
           *
           * It disappears on a phone, where it could only be ignored: a table
           * does not fit there however firmly somebody asked for one, and a
           * control that does nothing teaches people the tool is unreliable.
           */}
          {!isNarrow && (
            <div className="affiliates__view" role="group" aria-label="Layout">
              <button
                type="button"
                className={
                  view === "table"
                    ? "affiliates__view-button affiliates__view-button--on"
                    : "affiliates__view-button"
                }
                onClick={() => setView("table")}
                aria-pressed={view === "table"}
              >
                Table
              </button>
              <button
                type="button"
                className={
                  view === "cards"
                    ? "affiliates__view-button affiliates__view-button--on"
                    : "affiliates__view-button"
                }
                onClick={() => setView("cards")}
                aria-pressed={view === "cards"}
              >
                Cards
              </button>
            </div>
          )}
        </div>
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {rows && rows.length > 0 && (
        <div className="affiliates__figures">
          <span>
            <strong>{waiting.length}</strong> waiting to be approved
          </span>
          <span className={stuck.length > 0 ? "affiliates__stuck" : undefined}>
            <strong>{stuck.length}</strong> need attention
          </span>
        </div>
      )}

      {rows === null && <p className="empty">Loading…</p>}

      {rows?.length === 0 && (
        <p className="empty">
          Nobody yet. An affiliate appears here once she has applied and you
          have created her record.
        </p>
      )}

      {rows && rows.length > 0 && shown === "table" && (
        <table className="table affiliates__table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Kind</th>
              <th>Needs attention</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const missing = missingSetup(row);
              return (
                <tr key={row.id}>
                  <td>
                    <Link
                      className="affiliates__name"
                      to={`/affiliates/${row.id}`}
                    >
                      {row.name}
                    </Link>
                  </td>
                  <td>{STATUS_LABEL[row.status]}</td>
                  <td>
                    <span className="affiliates__kind">
                      {row.account_kind === "house" ? "House" : "Model"}
                    </span>
                  </td>
                  {/*
                   * Empty when there is nothing wrong. Marking the healthy rows
                   * too would spend the one signal the page has on the rows
                   * that need nothing (ADR 0027).
                   */}
                  <td>
                    {missing.length > 0 && (
                      <span className="blocker">{missing.join(", ")}</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {rows && rows.length > 0 && shown === "cards" && (
        <ul className="affiliates__cards">
          {rows.map((row) => {
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
