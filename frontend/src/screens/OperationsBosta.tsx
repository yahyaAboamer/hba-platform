import { useEffect, useState } from "react";

import { ApiError, api } from "../lib/api";
import {
  FreshLine,
  OpsIcon,
  SourceBanner,
  clockTime,
  dayAndTime,
  dayMonth,
  stateNow,
  useIsNarrow,
  useNow,
  useOpsTab,
} from "../components/OpsSource";
import type { Freshness } from "../components/OpsSource";
import "./OperationsDashboard.css";

/**
 * Operations → Bosta: what is stuck between HBA and its customers
 * (ADR 0057; PRD B1-B6; the approved mockup's frames 2 and 7).
 *
 * Four counts that open their orders, the last seven days of pickups, and
 * the success rate for a chosen range. Every order opens in Bosta. Bosta is
 * a source for operations only: nothing here is used for pay (ADR 0023).
 */

type Order = {
  tracking_number: string;
  shopify_order_number: string | null;
  type: string;
  status: string | null;
  created_at: string;
  collected_at: string | null;
  awb_printed_at: string | null;
  waiting_working_days: number | null;
  url: string;
};
type Card = { key: string; count: number; orders: Order[] };
type Day = { date: string; count: number; orders: Order[] };
type Pickups = { complete: boolean; read_back_to: string | null; days: Day[] };
type BostaTab = { freshness: Freshness; cards: Card[] | null; pickups: Pickups | null };
type Rate = {
  from: string;
  to: string;
  available: boolean;
  read_back_to?: string | null;
  successful?: number;
  unsuccessful?: number;
  finished?: number;
  rate?: number | null;
};

/** What a list shows besides the tracking number and the Shopify order. */
type Columns = "created" | "status" | "collected" | "day";

const CARDS: Record<
  string,
  { label: string; note: string; short: string; columns: Columns; airway: boolean }
> = {
  new_not_shipped: {
    label: "New, not shipped",
    note: "Waiting for pickup more than 2 working days",
    short: "Over 2 working days",
    columns: "created",
    airway: true,
  },
  not_printed: {
    label: "Not printed",
    note: "Airway bill not printed yet",
    short: "Airway bill",
    columns: "created",
    airway: true,
  },
  awaiting_action: {
    label: "Awaiting your action",
    note: "Bosta is waiting for HBA",
    short: "Waiting for HBA",
    columns: "status",
    airway: false,
  },
  shipped_not_delivered: {
    label: "Shipped, not delivered",
    note: "Collected more than 3 working days ago",
    short: "Over 3 working days",
    columns: "collected",
    airway: false,
  },
};

/** A long list shows this many first, then "Show the other N" (mockup). */
const FIRST = { wide: 5, narrow: 3 };

function workingDays(days: number | null): string {
  if (days === null) return "";
  return days === 1 ? "1 working day" : `${days} working days`;
}

function TrackingLink({ order }: { order: Order }) {
  return (
    <a className="ops-ext num" href={order.url} target="_blank" rel="noopener noreferrer">
      {order.tracking_number}
      <OpsIcon name="ext" />
      <span className="visually-hidden"> (opens in Bosta)</span>
    </a>
  );
}

function Airway({ order }: { order: Order }) {
  if (order.awb_printed_at) {
    return <span className="ops-yes">Printed {dayMonth(order.awb_printed_at)}</span>;
  }
  return (
    <span className="ops-no">
      <OpsIcon name="alert" />
      Not printed
    </span>
  );
}

