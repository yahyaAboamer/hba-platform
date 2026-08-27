import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Money } from "../components/Money";
import { MonthPicker } from "../components/MonthPicker";
import type { MonthLock } from "../components/MonthPicker";
import { api } from "../lib/api";
import type { Session } from "../lib/api";
import { currentMonth, formatMonth } from "../lib/money";
import "./Orders.css";

type Outcome = "attributed" | "unattributed" | "held";

type OrderRow = {
  shopify_order_id: string;
  order_number: string;
  placed_at: string;
  business_month: string;
  discount_codes: string[];
  total_piastres: number;
  delivery_state: string | null;
  delivery_status: string | null;
  cancelled: boolean;
  outcome: Outcome;
  affiliate_id: number | null;
  affiliate_name: string | null;
  matched_codes: string[];
  commission_state: "pending" | "earned" | "void" | null;
  base_piastres: number | null;
  is_carried: boolean;
  paid_in_month: string | null;
};

type Grid = {
  month: string;
  orders: OrderRow[];
  totals: { orders: number; held: number; unattributed: number; carried: number };
};

const DELIVERY_LABEL: Record<string, string> = {
  delivered: "Delivered",
  failed: "Failed delivery",
  in_flight: "On its way",
};

const COMMISSION_LABEL: Record<string, string> = {
  earned: "Counts",
  pending: "Still travelling",
  void: "Does not count",
};

/**
 * Why one order reads the way it does.
 *
 * Affiliates, Payroll and Payments each answer "what does she earn" for a
 * model or a month. This answers the question that actually arrives one order
 * at a time — whose code it carried, whether Shopify has said it arrived,
 * which payroll paid it — so the order is the unit here, not the person.
 *
 * Nothing on this page can be changed. It reads decisions `attributed_order`
 * and `payroll_snapshot` already made.
 */
