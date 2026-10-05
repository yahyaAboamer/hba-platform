import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import {
  FreshLine,
  OpsIcon,
  SourceBanner,
  clockTime,
  dayAndTime,
  stateNow,
  useIsNarrow,
  useNow,
} from "../components/OpsSource";
import type { Freshness } from "../components/OpsSource";
import "./OperationsDashboard.css";

/**
 * Operations → Shopify: open orders not shipped yet, counted by their tags
 * (ADR 0057; PRD S1-S7; the approved mockup's frames 1 and 7).
 *
 * Every number comes from the platform's last read of Shopify, with its time.
 * Each card opens the orders behind it, below the cards, one list at a time;
 * every order opens in Shopify, where it is fixed. Nothing here writes.
 */

type Tag = { text: string; hit: boolean };
type Order = {
  order_number: string;
  placed_at: string;
  waiting_days: number;
  tags: Tag[];
  admin_url: string | null;
};
type Card = { key: string; count: number; orders: Order[] };
type ShopifyTab = { freshness: Freshness; total: number | null; cards: Card[] | null };

/** The cards' words, wide and on a phone, as the mockup has them. */
const COPY: Record<string, { label: string; note: string; short: string; hint?: string }> = {
  confirmed: { label: "Confirmed", note: "Confirmed, not shipped yet", short: "Not shipped yet" },
  no_answer: { label: "No answer", note: "Not tried a second time yet", short: "Not tried twice yet" },
  no_answer_no_whatsapp_sent: {
    label: "No answer, WhatsApp not sent",
    note: "No WhatsApp message sent yet",
    short: "Send a WhatsApp",
  },
  no_whatsapp: {
    label: "No WhatsApp",
    note: "The number has no WhatsApp: call instead",
    short: "Call instead",
  },
  bosta_sync_failed: {
    label: "Bosta sync failed",
    note: "Confirmed but never reached Bosta",
    short: "Never reached Bosta",
    hint: "Each order opens in Shopify, where it is sent to Bosta again.",
  },
  compression_not_call_confirmed: {
    label: "Compression, not call-confirmed",
    note: "Needs a confirmation call",
    short: "Needs a call",
  },
  cancel_in_shopify: {
    label: "Cancel in Shopify",
    note: "Tagged cancelled, still open in Shopify",
    short: "Still open in Shopify",
    hint: "Each order opens in Shopify, where it is cancelled.",
  },
};

/** Read again this often, so a new read shows without a reload. */
const REFRESH_MS = 60_000;

/** On a phone a list shows this many, then "Show the other N". */
const PHONE_FIRST = 3;

function waiting(days: number): string {
  if (days === 0) return "Today";
  return days === 1 ? "1 day" : `${days} days`;
}

function OrderLink({ order }: { order: Order }) {
  if (!order.admin_url) return <span className="num">{order.order_number}</span>;
  return (
    <a className="ops-ext num" href={order.admin_url} target="_blank" rel="noopener noreferrer">
      {order.order_number}
      <OpsIcon name="ext" />
      <span className="visually-hidden"> (opens in Shopify)</span>
    </a>
  );
}

function Tags({ tags }: { tags: Tag[] }) {
  return (
    <>
      {tags.map((tag) => (
        <span key={tag.text} className={tag.hit ? "ops-tag ops-tag--hit" : "ops-tag"}>
          {tag.text}
        </span>
      ))}
    </>
  );
}

