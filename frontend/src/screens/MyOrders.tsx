import { useEffect, useState } from "react";

import { usePortal } from "../components/AffiliateLayout";
import { Money } from "../components/Money";
import { api } from "../lib/api";
import { formatMonth } from "../lib/money";
import type { MyEarnings } from "../lib/portal";
import "./MyOrders.css";

/**
 * The orders behind the figure, so she can count them against her own list.
 *
 * **No customer appears here**, and not because anything filters them: §10.2's
 * order index never stored a name, an address or a phone number, so there is
 * nothing to leak. What she sees is her side of the sale — the order number,
 * when it was placed, what it was worth to her, and whether it counts yet.
 *
 * A row is never removed. §9.4 pays on delivery, so an order can go from
 * counting to not counting, and one that quietly disappeared would look like a
 * mistake somebody made rather than a parcel that did not arrive.
 */
export function MyOrders() {
  const { month } = usePortal();
  const [body, setBody] = useState<MyEarnings | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setBody(null);
    setError(null);
    api
      .get<MyEarnings>(`/api/me/earnings/${month}`)
      .then(setBody)
      .catch((caught) => setError(caught.message));
  }, [month]);

  if (error) {
    return (
      <p className="notice notice--refused" role="alert">
        {error}
      </p>
    );
  }

  if (body === null) return <p className="empty">Loading…</p>;

  if (body.orders_detail.length === 0) {
    return (
      <p className="empty">
        No orders used your code in {formatMonth(month)} yet.
      </p>
    );
  }

  return (
    <ul className="orders">
      {body.orders_detail.map((order) => (
        <li key={order.order_number} className="orders__row">
          <div className="orders__head">
            <span className="code orders__number">{order.order_number}</span>
            {/*
             * An order that did not arrive keeps its figure, struck through.
             *
             * The business asked whether to show it at all. Showing it is the
             * safer answer: hiding a cancelled order's amount invites the
             * worse guess - that the platform lost it - where a struck-through
             * E£1,200 lets her check it against her own record and move on. It
             * can never be mistaken for money coming.
             */}
            <Money
              piastres={order.base_piastres}
              kind={order.state === "earned" ? "agreed" : "provisional"}
              className={order.state === "void" ? "money--void" : undefined}
            />
          </div>
          <div className="orders__foot">
            <span className="orders__date">{onlyTheDate(order.placed_at)}</span>
            <span className={`state state--${order.state}`}>
              {order.state_text}
              {order.state === "void" && " · not counted"}
            </span>
          </div>
          {/*
           * §11.4. Only where a *different* month paid it. Labelling every row
           * would bury the one or two that matter, and these are the rows that
           * decide whether her own arithmetic closes.
           */}
          {/*
           * §11.4, and the one row that will be asked about - so it keeps its
           * explanation rather than moving behind an ⓘ. Labelling every row
           * would bury the one or two that matter.
           */}
          {order.paid_in_month && (
            <p className="orders__carried">
              Paid with {formatMonth(order.paid_in_month)}, at this
              month&rsquo;s rate
              <details className="expl">
                <summary aria-label="Why this was paid later">
                  <span className="info" aria-hidden="true">i</span>
                </summary>
                <div className="expl__body">
                  It had not reached the customer when this month closed, so it
                  was paid with the next one — still at the rate you were on
                  when you sold it, not the later month&rsquo;s.
                </div>
              </details>
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

/**
 * `2026-08-14T…` → `14 August`.
 *
 * The year is already on the month bar above, and repeating it on forty rows
 * is forty things to read past.
 */
function onlyTheDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
  });
}
