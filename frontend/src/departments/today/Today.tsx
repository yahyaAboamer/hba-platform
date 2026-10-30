import { Link } from "react-router-dom";

import { age, clockTime, dayMonth, useIsNarrow, useNow } from "../../components/OpsSource";
import { Icon } from "../../frame/Icon";
import { DEPARTMENTS } from "../index";
import "./today.css";
import type { TodayBody, TodayDepartment, TodayItem, TodayOrderRow, TodayOrders } from "./types";
import { useToday } from "./useToday";

/**
 * Today (Phase 2, Batch 2.2; the approved mockup's frame 1 and, on a phone,
 * frame 7): everything waiting for this person across the departments they
 * hold, with one button to open each thing where it is done, and the last
 * seven days' orders beside it.
 *
 * The server decides what is waiting, in what order, and how each time is
 * said; this only lays it out. It reads nothing itself - the frame's one read
 * of `/api/today` is shared with the sidebar's numbers.
 */

const CAIRO_DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Cairo" });
const HEADING_DATE = new Intl.DateTimeFormat("en-US", {
  timeZone: "Africa/Cairo",
  weekday: "long",
  day: "numeric",
  month: "long",
});

/** The Cairo calendar day of an instant, as a whole number of days. */
function dayNumber(moment: string | number): number {
  // A bare date is that day already, not UTC midnight.
  const key = typeof moment === "string" && /^\d{4}-\d{2}-\d{2}$/.test(moment) ? moment : CAIRO_DAY.format(new Date(moment));
  const [year, month, day] = key.split("-").map(Number);
  return Date.UTC(year, month - 1, day) / 86_400_000;
}

/** "Sunday 25 October", Cairo time. */
export function headingDate(now: number): string {
  const parts = Object.fromEntries(HEADING_DATE.formatToParts(new Date(now)).map((part) => [part.type, part.value]));
  return `${parts.weekday} ${parts.day} ${parts.month}`;
}

/** "1 thing is waiting for you", "9 things are waiting for you", "Nothing is waiting for you". */
export function waitingSentence(count: number): string {
  if (count === 0) return "Nothing is waiting for you";
  return count === 1 ? "1 thing is waiting for you" : `${count} things are waiting for you`;
}

/**
 * The time column, in the way the server asked for it:
 * `elapsed` "4 h 43 m" / "3 days", `since` "since 10:05" / "since yesterday" /
 * "since 26 Oct", `deadline` "7 days left", or nothing.
 */
