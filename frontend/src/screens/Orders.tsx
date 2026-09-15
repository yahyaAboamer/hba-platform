import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

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
  totals: {
    orders: number;
    held: number;
    unattributed: number;
    carried: number;
    /** What did not fail or get cancelled, added up by the server. */
    counted: string;
  };
};

type OrderDetailBody = OrderRow & {
  commission_piastres: number | null;
  lines: {
    title: string;
    variant: string | null;
    quantity: number;
    total_piastres: number;
  }[];
};

/** The export loads twenty-five at a time and says how many are left. */
const STEP = 25;

/**
 * An order's state in the export's three words, and a fourth it never drew.
 *
 * *Delivered*, *Pending* and *Failed delivery* are the export's own; the tone
 * is too - accent, amber, red. *Cancelled* is ours, because Shopify cancels
 * orders and the export's sample shop never did, and it takes the red of a
 * failed delivery because it means the same thing for money: nothing earned.
 */
export function orderStatus(row: Pick<OrderRow, "cancelled" | "delivery_state">): {
  label: string;
  tone: "settled" | "owed" | "refused";
} {
  if (row.cancelled) return { label: "Cancelled", tone: "refused" };
  if (row.delivery_state === "delivered") return { label: "Delivered", tone: "settled" };
  if (row.delivery_state === "failed") return { label: "Failed delivery", tone: "refused" };
  return { label: "Pending", tone: "owed" };
}

function placedOn(iso: string, withYear = false): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    ...(withYear ? { year: "numeric" } : {}),
  });
}

/**
 * *Attributed orders* — `vOrders` in the approved export.
 *
 * A count and a search above one table of five columns: Order, Model with
 * the code under it, Date, Status, Net sales. Each row opens the order.
 *
 * This screen used to carry a strip of four counts, a row of filters, a
 * separate *Find* form and eight columns — *Commission*, *Base* and *Paid
 * by* among them. Those three are facts about one order rather than about
 * the month, and the export puts them where they are read one at a time: in
 * the order itself (`OrderDetail`, below). Held and code-less orders are
 * still here, said in the Model column where the reason they belong to
 * nobody is visible.
 *
 * Nothing on this page can be changed. It reads decisions `attributed_order`
 * and `payroll_snapshot` already made.
 */
