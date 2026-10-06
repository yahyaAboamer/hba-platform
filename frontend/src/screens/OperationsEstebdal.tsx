import { useState } from "react";

import { api } from "../lib/api";
import {
  FreshLine,
  OpsIcon,
  SourceBanner,
  clockTime,
  dayAndTime,
  stateNow,
  useIsNarrow,
  useNow,
  useOpsTab,
  waitingLabel,
} from "../components/OpsSource";
import type { Freshness } from "../components/OpsSource";
import "./OperationsDashboard.css";

/**
 * Operations → E-stebdal: return and exchange requests waiting for review
 * (ADR 0057; PRD E1; the approved mockup's frame 3).
 *
 * One card. Its list shows the request and order numbers and when it was
 * requested, and each opens E-stebdal, where it is approved or rejected.
 * E-stebdal publishes no address for a single request, so each opens its
 * dashboard, where the request's number finds it.
 */

type Request = {
  return_number: string;
  order_number: string | null;
  requested_at: string;
  waiting_days: number;
  url: string | null;
};
type Card = { key: string; count: number; requests: Request[] };
type EstebdalTab = { freshness: Freshness; total: number | null; cards: Card[] | null };

const LABEL = "Needs review";
const NOTE = "Nobody has approved or rejected them yet";

function RequestLink({ request }: { request: Request }) {
  if (!request.url) return <span className="num">{request.return_number}</span>;
  return (
    <a className="ops-ext num" href={request.url} target="_blank" rel="noopener noreferrer">
      {request.return_number}
      <OpsIcon name="ext" />
      <span className="visually-hidden"> (opens in E-stebdal)</span>
    </a>
  );
}

function RequestList({ card, narrow }: { card: Card; narrow: boolean }) {
  const noun = card.count === 1 ? "request" : "requests";
  return (
    <section className="panel" id="ops-list-panel-needs_review" aria-labelledby="ops-list-needs_review">
      <div className="panel__head">
        <h2 className="panel__title" id="ops-list-needs_review">
          {LABEL} · {card.count}
          {narrow ? "" : ` ${noun}`}
        </h2>
        {!narrow && <p className="ops-hint">Each opens in E-stebdal.</p>}
      </div>
      {narrow ? (
        <ul className="ops-rows">
          {card.requests.map((request) => (
            <li key={request.return_number}>
              <div className="ops-rows__top">
                <RequestLink request={request} />
                <span className={request.waiting_days === 0 ? "ops-muted" : undefined}>
                  {waitingLabel(request.waiting_days)}
                </span>
              </div>
              <div className="ops-rows__tags ops-muted">
                {request.order_number ? `Order ${request.order_number} · ` : ""}
                {dayAndTime(request.requested_at)}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <table className="ops-table">
          <thead>
            <tr>
              <th scope="col">Request</th>
              <th scope="col">Order</th>
              <th scope="col">Requested</th>
              <th scope="col">Waiting</th>
            </tr>
          </thead>
          <tbody>
            {card.requests.map((request) => (
              <tr key={request.return_number}>
                <td>
                  <RequestLink request={request} />
                </td>
                <td className="num">{request.order_number ?? "—"}</td>
                <td className="num">{dayAndTime(request.requested_at)}</td>
                <td className={request.waiting_days === 0 ? "ops-muted" : undefined}>
                  {waitingLabel(request.waiting_days)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export function OperationsEstebdal() {
  const [open, setOpen] = useState(false);
  const now = useNow();
  const narrow = useIsNarrow();
  const { tab, failed, reload } = useOpsTab(() => api.get<EstebdalTab>("/api/order-ops/estebdal"), (body) => {
    // An emptied list closes, and stays closed if requests arrive again.
    if (!body.cards?.[0]?.count) setOpen(false);
  });

  const freshness = tab?.freshness;
  const card = tab?.cards?.[0] ?? null;
  const state = freshness ? stateNow(freshness, now) : null;
  const old = state === "stale" || state === "failed";
  const asOf =
    old && freshness?.updated_at ? (
      <span className="ops-tile__as-of">As of {clockTime(freshness.updated_at)}</span>
    ) : null;

  return (
    <>
      <header className="page__head">
        <div className="page__title">
          <h1>E-stebdal</h1>
          <span className="page__subtitle">Return and exchange requests</span>
        </div>
        {freshness && <FreshLine freshness={freshness} now={now} />}
      </header>

      {failed && (
        <p className="notice notice--refused" role="alert">
          Couldn't load this tab.{" "}
          <button type="button" className="ops-linkbtn" onClick={reload}>
            Try again
          </button>
        </p>
      )}

      {!tab && !failed && <p className="loading">Loading…</p>}

      {freshness && <SourceBanner freshness={freshness} now={now} />}

      {state === "never" && !card && (
        <div className="ops-tiles">
          <div className="ops-tile ops-tile--reading">
            <span className="ops-tile__label">{LABEL}</span>
            <span className="ops-tile__value">Reading…</span>
            <span className="ops-tile__note">{NOTE}</span>
          </div>
        </div>
      )}

      {card && (
        <div className={old ? "ops-tiles ops-tiles--old" : "ops-tiles"}>
          {card.count === 0 ? (
            <div className="ops-tile ops-tile--zero">
              <span className="ops-tile__label">{LABEL}</span>
              <span className="ops-tile__value">0</span>
              <span className="ops-tile__note">Nothing waiting</span>
              {asOf}
            </div>
          ) : (
            <button
              type="button"
              className="ops-tile"
              aria-expanded={open}
              aria-controls={open ? "ops-list-panel-needs_review" : undefined}
              onClick={() => setOpen(!open)}
            >
              <span className="ops-tile__label">{LABEL}</span>
              <span className="ops-tile__value">{card.count}</span>
              <span className="ops-tile__note">{NOTE}</span>
              {asOf}
              {!narrow && (
                <span className="ops-tile__more">
                  {open ? "Hide requests" : "Show requests"}
                  <OpsIcon name={open ? "up" : "down"} />
                </span>
              )}
            </button>
          )}
        </div>
      )}

      {card && open && card.count > 0 && <RequestList card={card} narrow={narrow} />}
    </>
  );
}
