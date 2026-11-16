import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { pieces, plural, shortDay } from "../departments/production/next/format";
import { cutWords, unwrap } from "./logic";
import type { FactoryOrderRow } from "./types";

/** `/factory`: the factory's own open orders, in the order the server gives them (delivery date, nearest first). */
export function FactoryOrders() {
  const [orders, setOrders] = useState<FactoryOrderRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const latest = useRef(0);

  const load = useCallback(() => {
    const mine = ++latest.current;
    setError(null);
    api.get<unknown>("/api/factory/orders")
      .then((answer) => {
        if (latest.current === mine) setOrders(unwrap<FactoryOrderRow[]>(answer, "orders"));
      })
      .catch((caught) => {
        if (latest.current === mine) setError(caught instanceof Error ? caught.message : "Your orders could not be loaded.");
      });
  }, []);
  useEffect(() => {
    load();
    return () => {
      latest.current += 1;
    };
  }, [load]);

  if (error) {
    return (
      <>
        <p className="notice notice--refused" role="alert">{error}</p>
        <div className="factory__actions">
          <button type="button" className="button" onClick={load}>Try again</button>
        </div>
      </>
    );
  }
  if (!orders) return <p className="loading" role="status">Loading your orders…</p>;

  return (
    <>
      <h1 className="factory__h1">Your orders</h1>
      <p className="factory__sub">
        {orders.length === 0 ? "No open orders with HBA" : `${plural(orders.length, "order")} with HBA`}
      </p>
      {orders.length > 0 && (
        <ul className="factory__list">
          {orders.map((order) => (
            <li key={order.id}>
              <Link className="factory__row" to={`/factory/orders/${order.id}`}>
                <b>{order.style_name} · {order.colour}</b>
                <span className="factory__small">
                  {order.code} · {cutWords(order, pieces)} · {order.status_words}
                </span>
                <span className={`factory__small${order.moved ? " factory__late" : ""}`}>
                  Deliver by {shortDay(order.delivery_date)}
                  {order.moved && (order.moved_from ? ` · moved from ${shortDay(order.moved_from)}` : " · moved")}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <p className="factory__small factory__foot">Only your own orders appear here. No prices, costs or payments are shown.</p>
    </>
  );
}
