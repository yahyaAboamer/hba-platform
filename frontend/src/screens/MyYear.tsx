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
 * Their year.
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
 * they earned nothing (ADR 0014).
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

  // Months the platform actually paid for. The rest are real months with real
  // sales whose commission was agreed elsewhere.
  const paidMonths = year.months.filter(
    (m) => m.earned_piastres !== null,
  ).length;
  const before = year.months.length - paidMonths;

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

        {/*
         * **Why the chart is mostly empty**, said on the chart.
         *
         * A model who joined before go-live sees seven hollow months and one
         * point, and reads it as broken - which is exactly what happened. The
         * figures are missing on purpose: HBA paid those months before this
         * page existed and their rates live in the old system (ADR 0014).
         *
         * The sales are not missing, and the bars below prove it, so the
         * sentence points at them rather than apologising.
         */}
        {before > 0 && (
          <p className="year__caveat">
            {before === 1 ? "One month is" : `${before} months are`} not shown
            here — HBA paid {before === 1 ? "it" : "them"} before this page
            existed. Everything you sold in {before === 1 ? "it" : "them"} is in{" "}
            <strong>Orders that counted</strong> below.
          </p>
        )}
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
              {/*
               * The months that have a figure, not every month they have. It
               * said "E£3,829 across 8 months" when seven of them contributed
               * nothing to that total - which reads as a very bad year rather
               * than as a total that does not cover them.
               */}
              <span className="year__facts-sub">
                across {paidMonths} {paidMonths === 1 ? "month" : "months"}
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

/**
 * Keep the tooltip inside the card.
 *
 * Centred on the point and lifted above it, which is right in the middle of a
 * chart and wrong at both ends: on the last month it ran off the right edge
 * and lost half the figure, and on a tall point it was cut off by the top of
 * the card. Both were photographed on a phone before anybody noticed here.
 *
 * So it is clamped horizontally, and flips below the point when there is not
 * room above. The transform has to change with the flip, because the whole
 * position is relative to a corner that moves.
 */
function tipStyle(hover: NonNullable<Hover>): React.CSSProperties {
  const below = hover.y < 0.34;
  // 18% keeps a two-line tooltip clear of either edge at phone widths without
  // pulling it so far from its point that it stops pointing at anything.
  const left = Math.min(Math.max(hover.x, 0.18), 0.82);
  return {
    left: `${left * 100}%`,
    top: `${hover.y * 100}%`,
    transform: below
      ? `translate(-${left * 100}%, 22%)`
      : `translate(-${left * 100}%, -118%)`,
  };
}

/**
 * How a month gets read, on a phone as well as on a laptop.
 *
 * **These charts only answered a hover**, which is a thing a phone does not
 * have. Every model reads this on one, so the tooltips were unreachable for
 * everybody they were built for - the pointer handlers were written on a
 * laptop and tested on one.
 *
 * So: a **tap** selects a month and a second tap on the same month clears it,
 * which is the only way to dismiss a tooltip on a touch screen. Hover is kept
 * for a mouse, and guarded on `pointerType` - a touch also emits enter and
 * leave events, and letting those through makes the tooltip appear and vanish
 * in the same gesture.
 *
 * `onFocus` stays, so the charts are still readable by keyboard.
 */
function reading(
  index: number,
  x: number,
  y: number,
  setHover: React.Dispatch<React.SetStateAction<Hover>>,
) {
  const at = { index, x, y };
  return {
    onClick: () =>
      setHover((was) => (was?.index === index ? null : at)),
    onPointerEnter: (event: React.PointerEvent) => {
      if (event.pointerType === "mouse") setHover(at);
    },
    onPointerLeave: (event: React.PointerEvent) => {
      if (event.pointerType === "mouse") setHover(null);
    },
    onFocus: () => setHover(at),
    onBlur: () => setHover(null),
  };
}

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
            {...reading(i, x(i) / W, y(m.earned_piastres ?? 0) / H, setHover)}
            tabIndex={0}
            role="button"
            aria-label={`${m.label}: ${m.earned_piastres === null ? "not shown here" : formatEgp(m.earned_piastres)}`}
          />
        ))}
      </svg>

      {active && (
        <div className="chart__tip" style={tipStyle(hover!)}>
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
                {...reading(i, cx / W, y(m.orders) / H, setHover)}
                tabIndex={0}
                role="button"
                aria-label={`${m.label}: ${m.orders} orders counted`}
              />
            </g>
          );
        })}
      </svg>

      {active && (
        <div className="chart__tip" style={tipStyle(hover!)}>
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
