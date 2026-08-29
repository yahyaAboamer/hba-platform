import { useEffect, useState } from "react";

import { Money } from "../components/Money";
import { api } from "../lib/api";
import { formatEgp } from "../lib/money";
import "./MyYear.css";

type YearMonth = {
  month: string;
  number: number;
  label: string;
  state: "historical" | "open" | "agreed";
  /** `null` on a month the platform did not pay for. Not a zero. */
  earned_piastres: number | null;
  sales_piastres: number;
  orders: number;
};

type Year = {
  months: YearMonth[];
  total_earned_piastres: number;
  best_month_label: string | null;
  best_month_piastres: number | null;
  total_orders: number;
};

/**
 * Her year.
 *
 * **Two charts that measure different things.** The first attempt drew
 * earnings and sales, and the business caught it immediately: on a commission
 * arrangement those move together, so drawing both is drawing one thing with
 * two y-axes.
 *
 * So one is money and the other is a count, and they cannot restate each
 * other:
 *
 * - **What you earned** — a line, because money is a trend and the question is
 *   *am I going up?*, which the eye answers from a slope.
 * - **Orders that counted** — bars, because a count is a tally and bar heights
 *   compare exactly in a way points on a line do not.
 *
 * Sales appear only in the orders tooltip, where they make a bar mean
 * something. They are not a third series.
 *
 * A month before go-live is drawn hollow rather than at zero. Its sales are
 * real; the commission was agreed elsewhere, and a zero would be a claim that
 * she earned nothing (ADR 0014).
 */
export function MyYear() {
  const [year, setYear] = useState<Year | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Year>("/api/me/year")
      .then(setYear)
      .catch((caught) => setError(caught.message));
  }, []);

  if (error) {
    return (
      <p className="notice notice--refused" role="alert">
        {error}
      </p>
    );
  }
  if (year === null) return <p className="empty">Loading…</p>;

  if (year.months.length < 2) {
    return (
      <p className="empty">
        Once you have a few months here, this page will show how they compare.
      </p>
    );
  }

  return (
    <>
      <section className="panel year">
        <div className="panel__head">
          <h2 className="panel__title">What you have earned</h2>
        </div>
        <EarningsLine months={year.months} />
        <div className="year__facts">
          {year.best_month_label && (
            <div>
              <dt>Best month</dt>
              <dd>
                <Money piastres={year.best_month_piastres ?? 0} kind="agreed" />
                <span className="year__facts-sub">{year.best_month_label}</span>
              </dd>
            </div>
          )}
          <div>
            <dt>Since you joined</dt>
            <dd>
              <Money piastres={year.total_earned_piastres} kind="agreed" />
              <span className="year__facts-sub">
                across {year.months.length} months
              </span>
            </dd>
          </div>
        </div>
      </section>

      <section className="panel year">
        <div className="panel__head">
          <h2 className="panel__title">Orders that counted</h2>
          <span className="chip chip--quiet">{year.total_orders} in total</span>
        </div>
        <OrdersBars months={year.months} />
      </section>
    </>
  );
}

/** Where the pointer is, if anywhere. `null` means no tooltip. */
type Hover = { index: number; x: number; y: number } | null;

