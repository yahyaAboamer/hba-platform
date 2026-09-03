import { useState } from "react";
import { useEffect } from "react";

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

/** Which of the two questions is on screen. */
type Chart = "earned" | "orders";

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
 * - **Orders counted** — bars, because a count is a tally and bar heights
 *   compare exactly in a way points on a line do not.
 *
 * Sales appear only when a month is being read, where they make a bar mean
 * something. They are not a third series.
 *
 * **One at a time, chosen by a control**, rather than both stacked. Two full
 * charts and a facts row is more than a phone screen holds, and the pair were
 * being scrolled past rather than compared.
 *
 * **The month being read has a panel of its own, above the chart**, rather
 * than a tooltip floating over it. A tooltip has to be positioned, clamped to
 * the card, flipped when it would overflow, and dismissed - and on a phone it
 * covers the very months somebody is trying to compare it against. A fixed
 * panel has none of those problems and is always readable.
 *
 * A month before go-live is drawn hollow rather than at zero. Its sales are
 * real; the commission was agreed elsewhere, and a zero would be a claim that
 * they earned nothing (ADR 0014).
 */
export function MyYear() {
  const [year, setYear] = useState<Year | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chart, setChart] = useState<Chart>("earned");
  const [pick, setPick] = useState<number | null>(null);

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

  // Months the platform actually paid for. The rest are real months with real
  // sales whose commission was agreed elsewhere.
  const paidMonths = year.months.filter((m) => m.earned_piastres !== null).length;
  const before = year.months.length - paidMonths;

  // Opens on the most recent month rather than on nothing. An empty reading
  // panel above a chart is a hole somebody has to work out how to fill.
  const index = pick ?? year.months.length - 1;
  const active = year.months[index];

  return (
    <>
      <section className="year__lead">
        <p className="year__kicker">Your year</p>
        <Money
          piastres={year.total_earned_piastres}
          kind="agreed"
          className="year__total"
        />
        <p className="year__since">
          {/*
           * The months that have a figure, not every month they have. It said
           * "across 8 months" when seven of them contributed nothing to that
           * total — which reads as a very bad year rather than as a total that
           * does not cover them.
           */}
          earned across {paidMonths} {paidMonths === 1 ? "month" : "months"} on
          the platform
        </p>
      </section>

      <div className="filters" role="group" aria-label="What to compare">
        <button
          type="button"
          className="filters__option"
          aria-pressed={chart === "earned"}
          onClick={() => setChart("earned")}
        >
          What you earned
        </button>
        <button
          type="button"
          className="filters__option"
          aria-pressed={chart === "orders"}
          onClick={() => setChart("orders")}
        >
          Orders counted
        </button>
      </div>

      <section className="panel year">
        {/*
         * The month being read, above the chart rather than over it. Always
         * present, so there is never a state where the chart is showing
         * something nobody can name.
         */}
        <div className="reading" aria-live="polite">
          <p className="reading__month">{active.label}</p>
          <p className="reading__figure">
            {chart === "earned"
              ? active.earned_piastres === null
                ? "Not shown here"
                : formatEgp(active.earned_piastres)
              : `${active.orders} ${active.orders === 1 ? "order" : "orders"}`}
          </p>
          <p className="reading__note">{note(active, chart)}</p>
        </div>

        {chart === "earned" ? (
          <EarningsLine months={year.months} pick={index} onPick={setPick} />
        ) : (
          <OrdersBars months={year.months} pick={index} onPick={setPick} />
        )}

        {/*
         * **Why the chart is mostly empty**, said on the chart.
         *
         * A model who joined before go-live sees seven hollow months and one
         * point, and reads it as broken — which is exactly what happened. The
         * figures are missing on purpose: HBA paid those months before this
         * page existed and their rates live in the old system (ADR 0014).
         *
         * The sales are not missing, and the bars prove it, so the sentence
         * points at them rather than apologising.
         */}
        {chart === "earned" && before > 0 && (
          <p className="year__caveat">
            {before === 1 ? "One month sits" : `${before} months sit`} on the
            line without a figure — HBA paid{" "}
            {before === 1 ? "it" : "them"} before this page existed. Everything
            you sold in {before === 1 ? "it" : "them"} is counted under{" "}
            <strong>Orders counted</strong>.
          </p>
        )}
        {chart === "orders" && (
          <p className="year__caveat">
            Every order that counted under your code, including the months HBA
            paid before this page existed.
          </p>
        )}
      </section>

      <div className="year__facts">
        {year.best_month_label && (
          <div className="tile">
            <span className="tile__label">Best month</span>
            <Money piastres={year.best_month_piastres ?? 0} kind="agreed" />
            <span className="tile__sub">{year.best_month_label}</span>
          </div>
        )}
        <div className="tile">
          <span className="tile__label">Orders counted</span>
          <span className="tile__figure">{year.total_orders}</span>
          <span className="tile__sub">all time</span>
        </div>
      </div>
    </>
  );
}

