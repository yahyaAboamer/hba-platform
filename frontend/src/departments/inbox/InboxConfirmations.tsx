import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError, api } from "../../lib/api";
import { dayTimeLabel, formatPhone } from "../../lib/inbox";
import { OpsIcon, age, clockTime, useIsNarrow, useNow, useOpsTab } from "../../components/OpsSource";
import "../operations/OperationsDashboard.css";
import "./Inbox.css";

/**
 * Inbox → Confirmations: where every cash-on-delivery order's confirmation
 * message stands, and the one place a message is sent again (ADR 0059; the
 * approved mockup `docs/design/whatsapp-inbox-2026-10-11.html`, frame 3).
 *
 * A paid order is not here: it never gets a confirmation.
 *
 * The mockup draws one list, Not sent. The other five are drawn the same way
 * with the column that card is about - when it was sent, when she answered,
 * the number to call - and a way into the chat.
 */

const TILES = [
  "waiting", "edit", "cancelled", "not_sent", "no_whatsapp", "confirmed",
  // An unpaid international order's payment link (ADR 0062). Not in the
  // approved mockup: the owner asked for it on 18 October 2026.
  "awaiting_payment", "paid",
] as const;
type TileKey = (typeof TILES)[number];

type Order = {
  order_id: string;
  order: string | null;
  admin_url: string | null;
  state: string;
  answer: string | null;
  answered_at: string | null;
  placed_at: string | null;
  sent_at: string | null;
  why: string | null;
  can_send_again: boolean;
  customer: string | null;
  phone: string | null;
  conversation_id: number | null;
  kind?: "confirmation" | "payment";
  paid_at?: string | null;
  reminded_at?: string | null;
  needs_a_person?: boolean;
};

type Confirmations = {
  days: number;
  total: number;
  /** The action cards count only orders still open in Shopify (ADR 0063). */
  tiles: Record<TileKey, number>;
  /** How many of each action card's orders were already shipped or cancelled. */
  done?: Partial<Record<TileKey, number>>;
  orders: Order[] | null;
};

/** The answer, and the card whose orders it was asked for. */
type Loaded = Confirmations & { tile: TileKey | null };

const COPY: Record<TileKey, { label: string; note: string; column: string; hint?: string }> = {
  waiting: {
    label: "Waiting for an answer",
    note: "Message delivered, no answer yet",
    column: "Sent",
  },
  edit: { label: "Wants a change", note: "Asked for a change, not shipped yet", column: "Answered" },
  cancelled: {
    label: "Asked to cancel",
    note: "Asked to cancel, still open in Shopify",
    column: "Answered",
    hint: "Marked here only. The order itself is cancelled in Shopify.",
  },
  not_sent: {
    label: "Not sent",
    note: "The message never went out",
    column: "Why",
    hint: "Sending again never sends twice: an order that already has a message is refused.",
  },
  no_whatsapp: {
    label: "No WhatsApp",
    note: "The number has no WhatsApp: call instead",
    column: "Phone",
  },
  confirmed: {
    label: "Confirmed",
    note: "In WhatsApp, the Inbox or tagged in Shopify",
    column: "Answered",
  },
  awaiting_payment: {
    label: "Waiting for payment",
    note: "International: payment link sent, not paid yet",
    column: "Sent",
    hint: "One reminder goes 24 hours after the link. Unpaid after 3 days, get in touch. Nothing is cancelled automatically.",
  },
  paid: { label: "Paid by link", note: "International: paid after the link", column: "Paid" },
};

/** Why an order has no message, where the server recorded no reason. */
const WHY: Record<string, string> = {
  no_phone: "The order has no phone number",
  bad_phone: "The phone number on the order could not be read",
  failed: "WhatsApp was not answering",
  pending: "Being sent now",
  sending: "Being sent now",
};

function isTile(value: string | null): value is TileKey {
  return (TILES as readonly string[]).includes(value ?? "");
}

function OrderLink({ order }: { order: Order }) {
  const name = order.order ?? order.order_id;
  if (!order.admin_url) return <span className="num">{name}</span>;
  return (
    <a className="ops-ext num" href={order.admin_url} target="_blank" rel="noopener noreferrer">
      {name}
      <OpsIcon name="ext" />
      <span className="visually-hidden"> (opens in Shopify)</span>
    </a>
  );
}

function detail(tile: TileKey, order: Order, now: number): string {
  if (tile === "not_sent") return order.why ?? WHY[order.state] ?? "Not sent";
  if (tile === "no_whatsapp") return formatPhone(order.phone) || "—";
  if (tile === "paid") return order.paid_at ? dayTimeLabel(order.paid_at, now) : "—";
  if (tile === "awaiting_payment") {
    const sent = order.sent_at ? dayTimeLabel(order.sent_at, now) : "—";
    if (order.needs_a_person) return `${sent} · Unpaid for 3 days: get in touch`;
    return order.reminded_at ? `${sent} · Reminded` : sent;
  }
  const at = tile === "waiting" ? order.sent_at : order.answered_at;
  return at ? dayTimeLabel(at, now) : "—";
}

