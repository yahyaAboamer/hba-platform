import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { usePortal } from "../components/AffiliateLayout";
import { Money } from "../components/Money";
import { api } from "../lib/api";
import { formatMonth } from "../lib/money";
import type { MyEarnings, MyOrder } from "../lib/portal";
import "./MyOrders.css";

/**
 * The orders behind the figure, so they can count them against their own list.
 *
 * **No customer appears here**, and not because anything filters them: §10.2's
 * order index never stored a name, an address or a phone number, so there is
 * nothing to leak. What they see is their side of the sale — the order number,
 * when it was placed, what it was worth to them, and whether it counts yet.
 *
 * A row is never removed. §9.4 pays on delivery, so an order can go from
 * counting to not counting, and one that quietly disappeared would look like a
 * mistake somebody made rather than a parcel that did not arrive.
 */

/** The three questions people actually arrive with. */
type Filter = "all" | "earned" | "pending";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "earned", label: "Counted" },
  { key: "pending", label: "Moving" },
];

export function MyOrders() {
  const { month } = usePortal();
  const [body, setBody] = useState<MyEarnings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    setBody(null);
    setError(null);
    // The month changed underneath them, so an expanded row from the last one
    // would be pointing at an order that is no longer on screen.
    setOpen(null);
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

  const all = body.orders_detail;

  if (all.length === 0) {
    return (
      <p className="empty">
        No orders used your code in {formatMonth(month)} yet.
      </p>
    );
  }

  const count = (key: Filter) =>
    key === "all" ? all.length : all.filter((o) => o.state === key).length;
  const shown = filter === "all" ? all : all.filter((o) => o.state === filter);

  return (
    <>
      {/*
       * **Counted and moving, because those are the two questions.** Nobody
       * opens this screen wondering about their orders in general; they are
       * either checking what has already counted or chasing what has not
       * arrived. Void has no tab of its own — an order that did not arrive is
       * something to notice in passing, not a list to go looking for.
       *
       * The counts are on the controls rather than in a summary line, so
       * choosing one and reading the answer are the same act.
       */}
      <div className="filters" role="group" aria-label="Which orders">
        {FILTERS.map((option) => (
          <button
            key={option.key}
            type="button"
            className="filters__option"
            aria-pressed={filter === option.key}
            onClick={() => {
              setFilter(option.key);
              setOpen(null);
            }}
          >
            {option.label} <span className="filters__count">{count(option.key)}</span>
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <p className="empty">
          {filter === "earned"
            ? "Nothing has counted yet this month."
            : "Nothing is on its way — every order this month has arrived or been cancelled."}
        </p>
      ) : (
        <ul className="orders">
          {shown.map((order) => (
            <Row
              key={order.order_number}
              order={order}
              month={month}
              open={open === order.order_number}
              onToggle={() =>
                setOpen((was) =>
                  was === order.order_number ? null : order.order_number,
                )
              }
            />
          ))}
        </ul>
      )}

      <p className="orders__note">
        No customer details are stored against an order, so none appear here. A
        row is never removed — an order that did not arrive stays, struck
        through.
      </p>
    </>
  );
}

function Row({
  order,
  month,
  open,
  onToggle,
}: {
  order: MyOrder;
  month: string;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <li className="orders__row">
      {/*
       * The whole row opens it. A chevron would be a 12px target on a screen
       * held one-handed, and there is nothing else on the row to press.
       */}
      <button
        type="button"
        className="orders__button"
        aria-expanded={open}
        onClick={onToggle}
      >
        <span className="orders__left">
          <span className="code orders__number">{order.order_number}</span>
          <span className="orders__meta">
            {onlyTheDate(order.placed_at)} · {order.state_text}
            {order.state === "void" && " · not counted"}
          </span>
        </span>
        <span className="orders__right">
          {/*
           * **An amount is printed only where there is one.**
           *
           * An order that did not arrive keeps its figure struck through
           * wherever the figure survives - that is the rule, and it lets
           * somebody check a cancelled order against their own record instead
           * of guessing the platform lost it.
           *
           * But it does not always survive. `normalise.py` stores Shopify's
           * *current* totals, which is correct for commission (§9.3 pays on
           * what the customer actually paid) and means a cancelled order
           * comes back worth zero. A struck-through E£0.00 then claims the
           * order was worth nothing *and* was cancelled, which is not a fact
           * about anything - it reads as a bug, and was reported as one.
           *
           * So: the figure where there is a figure, and the reason in the
           * expansion where there is not.
           */}
          {order.base_piastres > 0 && (
            <Money
              piastres={order.base_piastres}
              kind={order.state === "earned" ? "agreed" : "provisional"}
              className={order.state === "void" ? "money--void" : undefined}
            />
          )}
          <span
            className={
              order.commission
                ? "orders__earned orders__earned--paid"
                : "orders__earned"
            }
          >
            {order.commission
              ? `${order.commission} to you`
              : order.state === "pending"
                ? "counts on delivery"
                : "nothing earned"}
          </span>
        </span>
      </button>

      {open && (
        <div className="orders__detail">
          <p className="orders__explain">{explain(order, month)}</p>

          {/*
           * §11.4, and the one row that will be asked about. Kept inside the
           * expansion now rather than printed on every row: labelling all of
           * them would bury the one or two that matter.
           */}
          {order.paid_in_month && (
            <p className="orders__explain">
              It had not reached the customer when {formatMonth(month)} closed,
              so it was paid with {formatMonth(order.paid_in_month)} instead —
              still at the rate you were on when you sold it, not that
              month&rsquo;s. This is called{" "}
              <Link to="/glossary#carried-forward">carried forward</Link>.
            </p>
          )}
        </div>
      )}
    </li>
  );
}

/**
 * What this order did, in a sentence.
 *
 * The commission figure is the server's, never worked out here — §11.1's rule
 * about a second implementation applies to one order as much as to a month.
 * Where there is no figure the sentence says why rather than showing a zero.
 */
function explain(order: MyOrder, month: string): string {
  if (order.state === "earned") {
    return order.commission
      ? `Delivered, so it counts in ${formatMonth(month)}. Of ${order.base}, ${order.commission} is yours.`
      : `Delivered, so it counts in ${formatMonth(month)}.`;
  }
  if (order.state === "pending") {
    return `It counts the day it reaches the customer. If that is after HBA closes ${formatMonth(month)}, it is paid with the next month — still at this month's rate.`;
  }
  // Two different void rows. Where the amount survived, it is on screen and
  // they can match it; where the order was cancelled outright, Shopify clears
  // its value and there is nothing to match - so the row says that rather
  // than leaving somebody to wonder what the missing figure was.
  return order.base_piastres > 0
    ? "This parcel did not reach the customer, so it earns nothing. The amount stays here so you can match it against your own record."
    : "This order was cancelled, so it earns nothing. The shop clears the value of a cancelled order, which is why no amount is shown — the order number and the date are what to match it against.";
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