export function Orders({ session }: { session: Session }) {
  const [query] = useSearchParams();
  const navigate = useNavigate();
  const [month, setMonth] = useState(
    query.get("month")?.match(/^\d{4}-(0[1-9]|1[0-2])$/)
      ? query.get("month")!
      : session.platform.working_month,
  );
  const [grid, setGrid] = useState<Grid | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lockNote, setLockNote] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(STEP);
  const [lookedUp, setLookedUp] = useState<"missing" | null>(null);

  useEffect(() => {
    setError(null);
    setGrid(null);
    setLimit(STEP);
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

  const needle = search.trim().toLowerCase().replace(/^#/, "");
  const month_rows = (grid?.orders ?? []).filter(
    (row) => !query.get("affiliate") || String(row.affiliate_id) === query.get("affiliate"),
  );
  const rows = month_rows.filter(
    (row) =>
      !needle ||
      [row.order_number, row.affiliate_name ?? "", ...row.discount_codes]
        .join(" ")
        .toLowerCase()
        .includes(needle),
  );

  /*
   * **The support question arrives as an order number, never as a month.**
   * The export's search narrows the month on screen, and so does this one;
   * pressing Enter on a number that is not in this month then looks it up
   * across every month and opens it, which is what the separate *Find* form
   * used to do from a second box.
   */
  async function lookUp(event: React.FormEvent) {
    event.preventDefault();
    if (!needle || rows.length > 0) return;
    try {
      const found = await api.get<OrderRow>(
        `/api/orders/lookup/${encodeURIComponent(search.trim())}`,
      );
      navigate(`/orders/${encodeURIComponent(found.shopify_order_id)}`);
    } catch {
      setLookedUp("missing");
    }
  }

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Attributed orders</h1>
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

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}
      {lockNote && <p className="notice orders__note">{lockNote}</p>}

      <form className="orders__bar" onSubmit={lookUp}>
        <span className="orders__count">
          {grid === null
            ? "…"
            : needle
              ? /* A search narrows the list; the counted figure is the
                 * server's for the whole month, and re-adding the visible
                 * rows here would be a second implementation of a money
                 * figure. So a narrowed list says how many, not how much. */
                `${rows.length} of ${month_rows.length} ${month_rows.length === 1 ? "order" : "orders"}`
              : `${month_rows.length} ${month_rows.length === 1 ? "order" : "orders"} · ${grid.totals.counted} counted`}
        </span>
        <input
          type="search"
          className="input orders__search"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setLookedUp(null);
            setLimit(STEP);
          }}
          placeholder="Search model, code or order"
          aria-label="Search model, code or order"
        />
      </form>

      {grid === null && !error && <p className="empty">Loading…</p>}

      {grid && (
        <div className="surface orders__surface">
          {month_rows.length === 0 ? (
            <p className="empty">No orders placed in {formatMonth(month)} yet.</p>
          ) : rows.length === 0 ? (
            <p className="empty">
              {lookedUp === "missing" || !/^\d+$/.test(needle)
                ? "No order matches that search."
                : "Not in this month. Press Enter to look for it in any month."}
            </p>
          ) : (
            <table className="table orders__table">
              <thead>
                <tr>
                  <th className="orders__ref">Order</th>
                  <th>Model</th>
                  <th className="orders__date">Date</th>
                  <th className="orders__status">Status</th>
                  <th className="orders__net">Net sales</th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, limit).map((row) => (
                  <OrderTableRow key={row.shopify_order_id} row={row} />
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {grid && rows.length > 0 && (
        <div className="orders__foot">
          <span>
            Showing {Math.min(limit, rows.length)} of {rows.length}
          </span>
          {rows.length > limit && (
            <button type="button" className="button button--row" onClick={() => setLimit(limit + STEP)}>
              Load {Math.min(STEP, rows.length - limit)} more of {rows.length}
            </button>
          )}
        </div>
      )}
    </>
  );
}

function OrderTableRow({ row }: { row: OrderRow }) {
  const navigate = useNavigate();
  const status = orderStatus(row);
  const open = `/orders/${encodeURIComponent(row.shopify_order_id)}`;

  return (
    /*
     * The export makes the whole row the way in. The order number is also a
     * real link, so the row is reachable by keyboard and a middle-click opens
     * it in a tab, which a row with only an `onClick` never is.
     */
    <tr className="orders__row" onClick={() => navigate(open)}>
      <td className="orders__ref">
        <Link to={open} onClick={(event) => event.stopPropagation()}>
          {row.order_number}
        </Link>
      </td>
      <td>
        {row.outcome === "attributed" ? (
          <span className="orders__model">{row.affiliate_name}</span>
        ) : row.outcome === "held" ? (
          <span className="orders__held">Held — two codes claim it</span>
        ) : (
          /* *No affiliate code* over a row that visibly carries HBA10 read as
           * a contradiction on staging. Where there is a code it simply
           * belongs to no model - a brand code, or one nobody registered. */
          <span className="orders__nobody">
            {row.discount_codes.length > 0 ? "No model" : "No affiliate code"}
          </span>
        )}
        {/* The code under the model, as the export stacks them. An unmatched
         *  code still shows — it is the reason the row belongs to nobody. */}
        {row.discount_codes.length > 0 && (
          <span className="orders__code">{row.discount_codes.join(" · ")}</span>
        )}
      </td>
      <td className="orders__date">{placedOn(row.placed_at)}</td>
      <td className={`orders__status orders__status--${status.tone}`}>{status.label}</td>
      <td className="orders__net">
        {/* Shopify zeroes a cancelled order's totals, so the zero is not what
         *  it sold for — the export writes *not available* for exactly this. */}
        {row.cancelled ? (
          <span className="orders__nobody">not available</span>
        ) : (
          <Money piastres={row.total_piastres} kind="agreed" />
        )}
      </td>
    </tr>
  );
}

/**
 * One order, opened — `vOrder` in the approved export.
 *
 * A card with the order's number and state, then five facts on hairlines:
 * the model and code, when it was placed, its net sales, the commission it
 * was worth, and which month it counts towards. Its product lines follow on
 * a surface of their own.
 *
 * Every figure is the server's. The commission is the same per-order
 * arithmetic a model sees on her own orders, at the rate of the month the
 * order belongs to.
 */
export function OrderDetail() {
  const { orderId = "" } = useParams();
  const [order, setOrder] = useState<OrderDetailBody | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setOrder(null);
    setError(null);
    api
      .get<OrderDetailBody>(`/api/orders/detail/${encodeURIComponent(orderId)}`)
      .then(setOrder)
      .catch((caught) => setError(caught.message));
  }, [orderId]);

  const status = order ? orderStatus(order) : null;
  const counts = order ? countsTowards(order) : null;

  return (
    <>
      <div className="page__head">
        <Link
          className="button orders__back"
          to={order ? `/orders?month=${order.business_month}` : "/orders"}
        >
          ← Attributed orders
        </Link>
        <div className="page__title">
          <h1>{order ? `Order ${order.order_number}` : "Order"}</h1>
          {order && (
            <span className="page__subtitle">{formatMonth(order.business_month)}</span>
          )}
        </div>
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}
      {!order && !error && <p className="empty">Loading…</p>}

      {order && status && counts && (
        <div className="order">
          <section className="order__card">
            <div className="order__head">
              <span className="order__ref">{order.order_number}</span>
              <span className={`pill order__pill orders__status--${status.tone}`}>
                {status.label}
              </span>
            </div>
            <dl className="order__facts">
              <div>
                <dt>Model</dt>
                <dd>
                  {order.outcome === "attributed" && order.affiliate_id !== null ? (
                    <Link
                      className="order__model"
                      to={`/affiliates/${order.affiliate_id}?section=performance&month=${order.business_month}`}
                    >
                      {order.affiliate_name}
                      {order.matched_codes.length > 0 && ` · ${order.matched_codes.join(" · ")}`}
                    </Link>
                  ) : order.outcome === "held" ? (
                    <span className="orders__held">Held — two codes claim it</span>
                  ) : (
                    <span className="orders__nobody">No affiliate code</span>
                  )}
                </dd>
              </div>
              <div>
                <dt>Placed</dt>
                <dd>{placedOn(order.placed_at, true)}</dd>
              </div>
              <div>
                <dt>Net sales</dt>
                <dd>
                  {order.cancelled ? (
                    <span className="orders__nobody">not available</span>
                  ) : (
                    <Money piastres={order.total_piastres} kind="agreed" />
                  )}
                </dd>
              </div>
              <div>
                <dt>Commission</dt>
                <dd>
                  {order.commission_piastres === null ? (
                    <span className="orders__nobody">Nothing earned</span>
                  ) : (
                    <Money piastres={order.commission_piastres} kind="agreed" />
                  )}
                </dd>
              </div>
              <div>
                <dt>Counts towards</dt>
                <dd className={`orders__status--${counts.tone}`}>{counts.label}</dd>
              </div>
            </dl>
          </section>

          {order.lines.length > 0 && (
            <section className="order__lines">
              <h2 className="order__lines-title">Products</h2>
              <ul>
                {order.lines.map((line, index) => (
                  <li key={`${line.title}-${index}`}>
                    <span>
                      {line.title}
                      {line.variant && <span className="orders__nobody"> · {line.variant}</span>}
                      {line.quantity > 1 && <span className="orders__nobody"> × {line.quantity}</span>}
                    </span>
                    <Money piastres={line.total_piastres} kind="agreed" />
                  </li>
                ))}
              </ul>
            </section>
          )}

          {order.lines.length === 0 && order.cancelled && (
            <p className="order__note">
              This order was cancelled in Shopify, so its original amount and
              product lines are not available.
            </p>
          )}
        </div>
      )}
    </>
  );
}

/**
 * *Counted in September 2026*, or *Excluded from it* — the export's line.
 *
 * Counted takes the month that actually paid it where that is a different
 * one (§11.4), because that is the month a model will find it in. A pending
 * order has not been decided either way, and says so rather than borrowing
 * one of the two answers.
 */
export function countsTowards(order: Pick<
  OrderRow,
  "outcome" | "commission_state" | "cancelled" | "delivery_state" | "business_month" | "paid_in_month"
>): { label: string; tone: "settled" | "owed" | "refused" | "quiet" } {
  if (order.outcome !== "attributed") return { label: "No model's month", tone: "quiet" };
  const month = formatMonth(order.paid_in_month ?? order.business_month);
  if (order.commission_state === "earned") return { label: `Counted in ${month}`, tone: "settled" };
  if (order.commission_state === "void" || order.cancelled || order.delivery_state === "failed") {
    return { label: `Excluded from ${formatMonth(order.business_month)}`, tone: "refused" };
  }
  return { label: "Waiting for delivery", tone: "owed" };
}