function Action({
  tile,
  order,
  busy,
  onSendAgain,
}: {
  tile: TileKey;
  order: Order;
  busy: boolean;
  onSendAgain: (order: Order) => void;
}) {
  const name = order.order ?? order.order_id;
  if (tile === "not_sent" && order.can_send_again) {
    return (
      <button
        type="button"
        className="inbox-btn inbox-btn--small"
        disabled={busy}
        onClick={() => onSendAgain(order)}
      >
        {busy ? "Sending…" : "Send again"}
        <span className="visually-hidden"> to {name}</span>
      </button>
    );
  }
  if (tile !== "not_sent" && tile !== "no_whatsapp" && order.conversation_id !== null) {
    return (
      <Link className="inbox-btn inbox-btn--quiet inbox-btn--small" to={`/inbox/chats/${order.conversation_id}`}>
        Open chat
        <span className="visually-hidden"> for {name}</span>
      </Link>
    );
  }
  if (!order.admin_url) return null;
  return (
    <a
      className="inbox-btn inbox-btn--quiet inbox-btn--small"
      href={order.admin_url}
      target="_blank"
      rel="noopener noreferrer"
    >
      Open in Shopify
      <span className="visually-hidden">: {name}</span>
    </a>
  );
}

function OrderList({
  tile,
  count,
  orders,
  narrow,
  now,
  here,
  busy,
  onSendAgain,
}: {
  tile: TileKey;
  count: number;
  orders: Order[];
  narrow: boolean;
  now: number;
  /** The order somebody followed a link to, from Operations. */
  here: string | null;
  busy: string | null;
  onSendAgain: (order: Order) => void;
}) {
  const copy = COPY[tile];
  const titleId = `inbox-list-${tile}`;
  const marked = useRef<HTMLElement | null>(null);

  // The order somebody came for is brought into view, once.
  useEffect(() => {
    marked.current?.scrollIntoView?.({ block: "center" });
  }, [here, tile]);

  const placed = (order: Order) => (order.placed_at ? dayTimeLabel(order.placed_at, now) : "—");
  const action = (order: Order) => (
    <Action tile={tile} order={order} busy={busy === order.order_id} onSendAgain={onSendAgain} />
  );

  return (
    <section className="panel" id={`inbox-list-panel-${tile}`} aria-labelledby={titleId}>
      <div className="panel__head">
        <h2 className="panel__title" id={titleId}>
          {copy.label} · {count}
          {narrow ? "" : count === 1 ? " order" : " orders"}
        </h2>
        {copy.hint && !narrow && <p className="ops-hint">{copy.hint}</p>}
      </div>
      {narrow ? (
        <ul className="ops-rows">
          {orders.map((order) => (
            <li
              key={order.order_id}
              className={order.order_id === here ? "inbox-here" : undefined}
              aria-current={order.order_id === here ? "true" : undefined}
              ref={order.order_id === here ? (node) => { marked.current = node; } : undefined}
            >
              <div className="ops-rows__top">
                <OrderLink order={order} />
                <span className="ops-muted num">{placed(order)}</span>
              </div>
              <div className="ops-rows__tags">
                {order.customer ?? "No name"} · <span className="ops-muted">{detail(tile, order, now)}</span>
              </div>
              <div className="inbox-rows__action">{action(order)}</div>
            </li>
          ))}
        </ul>
      ) : (
        <table className="ops-table">
          <thead>
            <tr>
              <th scope="col">Order</th>
              <th scope="col">Customer</th>
              <th scope="col">Placed</th>
              <th scope="col">{copy.column}</th>
              <th scope="col">
                <span className="visually-hidden">Action</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => (
              <tr
                key={order.order_id}
                className={order.order_id === here ? "inbox-here" : undefined}
                aria-current={order.order_id === here ? "true" : undefined}
                ref={order.order_id === here ? (node) => { marked.current = node; } : undefined}
              >
                <td>
                  <OrderLink order={order} />
                </td>
                <td>{order.customer ?? <span className="ops-muted">No name</span>}</td>
                <td className="num">{placed(order)}</td>
                <td className={tile === "not_sent" ? undefined : "num"}>{detail(tile, order, now)}</td>
                <td className="inbox-actions">{action(order)}</td>
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

export function InboxConfirmations() {
  const [params, setParams] = useSearchParams();
  const asked = params.get("card");
  const open: TileKey | null = isTile(asked) ? asked : null;
  const here = params.get("order");

  const now = useNow();
  const narrow = useIsNarrow();
  const [loadedAt, setLoadedAt] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [said, setSaid] = useState<{ tone: "done" | "refused"; text: string } | null>(null);

  const { tab, failed, reload } = useOpsTab(
    () =>
      api
        .get<Confirmations>(`/api/inbox/confirmations${open ? `?tile=${open}` : ""}`)
        .then((body): Loaded => ({ ...body, tile: open })),
    () => setLoadedAt(Date.now()),
  );

  // The orders behind a card are read when it is opened. Not on arrival: the
  // first read already asked for the card in the address.
  const arrived = useRef(false);
  useEffect(() => {
    if (!arrived.current) {
      arrived.current = true;
      return;
    }
    if (open) reload();
  }, [open, reload]);

  function toggle(tile: TileKey) {
    setSaid(null);
    setParams(open === tile ? {} : { card: tile }, { replace: true });
  }

  async function sendAgain(order: Order) {
    const name = order.order ?? order.order_id;
    setBusy(order.order_id);
    setSaid(null);
    try {
      await api.post(`/api/inbox/confirmations/${encodeURIComponent(order.order_id)}/send-again`);
      setSaid({ tone: "done", text: `${name} is queued to send again.` });
    } catch (error) {
      setSaid({
        tone: "refused",
        text: error instanceof ApiError ? error.message : `${name} could not be sent again.`,
      });
    } finally {
      setBusy(null);
      reload();
    }
  }

  // The list on screen is the open card's own: never the last card's orders
  // under this one's heading while its answer is on the way.
  const orders = open && tab?.tile === open && tab.orders ? tab.orders : null;
  const readAt = loadedAt ? new Date(loadedAt).toISOString() : null;

  return (
    <>
      <header className="page__head">
        <div className="page__title">
          <h1>Confirmations</h1>
          <span className="page__subtitle">
            Cash-on-delivery and unpaid international orders from the last {tab?.days ?? 7} days
            {tab ? ` · ${tab.total}` : ""}
          </span>
        </div>
        {readAt &&
          (failed ? (
            <p className="ops-fresh ops-fresh--stale">
              <OpsIcon name="clock" />
              Not updated for {age(readAt, now)}
            </p>
          ) : (
            <p className="ops-fresh" title={`Read at ${clockTime(readAt)}. Read again every minute.`}>
              <OpsIcon name="clock" />
              {now - (loadedAt ?? now) < 60_000 ? "Updated just now" : `Updated ${age(readAt, now)} ago`}
            </p>
          ))}
      </header>

      {failed && (
        <p className="notice notice--refused" role="alert">
          Couldn't load Confirmations.{" "}
          <button type="button" className="ops-linkbtn" onClick={reload}>
            Try again
          </button>
        </p>
      )}

      {!tab && !failed && <p className="loading">Loading…</p>}

      {tab && (
        <div className={failed ? "ops-tiles ops-tiles--old" : "ops-tiles"}>
          {TILES.map((tile) => {
            const count = tab.tiles[tile] ?? 0;
            const copy = COPY[tile];
            const settled = tab.done?.[tile] ?? 0;
            // What left this card because Shopify already settled it (ADR 0063).
            const done = settled > 0 && (
              <span className="ops-tile__note ops-muted">
                {/* An unpaid order that shipped stays on its card (ADR 0062). */}
                {settled} already {tile === "awaiting_payment" ? "cancelled" : "shipped or cancelled"}
              </span>
            );
            if (count === 0) {
              return (
                <div key={tile} className="ops-tile ops-tile--zero">
                  <span className="ops-tile__label">{copy.label}</span>
                  <span className="ops-tile__value">0</span>
                  <span className="ops-tile__note">{copy.note}</span>
                  {done}
                </div>
              );
            }
            const isOpen = open === tile;
            return (
              <button
                key={tile}
                type="button"
                className="ops-tile"
                aria-expanded={isOpen}
                aria-controls={isOpen && orders ? `inbox-list-panel-${tile}` : undefined}
                onClick={() => toggle(tile)}
              >
                <span className="ops-tile__label">{copy.label}</span>
                <span className="ops-tile__value">{count}</span>
                <span className="ops-tile__note">{copy.note}</span>
                {done}
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

      {said && (
        <p
          className={
            said.tone === "done" ? "notice notice--settled inbox-said" : "notice notice--refused inbox-said"
          }
          role={said.tone === "done" ? "status" : "alert"}
        >
          {said.text}
        </p>
      )}

      {tab && open && orders && orders.length > 0 && (
        <OrderList
          tile={open}
          count={tab.tiles[open]}
          orders={orders}
          narrow={narrow}
          now={now}
          here={here}
          busy={busy}
          onSendAgain={sendAgain}
        />
      )}
    </>
  );
}
