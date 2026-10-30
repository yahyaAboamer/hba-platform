import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import {
  OpsIcon,
  age,
  clockTime,
  dayAndTime,
  useIsNarrow,
  useNow,
  useOpsTab,
  waitingLabel,
} from "../components/OpsSource";
import "./OperationsDashboard.css";

/**
 * Operations → WhatsApp: order confirmations that went wrong (ADR 0059,
 * point 18; the approved mockup `docs/design/whatsapp-inbox-2026-10-11.html`,
 * frame 4).
 *
 * It only reads, as the rest of Operations does, and it shows an order
 * number and a reason with no name, phone or message: the server sends none.
 * Each order opens in the Inbox, where the fix is made.
 *
 * These are the platform's own records, so the counts are current whenever
 * the platform answers. What can go stale is WhatsApp itself, and the line
 * beside the heading says when it was last heard from.
 */

const CARDS = ["failed", "no_whatsapp", "never_messaged", "answers_not_recorded", "waiting"] as const;
type CardKey = (typeof CARDS)[number];

type Order = {
  order_id: string;
  order: string | null;
  placed_at: string | null;
  waiting_days: number | null;
  why: string | null;
  state: string;
  answer: string | null;
  tag: string | null;
};

type WhatsAppTab = {
  connected: boolean;
  sending: boolean;
  last_heard_at: string | null;
  quiet_since: string | null;
  read_at: string;
  days: number;
  cards: Record<CardKey, number>;
  orders: Order[] | null;
};

/** The answer, and the card whose orders it was asked for. */
type Loaded = WhatsAppTab & { card: CardKey | null };

const COPY: Record<CardKey, { label: string; note: string; hint: string; why: string }> = {
  failed: {
    label: "Failed to send",
    note: "Tried 5 times and gave up",
    hint: "Each order opens in the Inbox, where the message is sent again.",
    why: "WhatsApp was not answering",
  },
  no_whatsapp: {
    label: "No WhatsApp",
    note: "The number has no WhatsApp: call instead",
    hint: "Each order opens in the Inbox, where the number to call is.",
    why: "The number has no WhatsApp",
  },
  never_messaged: {
    label: "Never messaged",
    note: "No phone, or not a valid number",
    hint: "Each order opens in the Inbox. The phone is corrected on the order in Shopify.",
    why: "No phone, or not a valid number",
  },
  answers_not_recorded: {
    label: "Answers not recorded",
    note: "A tap that could not be turned into a tag",
    hint: "The answer is kept in the Inbox. Only the tag in Shopify is missing.",
    why: "The tag could not be written to Shopify",
  },
  waiting: {
    label: "Waiting over 24 hours",
    note: "Delivered, no button tapped",
    hint: "Each order opens in the Inbox, where the customer can be reached.",
    why: "No answer yet",
  },
};

/** The Confirmations card an order stands under in the Inbox. */
function inboxAddress(order: Order): string {
  const card =
    order.answer ??
    (order.state === "sent" ? "waiting" : order.state === "no_whatsapp" ? "no_whatsapp" : "not_sent");
  return `/inbox/confirmations?card=${card}&order=${encodeURIComponent(order.order_id)}`;
}

function OrderLink({ order }: { order: Order }) {
  return (
    <Link className="ops-ext num" to={inboxAddress(order)}>
      {order.order ?? order.order_id}
      <OpsIcon name="right" />
      <span className="visually-hidden"> (opens in the Inbox)</span>
    </Link>
  );
}

function Tag({ order }: { order: Order }) {
  if (!order.tag) return <span className="ops-muted">None yet</span>;
  return <span className="ops-tag ops-tag--hit">{order.tag}</span>;
}