function OrderList({ card, narrow }: { card: Card; narrow: boolean }) {
  const [all, setAll] = useState(false);
  const copy = COPY[card.key];
  const titleId = `ops-list-${card.key}`;
  const shown = narrow && !all ? card.orders.slice(0, PHONE_FIRST) : card.orders;
  const hidden = card.orders.length - shown.length;

  return (
    <section className="panel" id={`ops-list-panel-${card.key}`} aria-labelledby={titleId}>
      <div className="panel__head">
        <h2 className="panel__title" id={titleId}>
          {copy.label} · {card.count}
          {narrow ? "" : card.count === 1 ? " order" : " orders"}
        </h2>
        {!narrow && <p className="ops-hint">{copy.hint ?? "Each order opens in Shopify."}</p>}
      </div>
      {narrow ? (
        <>
          <ul className="ops-rows">
            {shown.map((order) => (
              <li key={order.order_number}>
                <div className="ops-rows__top">
                  <OrderLink order={order} />
                  <span className={order.waiting_days === 0 ? "ops-muted" : undefined}>
                    {waiting(order.waiting_days)}
                  </span>
                </div>
                <div className="ops-rows__tags">
                  <Tags tags={order.tags} />
                </div>
              </li>
            ))}
          </ul>
          {hidden > 0 && (
            <div className="ops-foot">
              <button type="button" className="ops-linkbtn" onClick={() => setAll(true)}>
                Show the other {hidden}
              </button>
            </div>
          )}
        </>
      ) : (
        <table className="ops-table">
          <thead>
            <tr>
              <th scope="col">Order</th>
              <th scope="col">Placed</th>
              <th scope="col">Waiting</th>
              <th scope="col">Tags</th>
            </tr>
          </thead>
          <tbody>
            {card.orders.map((order) => (
              <tr key={order.order_number}>
                <td>
                  <OrderLink order={order} />
                </td>
                <td className="num">{dayAndTime(order.placed_at)}</td>
                <td className={order.waiting_days === 0 ? "ops-muted" : undefined}>
                  {waiting(order.waiting_days)}
                </td>
                <td>
                  <Tags tags={order.tags} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export function OperationsShopify() {
  const [tab, setTab] = useState<ShopifyTab | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const now = useNow();
  const narrow = useIsNarrow();

  const load = useCallback(() => {
    api
      .get<ShopifyTab>("/api/order-ops/shopify")
      .then((body) => {
        setTab(body);
        setFailed(false);
        // A list whose card has emptied closes, and stays closed if it fills.
        setOpen((current) =>
          body.cards?.some((card) => card.key === current && card.count > 0) ? current : null,
        );
      })
      .catch(() => setFailed(true));
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const freshness = tab?.freshness;
  const cards = tab?.cards ?? null;
  const state = freshness ? stateNow(freshness, now) : null;
  const old = state === "stale" || state === "failed";
  const openCard = cards?.find((card) => card.key === open && card.count > 0) ?? null;

  return (
    <>
      <header className="page__head">
        <div className="page__title">
          <h1>Shopify</h1>
          <span className="page__subtitle">
            Open orders not shipped yet{tab?.total != null ? ` · ${tab.total}` : ""}
          </span>
        </div>
        {freshness && <FreshLine freshness={freshness} now={now} />}
      </header>

      {failed && (
        <p className="notice notice--refused" role="alert">
          Couldn't load this tab.{" "}
          <button type="button" className="ops-linkbtn" onClick={load}>
            Try again
          </button>
        </p>
      )}

      {!tab && !failed && <p className="loading">Loading…</p>}

      {freshness && <SourceBanner freshness={freshness} now={now} />}

      {state === "never" && !cards && (
        <div className="ops-tiles">
          {Object.entries(COPY).map(([key, copy]) => (
            <div key={key} className="ops-tile ops-tile--reading">
              <span className="ops-tile__label">{copy.label}</span>
              <span className="ops-tile__value">Reading…</span>
              <span className="ops-tile__note">{narrow ? copy.short : copy.note}</span>
            </div>
          ))}
        </div>
      )}

      {cards && freshness && (
        <div className={old ? "ops-tiles ops-tiles--old" : "ops-tiles"}>
          {cards.map((card) => {
            const copy = COPY[card.key];
            const asOf =
              old && freshness.updated_at ? (
                <span className="ops-tile__as-of">As of {clockTime(freshness.updated_at)}</span>
              ) : null;
            if (card.count === 0) {
              return (
                <div key={card.key} className="ops-tile ops-tile--zero">
                  <span className="ops-tile__label">{copy.label}</span>
                  <span className="ops-tile__value">0</span>
                  <span className="ops-tile__note">Nothing waiting</span>
                  {asOf}
                </div>
              );
            }
            const expanded = openCard?.key === card.key;
            return (
              <button
                key={card.key}
                type="button"
                className="ops-tile"
                aria-expanded={expanded}
                aria-controls={expanded ? `ops-list-panel-${card.key}` : undefined}
                onClick={() => setOpen(expanded ? null : card.key)}
              >
                <span className="ops-tile__label">{copy.label}</span>
                <span className="ops-tile__value">{card.count}</span>
                <span className="ops-tile__note">{narrow ? copy.short : copy.note}</span>
                {asOf}
                {!narrow && (
                  <span className="ops-tile__more">
                    {expanded ? "Hide orders" : "Show orders"}
                    <OpsIcon name={expanded ? "up" : "down"} />
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}

      {openCard && <OrderList key={openCard.key} card={openCard} narrow={narrow} />}
    </>
  );
}
