import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

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
type Filter = "all" | "earned" | "pending" | "void";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "earned", label: "Counted" },
  { key: "pending", label: "Pending" },
  { key: "void", label: "Excluded" },
];

export function MyOrders() {
  const { month } = usePortal();
  const [body, setBody] = useState<MyEarnings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query] = useSearchParams();
  const [filter, setFilter] = useState<Filter>((["earned","pending","void"].includes(query.get("status") ?? "") ? query.get("status") : "all") as Filter);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setBody(null);
    setError(null);
    // The month changed underneath them, so an expanded row from the last one
    // would be pointing at an order that is no longer on screen.
    setOpen(null);
    api
      .get<MyEarnings>(`/api/me/earnings/${month}`)
      .then(value => { if(live) setBody(value); })
      .catch((caught) => {if(live) setError(caught.message);});
    return () => {live=false;};
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
           * `placed_piastres` is the order as it was placed, which the
           * platform now keeps for exactly this row. It is `null` only where
           * the base already carries the figure, or on an order indexed
           * before the platform started asking Shopify for it - and there,
           * still, no zero is printed.
           */}
          {order.base_piastres > 0 ? (
            <Money
              piastres={order.base_piastres}
              kind={order.state === "earned" ? "agreed" : "provisional"}
              className={order.state === "void" ? "money--void" : undefined}
            />
          ) : (
            order.placed_piastres !== null && (
              <Money piastres={order.placed_piastres} className="money--void" />
            )
          )}
          {/*
           * **A void row mirrors a counted one**: the sale on top, what it
           * was worth to her underneath, both struck through. The business
           * asked for the figure rather than the words - "nothing earned"
           * says what did not happen and gives her nothing to check her own
           * record against.
           *
           * Struck rather than coloured. It is not money coming, and it must
           * never read as though it were.
           */}
          <span
            className={
              order.commission
                ? "orders__earned orders__earned--paid"
                : order.forgone
                  ? "orders__earned money--void"
                  : "orders__earned"
            }
          >
            {order.commission
              ? `${order.commission} to you`
              : order.forgone
                ? `${order.forgone} to you`
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
           * **What was in the order** (owner, 11 September 2026).
           *
           * Inside the expansion, not on the row: the list answers *what did
           * they buy* and the row answers *what did I earn*, and a garment
           * name printed beside a figure reads as though the figure belonged
           * to the garment.
           *
           * **Empty is not the same as none.** Contents are read only for
           * orders that earned somebody commission, and only from 07A
           * onwards, so an older order genuinely has nothing recorded - and
           * saying so is the difference between an honest gap and a claim
           * that somebody bought nothing.
           */}
          {order.contents.length > 0 ? (
            <ul className="orders__contents">
              {order.contents.map((line, index) => (
                <li key={`${line.title}-${index}`}>
                  <span className="orders__item">{line.title}</span>
                  {line.variant && (
                    <span className="orders__variant">{line.variant}</span>
                  )}
                  {line.quantity > 1 && (
                    <span className="orders__qty">&times;{line.quantity}</span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="detail__note">
              What was in this order was not recorded.
            </p>
          )}

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
  if (order.base_piastres > 0) {
    return "This parcel did not reach the customer, so it earns nothing. The amount stays here so you can match it against your own record.";
  }
  if (order.placed_piastres !== null) {
    return order.forgone
      ? `This order was cancelled, so it earns nothing. It came to ${order.placed} when it was placed, and would have been worth ${order.forgone} to you had it arrived — both shown struck through so you can match them against your own record.`
      : `This order was cancelled, so it earns nothing. ${order.placed} is what it came to when it was placed — kept here so you can match it against your own record.`;
  }
  // An order indexed before the platform started keeping the placed-at
  // figure. The order number and the date are still enough to match it.
  return "This order was cancelled, so it earns nothing, and the shop no longer holds what it came to. The order number and the date are what to match it against.";
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
