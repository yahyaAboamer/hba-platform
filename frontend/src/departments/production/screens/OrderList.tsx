import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api, can } from "../../../lib/api";
import type { Session } from "../../../lib/api";
import { cairoToday, lateWords, pieces, shortDay, stagePhrase, whoWhen } from "./format";
import type { Tone } from "./format";
import type { OrderRow } from "./types";
import { Problem, Steps, useIsNarrow } from "./ui";

type OrderRows = { orders: OrderRow[] };
type Filter = "open" | "late" | "waiting" | "closed";

const TONE_CLASS: Record<Tone, string> = { late: "prod-late", warn: "prod-warn", ok: "prod-ok", "": "" };

/** Whether somebody should look at this order today. */
const needsAttention = (row: OrderRow): boolean => row.flags.late || row.flags.waiting_for_owner || row.flags.count_mismatch;

function Lateness({ row }: { row: OrderRow }) {
  const words = lateWords(row);
  return <span className={TONE_CLASS[words.tone]}>{words.text}</span>;
}

function NextAction({ row, today }: { row: OrderRow; today: string }) {
  const action = row.next_action;
  if (!action) return <span className="prod-small">{row.status === "cancelled" ? "Cancelled" : "Settled and closed"}</span>;
  return (
    <>
      <span className={action.who === "owner" ? "prod-warn" : undefined}>{action.what}</span>
      <div className="prod-small">{whoWhen(action, today, row.flags.waiting_for_owner)}</div>
    </>
  );
}

function OrderName({ row }: { row: OrderRow }) {
  return (
    <Link className="prod-rowlink" to={`/production/orders/${row.id}`}>
      {row.style_name} · {row.colour}
    </Link>
  );
}

function Table({ rows, today }: { rows: OrderRow[]; today: string }) {
  return (
    <div className="surface prod-list">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Order</th>
            <th scope="col">Factory</th>
            <th scope="col">Stage</th>
            <th scope="col" className="numeric">Planned</th>
            <th scope="col" className="numeric">Received</th>
            <th scope="col">Target date</th>
            <th scope="col">Next action</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>
                <OrderName row={row} />
                <div className="prod-small">{row.code}</div>
              </td>
              <td>{row.factory.name ?? "—"}</td>
              <td>
                {stagePhrase(row)}
                <Steps steps={row.steps} />
              </td>
              <td className="numeric">{pieces(row.planned_total)}</td>
              <td className="numeric">{pieces(row.received_total)}</td>
              <td>
                {shortDay(row.target_date)}
                <div className="prod-small">
                  <Lateness row={row} />
                </div>
              </td>
              <td>
                <NextAction row={row} today={today} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Cards({ rows, today }: { rows: OrderRow[]; today: string }) {
  return (
    <div className="prod-cards">
      {rows.map((row) => (
        <article key={row.id} className="prod-card">
          <div>
            <OrderName row={row} />
            <div className="prod-small">
              {row.code} · {row.factory.name ?? "—"}
            </div>
          </div>
          <div>
            {stagePhrase(row)}
            <Steps steps={row.steps} />
          </div>
          <div className="prod-small">
            {pieces(row.received_total)} of {pieces(row.planned_total)} received · target {shortDay(row.target_date)} · <Lateness row={row} />
          </div>
          {row.next_action && (
            <div className={`prod-flag ${row.next_action.who === "owner" ? "prod-flag--owed" : ""}`}>
              {row.next_action.what}
              <div className="prod-small">{whoWhen(row.next_action, today, row.flags.waiting_for_owner)}</div>
            </div>
          )}
        </article>
      ))}
    </div>
  );
}

/** `/production/orders`: every production order, and what happens next on each. */
export function OrderList({ session }: { session: Session }) {
  const [open, setOpen] = useState<OrderRow[] | null>(null);
  const [closed, setClosed] = useState<OrderRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("open");
  const narrow = useIsNarrow();
  const isOwner = can(session, "production.owner");
  const today = useMemo(cairoToday, []);

  const load = useCallback(() => {
    setError(null);
    Promise.all([api.get<OrderRows>("/api/prod/orders?status=open"), api.get<OrderRows>("/api/prod/orders?status=closed")])
      .then(([inProduction, finished]) => {
        setOpen(inProduction.orders);
        setClosed(finished.orders);
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "The orders could not be loaded."));
  }, []);
  useEffect(load, [load]);

  const late = open?.filter((row) => row.flags.late) ?? [];
  const waiting = open?.filter((row) => row.flags.waiting_for_owner) ?? [];
  const attention = open?.filter(needsAttention).length ?? 0;
  const shown = filter === "open" ? open : filter === "late" ? late : filter === "waiting" ? waiting : closed;

  const chips: { key: Filter; label: string; count: number }[] = [
    { key: "open", label: "In production", count: open?.length ?? 0 },
    { key: "late", label: "Late", count: late.length },
    { key: "waiting", label: "Waiting for owner", count: waiting.length },
    { key: "closed", label: "Closed", count: closed?.length ?? 0 },
  ];

  const empty: Record<Filter, string> = {
    open: "No orders in production.",
    late: "Nothing is running late.",
    waiting: "Nothing is waiting for the owner.",
    closed: "No order has been settled or cancelled yet.",
  };

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Production orders</h1>
          <span className="page__subtitle">
            {open ? `${open.length} in production${attention ? `, ${attention} need${attention === 1 ? "s" : ""} attention` : ""}` : "Loading"}
          </span>
        </div>
        {isOwner && (
          <div className="prod-head-actions">
            <Link className="button button--primary" to="/production/orders/new">
              New order
            </Link>
          </div>
        )}
      </div>

      {error && (
        <div>
          <Problem>{error}</Problem>
          <button type="button" className="button" onClick={load}>
            Try again
          </button>
        </div>
      )}

      {!error && (open === null || closed === null) && <p className="loading" role="status">Loading orders…</p>}

      {!error && open !== null && closed !== null && (
        <>
          <div className="prod-chips" role="group" aria-label="Show">
            {chips.map((chip) => (
              <button
                key={chip.key}
                type="button"
                className={`chip${filter === chip.key ? " chip--on" : ""}`}
                aria-pressed={filter === chip.key}
                onClick={() => setFilter(chip.key)}
              >
                {chip.label} · {chip.count}
              </button>
            ))}
          </div>

          {shown && shown.length === 0 ? (
            <p className="empty">
              {empty[filter]}
              {filter === "open" && isOwner && (
                <>
                  {" "}
                  <Link to="/production/orders/new">Make the first one.</Link>
                </>
              )}
            </p>
          ) : narrow ? (
            <Cards rows={shown ?? []} today={today} />
          ) : (
            <Table rows={shown ?? []} today={today} />
          )}
        </>
      )}
    </>
  );
}