export function Orders({ session }: { session: Session }) {
  const [month, setMonth] = useState(session.platform.working_month);
  const [grid, setGrid] = useState<Grid | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lockNote, setLockNote] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [found, setFound] = useState<OrderRow | null | undefined>(undefined);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    setError(null);
    api
      .get<Grid>(`/api/orders/${month}`)
      .then(setGrid)
      .catch((caught) => setError(caught.message));
  }, [month]);

  function lockFor(candidate: string): MonthLock {
    if (
      session.platform.go_live_month &&
      candidate < session.platform.go_live_month
    ) {
      return "historical";
    }
    if (candidate > currentMonth()) return "future";
    return null;
  }

  async function lookUp(event: React.FormEvent) {
    event.preventDefault();
    const needle = search.trim();
    if (!needle) return;
    setSearching(true);
    setFound(undefined);
    try {
      setFound(await api.get<OrderRow>(`/api/orders/lookup/${encodeURIComponent(needle)}`));
    } catch {
      setFound(null);
    } finally {
      setSearching(false);
    }
  }

  const rows = grid?.orders ?? [];

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Orders</h1>
          <span className="page__subtitle">{formatMonth(month)}</span>
        </div>
        <MonthPicker
          value={month}
          onChange={setMonth}
          lockFor={lockFor}
          onLockedClick={(candidate, lock) =>
            setLockNote(
              lock === "historical"
                ? `${formatMonth(candidate)} was settled before the platform.`
                : `${formatMonth(candidate)} has not finished. Orders are still arriving.`,
            )
          }
        />
      </div>

      {/*
       * The support question arrives as an order number, never as a month.
       * Looking one up is therefore its own action, separate from browsing.
       */}
      <form className="orders__search" onSubmit={lookUp}>
        <input
          className="input orders__search-input"
          placeholder="Find an order by number — 2001 or #2001"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setFound(undefined);
          }}
        />
        <button type="submit" className="button" disabled={searching || !search.trim()}>
          {searching ? "Looking…" : "Find"}
        </button>
      </form>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {found === null && (
        <p className="notice notice--refused orders__note" role="alert">
          No order matches "{search.trim()}".
        </p>
      )}

      {found && (
        <div className="orders__found">
          <p className="orders__found-label">Found, regardless of month:</p>
          <table className="table orders__table">
            <thead>
              <OrderHead />
            </thead>
            <tbody>
              <OrderTableRow row={found} />
            </tbody>
          </table>
        </div>
      )}

      {lockNote && <p className="notice orders__note">{lockNote}</p>}

      {grid === null && !error && <p className="empty">Loading…</p>}

      {grid && (
        <div className="orders__figures">
          <div className="orders__figure">
            <strong className="orders__count">{grid.totals.orders}</strong>
            <span className="orders__figure-label">orders this month</span>
          </div>
          {grid.totals.held > 0 && (
            <div className="orders__figure">
              <strong className="orders__count orders__count--refused">
                {grid.totals.held}
              </strong>
              <span className="orders__figure-label">
                held — two codes both claim {grid.totals.held === 1 ? "it" : "them"}
              </span>
            </div>
          )}
          {grid.totals.unattributed > 0 && (
            <div className="orders__figure">
              <strong className="orders__count">{grid.totals.unattributed}</strong>
              <span className="orders__figure-label">no affiliate code used</span>
            </div>
          )}
          {grid.totals.carried > 0 && (
            <div className="orders__figure">
              <strong className="orders__count">{grid.totals.carried}</strong>
              <span className="orders__figure-label">
                carried in from an earlier month
              </span>
            </div>
          )}
        </div>
      )}

      {grid && rows.length === 0 && !found && (
        <p className="empty">No orders placed in {formatMonth(month)} yet.</p>
      )}

      {grid && rows.length > 0 && (
        <table className="table orders__table">
          <thead>
            <OrderHead />
          </thead>
          <tbody>
            {rows.map((row) => (
              <OrderTableRow key={row.shopify_order_id} row={row} />
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function OrderHead() {
  return (
    <tr>
      <th>Order</th>
      <th>Placed</th>
      <th>Codes</th>
      <th>Belongs to</th>
      <th>Delivery</th>
      <th>Commission</th>
      <th className="orders__amount">Sales</th>
      <th className="orders__amount">Base</th>
      <th>Paid by</th>
    </tr>
  );
}

function OrderTableRow({ row }: { row: OrderRow }) {
  return (
    <tr>
      <td className="code">{row.order_number}</td>
      <td className="orders__placed">
        {new Date(row.placed_at).toLocaleDateString("en-GB", {
          day: "numeric",
          month: "short",
        })}
      </td>
      <td>
        {row.discount_codes.length === 0 ? (
          <span className="orders__quiet">none</span>
        ) : (
          row.discount_codes.map((code) => (
            <span
              key={code}
              className={
                row.matched_codes.includes(code)
                  ? "code orders__code"
                  : "code orders__code orders__code--unmatched"
              }
            >
              {code}
            </span>
          ))
        )}
      </td>
      <td>
        {row.outcome === "attributed" && row.affiliate_id !== null ? (
          <Link className="orders__name" to={`/affiliates/${row.affiliate_id}`}>
            {row.affiliate_name}
          </Link>
        ) : row.outcome === "held" ? (
          <span className="blocker">Held — two codes claim it</span>
        ) : (
          <span className="orders__quiet">No affiliate code</span>
        )}
      </td>
      <td className="orders__delivery">
        {row.cancelled
          ? "Cancelled"
          : row.delivery_state
            ? DELIVERY_LABEL[row.delivery_state] ?? row.delivery_state
            : "Not yet known"}
      </td>
      <td className="orders__commission">
        {row.commission_state ? COMMISSION_LABEL[row.commission_state] : "—"}
      </td>
      <td className="orders__amount">
        <Money piastres={row.total_piastres} />
      </td>
      <td className="orders__amount">
        {row.base_piastres === null ? (
          "—"
        ) : (
          <Money
            piastres={row.base_piastres}
            kind={row.commission_state === "earned" ? "agreed" : "provisional"}
          />
        )}
      </td>
      <td className="orders__paid-by">
        {row.paid_in_month && (
          <>
            {formatMonth(row.paid_in_month)}
            {row.is_carried && (
              <span className="orders__carried-note">carried from {formatMonth(row.business_month)}</span>
            )}
          </>
        )}
      </td>
    </tr>
  );
}