function EarningsLine({ months }: { months: YearMonth[] }) {
  const [hover, setHover] = useState<Hover>(null);

  const W = 320;
  const H = 140;
  const L = 8;
  const R = 8;
  const T = 12;
  const B = 24;

  const paid = months.filter((m) => m.earned_piastres !== null);
  const max = Math.max(...paid.map((m) => m.earned_piastres ?? 0), 1) * 1.15;
  const x = (i: number) =>
    months.length === 1 ? W / 2 : L + ((W - L - R) * i) / (months.length - 1);
  const y = (v: number) => T + (H - T - B) * (1 - v / max);

  // Only months with a figure join the line. A month before go-live has no
  // figure to plot, and connecting through it would draw a slope that never
  // happened.
  const drawn = months
    .map((m, i) => ({ m, i }))
    .filter((p) => p.m.earned_piastres !== null);
  const path = drawn
    .map((p, k) => `${k ? "L" : "M"}${x(p.i)},${y(p.m.earned_piastres ?? 0)}`)
    .join(" ");

  const active = hover === null ? null : months[hover.index];

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="What you earned each month">
        <defs>
          <linearGradient id="earn" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="currentColor" stopOpacity="0.16" />
            <stop offset="1" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
        </defs>

        <line className="chart__base" x1={L} x2={W - R} y1={y(0)} y2={y(0)} />

        {drawn.length > 1 && (
          <path
            className="chart__area"
            d={`${path} L${x(drawn[drawn.length - 1].i)},${y(0)} L${x(drawn[0].i)},${y(0)} Z`}
          />
        )}
        {drawn.length > 1 && <path className="chart__line" d={path} />}

        {months.map((m, i) =>
          m.earned_piastres === null ? (
            // Hollow, on the baseline. Its sales are real and its commission is
            // not ours to state, so it is present and not plotted.
            <circle key={m.month} className="chart__hollow" cx={x(i)} cy={y(0)} r={3.5} />
          ) : (
            <circle
              key={m.month}
              className={
                hover?.index === i ? "chart__point chart__point--on" : "chart__point"
              }
              cx={x(i)}
              cy={y(m.earned_piastres)}
              r={4}
            />
          ),
        )}

        {months.map((m, i) => (
          <text key={m.month} className="chart__tick" x={x(i)} y={H - 7} textAnchor="middle">
            {m.number}
          </text>
        ))}

        {/* One wide target per month. Fingers are not pointers. */}
        {months.map((m, i) => (
          <rect
            key={m.month}
            className="chart__hit"
            x={x(i) - (W - L - R) / months.length / 2}
            y={0}
            width={(W - L - R) / months.length}
            height={H}
            onMouseEnter={() =>
              setHover({ index: i, x: x(i) / W, y: y(m.earned_piastres ?? 0) / H })
            }
            onFocus={() =>
              setHover({ index: i, x: x(i) / W, y: y(m.earned_piastres ?? 0) / H })
            }
            onMouseLeave={() => setHover(null)}
            onBlur={() => setHover(null)}
            tabIndex={0}
            role="button"
            aria-label={`${m.label}: ${m.earned_piastres === null ? "not shown here" : formatEgp(m.earned_piastres)}`}
          />
        ))}
      </svg>

      {active && (
        <div
          className="chart__tip"
          style={{ left: `${hover!.x * 100}%`, top: `${hover!.y * 100}%` }}
        >
          {active.label}
          <b>
            {active.earned_piastres === null
              ? "Not shown here"
              : formatEgp(active.earned_piastres)}
          </b>
          <i>
            {active.state === "historical"
              ? "HBA paid you the old way"
              : active.state === "agreed"
                ? "Agreed"
                : "Still adding up"}
          </i>
        </div>
      )}
    </div>
  );
}

function OrdersBars({ months }: { months: YearMonth[] }) {
  const [hover, setHover] = useState<Hover>(null);

  const W = 320;
  const H = 124;
  const L = 8;
  const R = 8;
  const T = 10;
  const B = 24;

  const max = Math.max(...months.map((m) => m.orders), 1) * 1.15;
  const step = (W - L - R) / months.length;
  const width = step * 0.6;
  const y = (v: number) => T + (H - T - B) * (1 - v / max);
  const active = hover === null ? null : months[hover.index];

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Orders that counted each month">
        <line className="chart__base" x1={L} x2={W - R} y1={y(0)} y2={y(0)} />
        {months.map((m, i) => {
          const cx = L + step * i + step / 2;
          return (
            <g key={m.month}>
              <rect
                className={
                  hover?.index === i ? "chart__bar chart__bar--on" : "chart__bar"
                }
                x={cx - width / 2}
                y={y(m.orders)}
                width={width}
                height={Math.max(y(0) - y(m.orders), 1)}
                rx={3}
              />
              <text className="chart__tick" x={cx} y={H - 7} textAnchor="middle">
                {m.number}
              </text>
              <rect
                className="chart__hit"
                x={cx - step / 2}
                y={0}
                width={step}
                height={H}
                onMouseEnter={() => setHover({ index: i, x: cx / W, y: y(m.orders) / H })}
                onFocus={() => setHover({ index: i, x: cx / W, y: y(m.orders) / H })}
                onMouseLeave={() => setHover(null)}
                onBlur={() => setHover(null)}
                tabIndex={0}
                role="button"
                aria-label={`${m.label}: ${m.orders} orders counted`}
              />
            </g>
          );
        })}
      </svg>

      {active && (
        <div
          className="chart__tip"
          style={{ left: `${hover!.x * 100}%`, top: `${hover!.y * 100}%` }}
        >
          {active.label}
          <b>
            {active.orders} {active.orders === 1 ? "order" : "orders"}
          </b>
          {/* Sales live here rather than on a chart of their own. They make a
              bar mean something; as a second line they would restate the
              first. */}
          <i>{formatEgp(active.sales_piastres)} of sales</i>
        </div>
      )}
    </div>
  );
}