export function whenText(item: Pick<TodayItem, "when" | "since" | "due">, now: number): string {
  if (item.when === "elapsed" && item.since) {
    const minutes = Math.max(0, Math.floor((now - new Date(item.since).getTime()) / 60_000));
    if (minutes < 60) return `${minutes} m`;
    if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} h ${minutes % 60} m`;
    const days = Math.floor(minutes / (24 * 60));
    return days === 1 ? "1 day" : `${days} days`;
  }
  if (item.when === "since" && item.since) {
    const days = dayNumber(now) - dayNumber(item.since);
    if (days <= 0) return `since ${clockTime(item.since)}`;
    return days === 1 ? "since yesterday" : `since ${dayMonth(item.since)}`;
  }
  if (item.when === "deadline" && item.due) {
    const left = dayNumber(item.due) - dayNumber(now);
    if (left < 0) return "overdue";
    if (left === 0) return "today";
    return left === 1 ? "1 day left" : `${left} days left`;
  }
  return "";
}

function departmentOf(key: TodayDepartment) {
  return DEPARTMENTS.find((department) => department.key === key);
}

/** "Inbox", "Inbox and Operations", "Inbox, Operations and Affiliates". */
function listOf(names: string[]): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** The department's icon, or the alert icon where something has broken. */
function ItemIcon({ item }: { item: TodayItem }) {
  return <Icon name={item.broken ? "alert" : (departmentOf(item.department)?.icon ?? "inbox")} />;
}

function Row({ item, now }: { item: TodayItem; now: number }) {
  const name = departmentOf(item.department)?.name ?? "";
  const when = whenText(item, now);
  return (
    <li className={item.broken ? "is-alert" : undefined}>
      <span className="wait__dept">
        <ItemIcon item={item} />
      </span>
      <span className="wait__what">
        {item.what}
        <small>
          <span className="wait__from">{name}</span>
          {item.detail && ` · ${item.detail}`}
        </small>
      </span>
      <span className={item.late ? "wait__when wait__when--late" : "wait__when"}>{when}</span>
      <Link className={item.broken ? "button button--row button--primary wait__go" : "button button--row wait__go"} to={item.go.to}>
        {item.go.label}
      </Link>
    </li>
  );
}

/** On a phone the whole row is the link; the button has nowhere to be. */
function PhoneRow({ item, now }: { item: TodayItem; now: number }) {
  const name = departmentOf(item.department)?.name ?? "";
  const when = whenText(item, now);
  return (
    <li>
      <Link className={item.broken ? "prow is-alert" : "prow"} to={item.go.to}>
        <span>
          <span className="prow__dept">
            <ItemIcon item={item} />
            {name}
          </span>
          <span className="prow__what">{item.what}</span>
          {when && <span className={item.late ? "prow__when prow__when--late" : "prow__when"}>{when}</span>}
        </span>
        <Icon name="chev" />
      </Link>
    </li>
  );
}

/** The week's orders as the mockup draws them: swatch, label, count, share. */
const SWATCH: Record<TodayOrderRow["key"], string> = {
  waiting: "var(--owed)",
  confirmed: "var(--bar)",
  with_bosta: "var(--faint)",
  delivered: "var(--accent)",
  cancelled: "var(--refused)",
  not_asked: "var(--rule-strong)",
};

function percent(count: number, placed: number): string {
  return placed > 0 ? `${((count / placed) * 100).toFixed(1)}%` : "0.0%";
}

/** "19–25 October", or "28 October – 3 November" across a month's end. */
export function weekRange(from: string, to: string): string {
  const [fromYear, fromMonth, fromDay] = from.split("-").map(Number);
  const [toYear, toMonth, toDay] = to.split("-").map(Number);
  const month = (year: number, index: number) =>
    new Intl.DateTimeFormat("en-US", { month: "long", timeZone: "UTC" }).format(new Date(Date.UTC(year, index - 1, 1)));
  return fromMonth === toMonth && fromYear === toYear
    ? `${fromDay}–${toDay} ${month(toYear, toMonth)}`
    : `${fromDay} ${month(fromYear, fromMonth)} – ${toDay} ${month(toYear, toMonth)}`;
}

/** The bar's words, for whoever cannot see it: every stage, with its count. */
export function ordersSentence(orders: TodayOrders): string {
  const stages = orders.rows.map((row) => `${row.count} ${row.label.charAt(0).toLowerCase()}${row.label.slice(1)}`);
  return `${orders.placed} ${orders.placed === 1 ? "order" : "orders"}: ${stages.join(", ")}`;
}

/** "09:38" today, "yesterday 09:38", "26 Oct" before that: an old reading says it is old. */
export function asOf(iso: string, now: number): string {
  const days = dayNumber(now) - dayNumber(iso);
  if (days <= 0) return clockTime(iso);
  return days === 1 ? `yesterday ${clockTime(iso)}` : dayMonth(iso);
}

function OrdersPanel({ orders, now }: { orders: TodayOrders; now: number }) {
  return (
    <section className="panel" aria-labelledby="flow-title">
      <div className="panel__head">
        <h2 className="panel__title" id="flow-title">Orders, last 7 days</h2>
        <p className="panel__hint">{weekRange(orders.from, orders.to)}</p>
      </div>
      <div className="flow">
        <div className="flow__bar" role="img" aria-label={ordersSentence(orders)}>
          {orders.rows
            .filter((row) => row.count > 0)
            .map((row) => (
              <span key={row.key} style={{ flex: row.count, background: SWATCH[row.key] }} />
            ))}
        </div>
        <table className="table">
          <tbody>
            {orders.rows.map((row) => {
              const source =
                row.key === "with_bosta" && orders.bosta_as_of
                  ? `${row.department} · as of ${asOf(orders.bosta_as_of, now)}`
                  : row.department;
              return (
                <tr key={row.key}>
                  <td>
                    <span className="swatch" style={{ background: SWATCH[row.key] }} />
                    {row.label}
                    {source && <small>{source}</small>}
                  </td>
                  <td className="r num">{row.count}</td>
                  <td className="r num muted">{percent(row.count, orders.placed)}</td>
                </tr>
              );
            })}
            <tr>
              <td><b>Placed</b></td>
              <td className="r num"><b>{orders.placed}</b></td>
              <td className="r num muted">100%</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** What stands where the list would be: nothing, a department that could not be read, or the items. */
function Notes({ body }: { body: TodayBody }) {
  const unread = body.unread ?? [];
  return (
    <>
      {body.items.length === 0 && unread.length === 0 && (
        <li className="wait__note">Nothing is waiting for you.</li>
      )}
      {unread.map((key) => (
        <li key={key} className="wait__note">
          {departmentOf(key)?.name ?? key} could not be read just now.
        </li>
      ))}
    </>
  );
}

export function Today() {
  const { body, readAt, failed } = useToday();
  const now = useNow();
  const narrow = useIsNarrow();
  // "Nothing is waiting" is not said while a department could not be read.
  const sub =
    body && !(body.items.length === 0 && (body.unread ?? []).length > 0)
      ? `${headingDate(now)} · ${waitingSentence(body.items.length)}`
      : headingDate(now);

  const minutes = readAt === null ? 0 : Math.floor((now - readAt) / 60_000);
  const readAgo = readAt === null ? null : minutes < 1 ? "just now" : `${age(new Date(readAt).toISOString(), now)} ago`;
  // A refresh that failed after an earlier read keeps that read, and says so.
  const updated = readAgo === null ? null : failed ? `Could not refresh · Updated ${readAgo}` : `Updated ${readAgo}`;

  const held = body ? listOf(body.departments.map((key) => departmentOf(key)?.name ?? key)) : "";

  const list = !body ? (
    <p className="today__state" role={failed ? "alert" : "status"}>
      {failed ? "Could not read what is waiting. Trying again every 30 seconds." : "Reading what is waiting…"}
    </p>
  ) : narrow ? (
    <ul className="prows">
      {body.items.map((item) => (
        <PhoneRow key={item.key} item={item} now={now} />
      ))}
      <Notes body={body} />
    </ul>
  ) : (
    <ul className="wait">
      {body.items.map((item) => (
        <Row key={item.key} item={item} now={now} />
      ))}
      <Notes body={body} />
    </ul>
  );

  if (narrow) {
    return (
      <div className="today today--phone">
        {/* The bar above shows the title; the page still has its heading. */}
        <h1 className="visually-hidden">Today</h1>
        <p className="psub">{sub}</p>
        {body ? list : <div className="panel">{list}</div>}
        {body?.orders && <OrdersPanel orders={body.orders} now={now} />}
      </div>
    );
  }

  return (
    <>
      <header className="page__head">
        <div className="page__title">
          <h1>Today</h1>
          <span className="page__subtitle">{sub}</span>
        </div>
        {updated && (
          <p className="today__fresh" role="status">
            <Icon name="clock" />
            {updated}
          </p>
        )}
      </header>
      <div className={body?.orders ? "today" : "today today--single"}>
        <section className="panel" aria-labelledby="wait-title">
          <div className="panel__head">
            <h2 className="panel__title" id="wait-title">Waiting for you</h2>
            {held && <p className="panel__hint">From {held}</p>}
          </div>
          {list}
        </section>
        {body?.orders && <OrdersPanel orders={body.orders} now={now} />}
      </div>
    </>
  );
}
