import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { AddHouseCode } from "./AddHouseCode";
import { InviteModel } from "./InviteModel";
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

/** An invitation nobody has opened yet. Not a model, and still ours. */
type Invited = {
  id: number;
  email: string;
  expires_at: string;
  expired: boolean;
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
export function Affiliates() {
  const [rows, setRows] = useState<Affiliate[] | null>(null);
  const [invited, setInvited] = useState<Invited[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("table");
  const [includeArchived, setIncludeArchived] = useState(false);
  const isNarrow = useIsNarrow();
  // The toggle is a preference, not an override: a table does not fit on a
  // phone however firmly somebody asked for one.
  const shown: View = isNarrow ? "cards" : view;

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
          {/*
           * The primary action on this screen, and it used to have no home at
           * all: inviting a model was neither here nor in Settings, whose role
           * list offers only staff. Phase 8 built the whole onboarding flow
           * and nothing could start it.
           */}
          <InviteModel onInvited={reload} />

          {/*
           * Deliberately its own button, not a second option folded into
           * inviting a model. The two create opposite things - a person who
           * signs in and gets paid, versus a code that never does either -
           * and one control offering both invites exactly the mistake this
           * exists to prevent.
           */}
          <AddHouseCode onCreated={reload} />

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

      {/*
       * Two counts that overlap, and the business read them as the same thing:
       * *I don't understand what is needs attention and what is the difference
       * between it and waiting to be approved.*
       *
       * They are different and only one of them is about a decision. Waiting
       * to be approved is somebody who has applied. Needs attention is
       * somebody - approved or not - who is missing a verified code or pay
       * terms, and therefore earns nothing while looking fine. Saying what
       * each means costs a clause and removes the question.
       */}
      {rows && rows.length > 0 && (
        <div className="affiliates__figures">
          <span>
            <strong>{waiting.length}</strong> waiting for you to approve
          </span>
          <span className={stuck.length > 0 ? "affiliates__stuck" : undefined}>
            <strong>{stuck.length}</strong> cannot earn yet — no code confirmed,
            or no pay terms
          </span>
        </div>
      )}

      {/*
       * Invitations nobody has opened. They belong here rather than on the
       * staff panel - a model is not staff - and they have to be somewhere, or
       * an invitation sent to the wrong address could never be withdrawn.
       */}
      {invited.length > 0 && (
        <section className="panel affiliates__invited">
          <div className="panel__head">
            <h2 className="panel__title">Invited, not opened yet</h2>
          </div>
          <ul className="affiliates__invited-list">
            {invited.map((row) => (
              <li key={row.id}>
                <span>{row.email}</span>
                <span className="affiliates__invited-state">
                  {row.expired ? "Link expired" : "Still waiting"}
                </span>
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
        </section>
      )}

      {rows === null && <p className="empty">Loading…</p>}

      {rows?.length === 0 && (
        <p className="empty">
          Nobody yet. An affiliate appears here once they have applied and you
          have created their record.
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