/** What the month being read is, under its figure. */
function note(month: YearMonth, chart: Chart): string {
  if (chart === "orders") {
    return `${formatEgp(month.sales_piastres)} of sales`;
  }
  if (month.earned_piastres === null) {
    return `${month.orders} ${month.orders === 1 ? "order" : "orders"} counted · HBA paid you the old way`;
  }
  return month.state === "agreed" ? "Agreed" : "Still adding up";
}

/**
 * One wide target per month, because fingers are not pointers.
 *
 * The charts used to answer a hover and nothing else, which is a thing a phone
 * does not have — so for every model who reads this on one, they answered
 * nothing at all.
 */
function pickable(index: number, onPick: (index: number) => void, label: string) {
  return {
    className: "chart__hit",
    tabIndex: 0,
    role: "button" as const,
    "aria-label": label,
    onClick: () => onPick(index),
    onFocus: () => onPick(index),
    onPointerEnter: (event: React.PointerEvent) => {
      if (event.pointerType === "mouse") onPick(index);
    },
  };
}

function EarningsLine({
  months,
  pick,
  onPick,
}: {
  months: YearMonth[];
  pick: number;
  onPick: (index: number) => void;
}) {
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

  return (
    <div className="chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="What you earned each month"
      >
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
            // Hollow, on the baseline. Its sales are real and its commission
            // is not ours to state, so it is present and not plotted.
            <circle
              key={m.month}
              className={
                pick === i ? "chart__hollow chart__hollow--on" : "chart__hollow"
              }
              cx={x(i)}
              cy={y(0)}
              r={pick === i ? 4.5 : 3.5}
            />
          ) : (
            <circle
              key={m.month}
              className={pick === i ? "chart__point chart__point--on" : "chart__point"}
              cx={x(i)}
              cy={y(m.earned_piastres)}
              r={pick === i ? 5 : 4}
            />
          ),
        )}

        {months.map((m, i) => (
          <text
            key={m.month}
            className={pick === i ? "chart__tick chart__tick--on" : "chart__tick"}
            x={x(i)}
            y={H - 7}
            textAnchor="middle"
          >
            {m.number}
          </text>
        ))}

        {months.map((m, i) => (
          <rect
            key={m.month}
            {...pickable(
              i,
              onPick,
              `${m.label}: ${m.earned_piastres === null ? "not shown here" : formatEgp(m.earned_piastres)}`,
            )}
            x={x(i) - (W - L - R) / months.length / 2}
            y={0}
            width={(W - L - R) / months.length}
            height={H}
          />
        ))}
      </svg>
    </div>
  );
}

function OrdersBars({
  months,
  pick,
  onPick,
}: {
  months: YearMonth[];
  pick: number;
  onPick: (index: number) => void;
}) {
  const W = 320;
  const H = 140;
  const L = 8;
  const R = 8;
  const T = 12;
  const B = 24;

  const max = Math.max(...months.map((m) => m.orders), 1) * 1.15;
  const step = (W - L - R) / months.length;
  const width = step * 0.6;
  const y = (v: number) => T + (H - T - B) * (1 - v / max);

  return (
    <div className="chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Orders that counted each month"
      >
        <line className="chart__base" x1={L} x2={W - R} y1={y(0)} y2={y(0)} />
        {months.map((m, i) => {
          const cx = L + step * i + step / 2;
          return (
            <g key={m.month}>
              <rect
                className={pick === i ? "chart__bar chart__bar--on" : "chart__bar"}
                x={cx - width / 2}
                y={y(m.orders)}
                width={width}
                height={Math.max(y(0) - y(m.orders), 1)}
                rx={3}
              />
              <text
                className={pick === i ? "chart__tick chart__tick--on" : "chart__tick"}
                x={cx}
                y={H - 7}
                textAnchor="middle"
              >
                {m.number}
              </text>
              <rect
                {...pickable(i, onPick, `${m.label}: ${m.orders} orders counted`)}
                x={cx - step / 2}
                y={0}
                width={step}
                height={H}
              />
            </g>
          );
        })}
      </svg>
    </div>
  );
}