function OrderList({
  card,
  count,
  orders,
  narrow,
}: {
  card: CardKey;
  count: number;
  orders: Order[];
  narrow: boolean;
}) {
  const copy = COPY[card];
  const titleId = `ops-list-${card}`;
  const waiting = (order: Order) =>
    order.waiting_days === null ? "—" : waitingLabel(order.waiting_days);

  return (
    <section className="panel" id={`ops-list-panel-${card}`} aria-labelledby={titleId}>
      <div className="panel__head">
        <h2 className="panel__title" id={titleId}>
          {copy.label} · {count}
          {narrow ? "" : count === 1 ? " order" : " orders"}
        </h2>
        {!narrow && <p className="ops-hint">{copy.hint}</p>}
      </div>
      {narrow ? (
        <ul className="ops-rows">
          {orders.map((order) => (
            <li key={order.order_id}>
              <div className="ops-rows__top">
                <OrderLink order={order} />
                <span className={order.waiting_days === 0 ? "ops-muted" : undefined}>
                  {waiting(order)}
                </span>
              </div>
              <div className="ops-rows__tags ops-muted">{order.why ?? copy.why}</div>
              <div className="ops-rows__tags">
                <Tag order={order} />
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <table className="ops-table">
          <thead>
            <tr>
              <th scope="col">Order</th>
              <th scope="col">Placed</th>
              <th scope="col">Waiting</th>
              <th scope="col">Why</th>
              <th scope="col">Tags</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => (
              <tr key={order.order_id}>
                <td>
                  <OrderLink order={order} />
                </td>
                <td className="num">{order.placed_at ? dayAndTime(order.placed_at) : "—"}</td>
                <td className={order.waiting_days === 0 ? "ops-muted" : undefined}>
                  {waiting(order)}
                </td>
                <td>{order.why ?? copy.why}</td>
                <td>
                  <Tag order={order} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {orders.length < count && (
        <p className="ops-foot ops-muted">Showing the newest {orders.length}.</p>
      )}
    </section>
  );
}

export function OperationsWhatsApp() {
  const [open, setOpen] = useState<CardKey | null>(null);
  const now = useNow();
  const narrow = useIsNarrow();
  const { tab, failed, reload } = useOpsTab(
    () =>
      api
        .get<WhatsAppTab>(`/api/order-ops/whatsapp${open ? `?card=${open}` : ""}`)
        .then((body): Loaded => ({ ...body, card: open })),
    (body) => {
      // An emptied list closes, and stays closed if orders arrive again.
      setOpen((current) => (current && body.cards[current] === 0 ? null : current));
    },
  );

  // The orders behind a card are read when it is opened.
  useEffect(() => {
    if (open) reload();
  }, [open, reload]);

  const readMinutes = tab ? Math.floor((now - new Date(tab.read_at).getTime()) / 60_000) : 0;
  const heard = tab?.last_heard_at
    ? `WhatsApp last heard from ${age(tab.last_heard_at, now)} ago`
    : "WhatsApp not heard from yet";
  // The list on screen is the open card's own: never the last card's orders
  // under this one's heading while its answer is on the way.
  const orders = open && tab?.card === open && tab.orders && tab.cards[open] > 0 ? tab.orders : null;

  return (
    <>
      <header className="page__head">
        <div className="page__title">
          <h1>WhatsApp</h1>
          <span className="page__subtitle">
            Order confirmations that went wrong · last {tab?.days ?? 7} days
          </span>
        </div>
        {tab &&
          (failed ? (
            <p className="ops-fresh ops-fresh--stale">
              <OpsIcon name="clock" />
              Not updated for {age(tab.read_at, now)}
            </p>
          ) : (
            <p
              className="ops-fresh"
              title={`Read at ${clockTime(tab.read_at)}. Read again every minute.`}
            >
              <OpsIcon name="clock" />
              {readMinutes < 1 ? "Updated just now" : `Updated ${age(tab.read_at, now)} ago`}
              {tab.connected ? ` · ${heard}` : ""}
            </p>
          ))}
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

      {tab && !tab.connected && (
        <div className="ops-banner ops-banner--off" role="status">
          <OpsIcon name="plug" />
          <div>
            WhatsApp isn't connected yet.
            <small>
              An admin connects it in Settings → Shopify. Until then the platform sends no
              confirmation.
            </small>
          </div>
        </div>
      )}

      {tab && tab.connected && !tab.sending && (
        <div className="ops-banner ops-banner--off" role="status">
          <OpsIcon name="plug" />
          <div>
            The platform is not sending confirmations.
            <small>
              Sending is switched off in Settings. The cards count only what the platform itself
              has decided or sent.
            </small>
          </div>
        </div>
      )}

      {tab?.quiet_since && (
        <div className="ops-banner ops-banner--failed" role="alert">
          <OpsIcon name="alert" />
          <div>
            WhatsApp has not been heard from for {age(tab.quiet_since, now)}.
            <small>New confirmations may not be going out.</small>
          </div>
        </div>
      )}

      {tab && (
        <div className={failed ? "ops-tiles ops-tiles--old" : "ops-tiles"}>
          {CARDS.map((card) => {
            const count = tab.cards[card];
            const copy = COPY[card];
            // A failed read keeps the last numbers and says how old they are;
            // they never drop to 0.
            const asOf = failed ? (
              <span className="ops-tile__as-of">As of {clockTime(tab.read_at)}</span>
            ) : null;
            if (count === 0) {
              return (
                <div key={card} className="ops-tile ops-tile--zero">
                  <span className="ops-tile__label">{copy.label}</span>
                  <span className="ops-tile__value">0</span>
                  <span className="ops-tile__note">{copy.note}</span>
                  {asOf}
                </div>
              );
            }
            const isOpen = open === card;
            return (
              <button
                key={card}
                type="button"
                className="ops-tile"
                aria-expanded={isOpen}
                aria-controls={isOpen && orders ? `ops-list-panel-${card}` : undefined}
                onClick={() => setOpen(isOpen ? null : card)}
              >
                <span className="ops-tile__label">{copy.label}</span>
                <span className="ops-tile__value">{count}</span>
                <span className="ops-tile__note">{copy.note}</span>
                {asOf}
                {!narrow && (
                  <span className="ops-tile__more">
                    {isOpen ? "Hide orders" : "Show orders"}
                    <OpsIcon name={isOpen ? "up" : "down"} />
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}

      {tab && open && orders && (
        <OrderList card={open} count={tab.cards[open]} orders={orders} narrow={narrow} />
      )}
    </>
  );
}
