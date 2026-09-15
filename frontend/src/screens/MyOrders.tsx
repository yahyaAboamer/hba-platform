import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { usePortal } from "../components/AffiliateLayout";
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
 *
 * ## What the row leads with
 *
 * The approved portal puts **her commission** in the large figure and the sale
 * underneath it, which is the opposite of what this screen used to do. It is
 * the right way round: the sale is the shop's number and the commission is
 * hers, and she opened this screen to check hers.
 */

/** The three questions people actually arrive with. */
type Filter = "all" | "earned" | "pending" | "void";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "earned", label: "Counted" },
  { key: "pending", label: "Pending" },
  // Not the export's *Failed*: this one holds cancelled and refunded orders
  // too, and calling a cancelled order a failed delivery would describe
  // something that never happened.
  { key: "void", label: "Not counted" },
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

  const head = (
    <div className="orders__head">
      <h1>Orders</h1>
      <span>{formatMonth(month)}</span>
    </div>
  );

  if (body === null) return <>{head}<p className="empty">Loading…</p></>;

  const all = body.orders_detail;

  if (all.length === 0) {
    return (
      <>
        {head}
        <p className="empty">
          No orders used your code in {formatMonth(month)} yet.
        </p>
      </>
    );
  }

  const count = (key: Filter) =>
    key === "all" ? all.length : all.filter((o) => o.state === key).length;
  const shown = filter === "all" ? all : all.filter((o) => o.state === filter);

  return (
    <>
      {head}

      {/* The count lives on the control, so choosing one and reading the
          answer are the same act. */}
      <div className="orders__filters" role="group" aria-label="Which orders">
        {FILTERS.map((option) => (
          <button
            key={option.key}
            type="button"
            className="orders__filter"
            aria-pressed={filter === option.key}
            onClick={() => {
              setFilter(option.key);
              setOpen(null);
            }}
          >
            {option.label} <span className="orders__filter-count">{count(option.key)}</span>
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <p className="empty">
          {filter === "earned"
            ? "Nothing has counted yet this month."
            : filter === "pending"
              ? "Nothing is on its way — every order this month has arrived or been cancelled."
              : "Every order this month counts."}
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

      <p className="orders__note">Customer details aren&rsquo;t shown here.</p>
    </>
  );
}

/**
 * What the sale was, under the commission.
 *
 * Shopify zeroes a cancelled order's totals — correct for commission, since
 * §9.3 pays on what the customer actually paid — so a cancelled row's base is
 * `0` and says nothing about what the order was. `placed` is the figure as it
 * was placed, kept for exactly this line, and where neither exists the row
 * says so rather than printing a zero that reads as *it was worth nothing*.
 */
function saleLine(order: MyOrder): string {
  if (order.base_piastres > 0) return `${order.base} net sales`;
  if (order.placed !== null) return `${order.placed} when it was placed`;
  return "amount not available";
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
  const pieces = order.contents.reduce((total, line) => total + line.quantity, 0);
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
            {onlyTheDate(order.placed_at)} · {pieces > 0 ? `${pieces} ${pieces === 1 ? "piece" : "pieces"}` : "contents not recorded"}
          </span>
          {/* Her words for the state, from the server, in the tone that
              matches it: counted is money, on its way is not yet, and did
              not arrive is neither. */}
          <span className={`orders__pill orders__pill--${order.state}`}>{order.state_text}</span>
        </span>
        <span className="orders__right">
          {/*
           * **What it was worth to her**, and only where there is an answer.
           *
           * A void order keeps what it would have earned, struck through, so
           * she can still match the row against her own record — the business
           * asked for the figure rather than the words. Where there is no
           * figure at all the row prints a dash, never a zero: an order still
           * travelling has earned nothing *yet*.
           */}
          <span className={order.commission ? "orders__fee" : order.forgone ? "orders__fee money--void" : "orders__fee orders__fee--none"}>
            {order.commission ?? order.forgone ?? "—"}
          </span>
          <span className="orders__net">{saleLine(order)}</span>
        </span>
      </button>

      {open && (
        <div className="orders__detail">
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
                  <span className="orders__item">
                    {line.title}
                    {line.variant && (
                      <span className="orders__variant">{line.variant}</span>
                    )}
                  </span>
                  {line.quantity > 1 && (
                    <span className="orders__qty">&times;{line.quantity}</span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="orders__explain">
              What was in this order was not recorded.
            </p>
          )}

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