function OrderList({
  id,
  title,
  hint,
  orders,
  columns,
  airway,
  narrow,
}: {
  id: string;
  title: string;
  hint: string;
  orders: Order[];
  columns: Columns;
  airway: boolean;
  narrow: boolean;
}) {
  const [all, setAll] = useState(false);
  const first = narrow ? FIRST.narrow : FIRST.wide;
  const shown = all ? orders : orders.slice(0, first);
  const hidden = orders.length - shown.length;
  const noun = orders.length === 1 ? "order" : "orders";
  const byCreation = columns === "created" || columns === "status";

  return (
    <section
      className="panel ops-list"
      id={`ops-list-panel-${id}`}
      aria-labelledby={`ops-list-${id}`}
    >
      <div className="panel__head">
        <h2 className="panel__title" id={`ops-list-${id}`}>
          {title} · {orders.length}
          {narrow ? "" : ` ${noun}`}
        </h2>
        {!narrow && <p className="ops-hint">{hint}</p>}
      </div>
      {narrow ? (
        <ul className="ops-rows">
          {shown.map((order) => (
            <li key={order.tracking_number}>
              <div className="ops-rows__top">
                <TrackingLink order={order} />
                <span>
                  {columns === "day" && order.collected_at
                    ? clockTime(order.collected_at)
                    : workingDays(order.waiting_working_days)}
                </span>
              </div>
              <div className="ops-rows__tags ops-muted">
                {[order.shopify_order_number, order.type, airway ? null : order.status]
                  .filter(Boolean)
                  .join(" · ")}
                {airway && (
                  <>
                    {" · "}
                    <Airway order={order} />
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <table className="ops-table">
          <thead>
            <tr>
              <th scope="col">Tracking number</th>
              <th scope="col">Shopify order</th>
              <th scope="col">Type</th>
              {columns !== "created" && <th scope="col">Status</th>}
              <th scope="col">{byCreation ? "Created on Bosta" : "Picked up"}</th>
              {columns !== "day" && <th scope="col">Waiting</th>}
              {airway && <th scope="col">Airway bill</th>}
            </tr>
          </thead>
          <tbody>
            {shown.map((order) => (
              <tr key={order.tracking_number}>
                <td>
                  <TrackingLink order={order} />
                </td>
                <td className="num">{order.shopify_order_number ?? "—"}</td>
                <td>{order.type}</td>
                {columns !== "created" && <td>{order.status ?? "—"}</td>}
                <td className="num">
                  {byCreation
                    ? dayMonth(order.created_at)
                    : order.collected_at
                      ? dayAndTime(order.collected_at)
                      : "—"}
                </td>
                {columns !== "day" && <td>{workingDays(order.waiting_working_days)}</td>}
                {airway && (
                  <td>
                    <Airway order={order} />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {hidden > 0 && (
        <div className="ops-foot">
          <button type="button" className="ops-linkbtn" onClick={() => setAll(true)}>
            Show the other {hidden}
          </button>
        </div>
      )}
    </section>
  );
}

// ── The last seven days ──────────────────────────────────────────────────────

const WEEKDAY = new Intl.DateTimeFormat("en-GB", { weekday: "long", timeZone: "UTC" });
const WEEKDAY_SHORT = new Intl.DateTimeFormat("en-GB", { weekday: "short", timeZone: "UTC" });

/** The weekday of a Cairo date ("2026-10-03"), read at its noon. */
function weekday(isoDate: string, narrow: boolean): string {
  return (narrow ? WEEKDAY_SHORT : WEEKDAY).format(new Date(`${isoDate}T12:00:00Z`));
}

function PickupDays({
  pickups,
  today,
  open,
  onOpen,
  narrow,
  asOf,
}: {
  pickups: Pickups;
  today: string;
  open: string | null;
  onOpen: (day: string) => void;
  narrow: boolean;
  /** The time of Bosta's last clean read, when that read is old. */
  asOf: string | null;
}) {
  const most = Math.max(1, ...pickups.days.map((day) => day.count));
  return (
    <section className="panel" aria-labelledby="ops-days-title">
      <div className="panel__head">
        <h2 className="panel__title" id="ops-days-title">
          Picked up, last 7 days
        </h2>
        {!narrow && <p className="ops-hint">Collected from HBA, by day</p>}
      </div>
      {!pickups.complete && (
        <p className="ops-panel-note" role="status">
          Still reading Bosta's history
          {pickups.read_back_to ? ` (back to ${dayMonth(pickups.read_back_to)} so far)` : ""}, so
          these days may be short.
        </p>
      )}
      {asOf && <p className="ops-panel-note">As of {asOf}.</p>}
      <ul className={pickups.complete && !asOf ? "ops-days" : "ops-days ops-days--old"}>
        {pickups.days.map((day) => {
          const label = (
            <span className="ops-day__label">
              {weekday(day.date, narrow)}
              <small>
                {dayMonth(day.date)}
                {day.date === today && !narrow ? " · today" : ""}
              </small>
            </span>
          );
          // A day history has not reached yet is not a 0, and not a day off.
          const unread =
            !pickups.complete && (!pickups.read_back_to || day.date < pickups.read_back_to);
          if (unread) {
            return (
              <li key={day.date}>
                <div className="ops-day ops-day--off">
                  {label}
                  <span className="ops-day__off">Not read yet</span>
                  <span className="ops-day__count">—</span>
                  <span />
                </div>
              </li>
            );
          }
          if (day.count === 0) {
            const friday = new Date(`${day.date}T12:00:00Z`).getUTCDay() === 5;
            return (
              <li key={day.date}>
                <div className="ops-day ops-day--off">
                  {label}
                  {friday ? (
                    <span className="ops-day__off">
                      {narrow ? "Day off" : "Day off, no pickups"}
                    </span>
                  ) : (
                    <span className="ops-bar" />
                  )}
                  <span className="ops-day__count">0</span>
                  <span />
                </div>
              </li>
            );
          }
          return (
            <li key={day.date}>
              <button
                type="button"
                className="ops-day"
                aria-expanded={open === day.date}
                aria-controls={open === day.date ? `ops-list-panel-day-${day.date}` : undefined}
                onClick={() => onOpen(day.date)}
              >
                {label}
                <span className="ops-bar">
                  <i style={{ width: `${(100 * day.count) / most}%` }} />
                </span>
                <span className="ops-day__count">{day.count}</span>
                <OpsIcon name="right" />
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// ── The success rate ─────────────────────────────────────────────────────────

type Preset = "today" | "day" | "last7" | "last30" | "range";

const PRESETS: [Preset, string][] = [
  ["today", "Today"],
  ["day", "A day…"],
  ["last7", "Last 7 days"],
  ["last30", "Last 30 days"],
  ["range", "From – to…"],
];

/** Today in Cairo, as "2026-10-06". */
function cairoToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Cairo" }).format(new Date());
}

function shift(isoDate: string, days: number): string {
  const moment = new Date(`${isoDate}T12:00:00Z`);
  moment.setUTCDate(moment.getUTCDate() + days);
  return moment.toISOString().slice(0, 10);
}

function bounds(preset: Preset, today: string, day: string, from: string, to: string) {
  if (preset === "today") return [today, today];
  if (preset === "day") return [day, day];
  if (preset === "last7") return [shift(today, -6), today];
  if (preset === "last30") return [shift(today, -29), today];
  return [from, to];
}

function SuccessRate({
  narrow,
  updatedAt,
  asOf,
}: {
  narrow: boolean;
  /** Bosta's last clean read: a new one asks for the rate again. */
  updatedAt: string | null;
  /** That read's time, when it is old. */
  asOf: string | null;
}) {
  const today = cairoToday();
  const [preset, setPreset] = useState<Preset>("last30");
  const [day, setDay] = useState(today);
  const [from, setFrom] = useState(shift(today, -29));
  const [to, setTo] = useState(today);
  const [rate, setRate] = useState<Rate | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [start, end] = bounds(preset, today, day, from, to);

  useEffect(() => {
    // A cleared date, or a new range on its way, never leaves the last
    // range's figure standing under the new choice.
    setRate(null);
    setProblem(null);
  }, [start, end]);

  useEffect(() => {
    if (!start || !end) return;
    let current = true;
    api
      .get<Rate>(`/api/order-ops/bosta/success-rate?from=${start}&to=${end}`)
      .then((body) => {
        if (current) setRate(body);
      })
      .catch((error: unknown) => {
        if (!current) return;
        setRate(null);
        setProblem(
          error instanceof ApiError && error.status === 422
            ? error.message
            : "Couldn't load the success rate.",
        );
      });
    return () => {
      current = false;
    };
  }, [start, end, updatedAt]);

  const value =
    rate?.available && rate.rate != null ? `${(rate.rate * 100).toFixed(1)}%` : null;

  return (
    <section className="panel" aria-labelledby="ops-rate-title">
      <div className="panel__head">
        <h2 className="panel__title" id="ops-rate-title">
          Success rate
        </h2>
        {!narrow && <p className="ops-hint">Counted the way Bosta's dashboard counts it</p>}
      </div>
      <div className="ops-filters" role="group" aria-label="Range">
        {PRESETS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            className="ops-chip"
            aria-pressed={preset === key}
            onClick={() => setPreset(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {preset === "day" && (
        <div className="ops-range">
          <label htmlFor="ops-rate-day">Day</label>
          <input
            id="ops-rate-day"
            type="date"
            value={day}
            min="2026-01-01"
            max={today}
            onChange={(event) => setDay(event.target.value)}
          />
        </div>
      )}
      {preset === "range" && (
        <div className="ops-range">
          <label htmlFor="ops-rate-from">From</label>
          <input
            id="ops-rate-from"
            type="date"
            value={from}
            min="2026-01-01"
            max={today}
            onChange={(event) => setFrom(event.target.value)}
          />
          <label htmlFor="ops-rate-to">to</label>
          <input
            id="ops-rate-to"
            type="date"
            value={to}
            min="2026-01-01"
            max={today}
            onChange={(event) => setTo(event.target.value)}
          />
        </div>
      )}
      <div className={asOf ? "ops-rate ops-rate--old" : "ops-rate"} aria-live="polite">
        {asOf && <p className="ops-tile__as-of">As of {asOf}</p>}
        {problem && <p className="ops-panel-note">{problem}</p>}
        {!problem && rate && !rate.available && (
          <p className="ops-panel-note">
            {rate.read_back_to
              ? `Not ready for this range yet: Bosta's history is read back to ${dayMonth(rate.read_back_to)} so far.`
              : "Reading Bosta…"}
          </p>
        )}
        {!problem && rate?.available && (
          <>
            {value ? (
              <>
                <p className="ops-rate__value">{value}</p>
                <div className="ops-meter" role="img" aria-label={`${value} successful`}>
                  <i style={{ width: value }} />
                </div>
              </>
            ) : (
              <p className="ops-rate__note">No finished orders in this range yet.</p>
            )}
            <p className="ops-rate__parts">
              <span className="ops-key">
                {(rate.successful ?? 0).toLocaleString("en-GB")} successful
              </span>
              <span className="ops-key ops-key--fail">
                {(rate.unsuccessful ?? 0).toLocaleString("en-GB")} unsuccessful
              </span>
              {!narrow && (
                <span className="ops-key ops-key--all ops-muted">
                  {(rate.finished ?? 0).toLocaleString("en-GB")} finished
                </span>
              )}
            </p>
            {!narrow && (
              <p className="ops-rate__note">
                Orders created on Bosta from {dayMonth(rate.from)} to {dayMonth(rate.to)}.
                Successful: delivered, exchanged, or a return collected. Unsuccessful: a delivery
                that came back to HBA.
              </p>
            )}
          </>
        )}
      </div>
    </section>
  );
}

// ── The tab ──────────────────────────────────────────────────────────────────

export function OperationsBosta() {
  const [open, setOpen] = useState<string | null>(null);
  const now = useNow();
  const narrow = useIsNarrow();
  const { tab, failed, reload } = useOpsTab(
    () => api.get<BostaTab>("/api/order-ops/bosta"),
    (body) =>
      // A list whose card or day has emptied closes, and stays closed if it fills.
      setOpen((current) => {
        const stillThere =
          body.cards?.some((card) => card.key === current && card.count > 0) ||
          body.pickups?.days.some((day) => `day:${day.date}` === current && day.count > 0);
        return stillThere ? current : null;
      }),
  );

  const freshness = tab?.freshness;
  const cards = tab?.cards ?? null;
  const pickups = tab?.pickups ?? null;
  const state = freshness ? stateNow(freshness, now) : null;
  const old = state === "stale" || state === "failed";
  const asOfTime = old && freshness?.updated_at ? clockTime(freshness.updated_at) : null;
  const today = cairoToday();

  const openCard = cards?.find((card) => card.key === open && card.count > 0) ?? null;
  const openDay =
    pickups?.days.find((day) => `day:${day.date}` === open && day.count > 0) ?? null;
  const toggle = (key: string) => setOpen(open === key ? null : key);

  const days = pickups && (
    <PickupDays
      pickups={pickups}
      today={today}
      open={openDay?.date ?? null}
      onOpen={(date) => toggle(`day:${date}`)}
      narrow={narrow}
      asOf={asOfTime}
    />
  );
  const rate = cards && (
    <SuccessRate narrow={narrow} updatedAt={freshness?.updated_at ?? null} asOf={asOfTime} />
  );

  return (
    <>
      <header className="page__head">
        <div className="page__title">
          <h1>Bosta</h1>
          <span className="page__subtitle">Every order HBA has on Bosta</span>
        </div>
        {freshness && <FreshLine freshness={freshness} now={now} />}
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

      {freshness && <SourceBanner freshness={freshness} now={now} />}

      {state === "never" && !cards && (
        <div className="ops-tiles">
          {Object.entries(CARDS).map(([key, copy]) => (
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
            const copy = CARDS[card.key];
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
                onClick={() => toggle(card.key)}
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

      {openCard && (
        <OrderList
          key={openCard.key}
          id={openCard.key}
          title={CARDS[openCard.key].label}
          hint="Oldest first. Each opens in Bosta."
          orders={openCard.orders}
          columns={CARDS[openCard.key].columns}
          airway={CARDS[openCard.key].airway}
          narrow={narrow}
        />
      )}

      {cards && (
        <div className="ops-split">
          {narrow ? (
            <>
              {rate}
              {days}
            </>
          ) : (
            <>
              {days}
              {rate}
            </>
          )}
        </div>
      )}

      {openDay && (
        <OrderList
          key={openDay.date}
          id={`day-${openDay.date}`}
          title={`Picked up ${dayMonth(openDay.date)}`}
          hint="Latest first. Each opens in Bosta."
          orders={openDay.orders}
          columns="day"
          airway={false}
          narrow={narrow}
        />
      )}
    </>
  );
}
