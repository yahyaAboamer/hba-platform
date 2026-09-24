import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { formatEgp, formatMonth } from "../lib/money";

/**
 * A08. `uses` is **required**, and that is the point of writing it this way.
 *
 * It used to be optional, so `my_year` not sending it was not a mistake any
 * tool could see: Home read *37 uses* from the month card while the Uses tab
 * beside it said *this history is not available yet*, and both were behaving
 * exactly as written.
 *
 * `null` still means genuinely unknown and still draws "Not available". What
 * it can no longer mean is *nobody wired it up*.
 */
export type ChartMonth = { month: string; sales_piastres: number | null; uses: number | null; in_progress: boolean };
/*
 * The export's plot, to its numbers (`viewBox="-24 0 324 130"`): months from
 * x 8 to 292, the axis at y 102 and 88 high, three rules at 0, half and the
 * top, labelled at x 2, and the scale given headroom above the highest month
 * - 15% for sales, 35% for uses, so a bar's count fits over it.
 *
 * Two cases the export never meets and ours must: a single month (its
 * `284 * i / (n - 1)` divides by zero), drawn in the middle; and a year with
 * no sales (its `max * 1.15` is zero), drawn flat on the axis. A month with
 * no figure stays a gap, never a zero.
 *
 * **No axis text, because the approved page shows none.** The export's
 * markup has rule labels (*0 / 11k / 22k*) and month numbers, but its
 * runtime puts each one in an HTML `<span>` inside the SVG `<text>`, which no
 * browser draws: every label measures 0px wide and the rendered chart - the
 * one approved on a phone - is rules, line, points and bars only. Whether to
 * show what the markup intended is a question for the owner (checklist).
 */
const LEFT = 8;
const WIDTH = 284;
const AXIS = 102;
const HEIGHT = 88;

const known = (v: number | null): v is number => v !== null && Number.isFinite(v);

/** The top of the scale: the highest month plus the export's headroom. */
export function chartScale(values: (number | null)[], headroom: number): number {
  const max = Math.max(0, ...values.filter(known));
  return max > 0 ? max * headroom : 0;
}

export function chartPoints(values: (number | null)[], headroom = 1.15) {
  const scale = chartScale(values, headroom);
  return values.map((value, index) => !known(value) ? null : {
    x: values.length === 1 ? LEFT + WIDTH / 2 : LEFT + (WIDTH * index) / (values.length - 1),
    y: AXIS - (scale ? (HEIGHT * Math.max(0, value)) / scale : 0),
  });
}

export function PortalYearChart({ month, eligible }: { month: string; eligible: string[] }) {
  const [data, setData] = useState<ChartMonth[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<"sales" | "uses">("sales");
  const [picked, setPicked] = useState(month);
  const [retry, setRetry] = useState(0);
  useEffect(() => { let live = true; setData(null); setError(null);
    api.get<{months:ChartMonth[]}>("/api/me/year").then(body => { if(live) setData(body.months); }).catch(e => {if(live) setError(e.message);});
    return () => {live=false;};
  },[retry]);
  const rows = (data ?? []).filter(row => eligible.includes(row.month) && row.month.slice(0,4) === month.slice(0,4)).sort((a,b) => a.month.localeCompare(b.month));
  const index = Math.max(0, rows.findIndex(row => row.month === picked));
  const selected = rows[index];
  const values = rows.map(row => metric === "sales" ? row.sales_piastres : row.uses ?? null);
  const headroom = metric === "sales" ? 1.15 : 1.35;
  const points = chartPoints(values, headroom);
  const scale = chartScale(values, headroom);
  const step = WIDTH / Math.max(1, rows.length);
  const segments: string[] = []; let segment: string[] = [];
  points.forEach(point => { if(point) segment.push(`${point.x},${point.y}`); else if(segment.length) {segments.push(segment.join(" ")); segment=[];} });
  if(segment.length) segments.push(segment.join(" "));
  return <section className="portal-chart">
    <div className="portal-chart__heading"><h2>Your year</h2><span>{month.slice(0,4)}</span></div>
    <div className="portal-chart__switch" role="group" aria-label="Chart metric">
      {(["sales","uses"] as const).map(value => <button key={value} aria-pressed={metric === value} onClick={() => setMetric(value)}>{value === "sales" ? "Sales" : "Uses"}</button>)}
    </div>
    {error ? <p role="alert">Could not load your chart. <button className="button" onClick={() => setRetry(n=>n+1)}>Retry</button></p> : !data ? <p className="empty">Loading chart…</p> : !rows.length ? <p className="empty">No months to show yet.</p> : <>
      {/* Month, figure, and what the figure is — the export's three lines,
          above the plot they read from. */}
      <div className="portal-chart__readout"><span>{formatMonth(selected.month)}{selected.in_progress ? " · So far" : ""}</span>
        <strong>{values[index] === null ? "Not available" : metric === "sales" ? formatEgp(values[index]!) : `${values[index]} ${values[index] === 1 ? "use" : "uses"}`}</strong>
        <em>{metric === "sales" ? "net sales counted" : "orders placed with your code"}</em></div>
      <svg viewBox="-24 0 324 130" role="img" aria-label={`${metric === "sales" ? "Sales" : "Code uses"} by month`}>
        {[0, 1, 2].map((i) => <line key={i} x1={LEFT} x2={LEFT + WIDTH} y1={AXIS - HEIGHT * i / 2} y2={AXIS - HEIGHT * i / 2} className="portal-chart__grid" />)}
        {metric === "sales"
          ? <>
            {segments.map((path, i) => <polyline key={i} points={path} className="portal-chart__line" />)}
            {points.map((p, i) => p && <circle key={rows[i].month} cx={p.x} cy={p.y} r={index === i ? 5 : 3.5}
              className={index === i ? "portal-chart__point portal-chart__point--on" : "portal-chart__point"} />)}
          </>
          : values.map((value, i) => {
            if (!known(value)) return null;
            const h = Math.max(scale ? (HEIGHT * value) / scale : 0, 3);
            return <rect key={rows[i].month} x={LEFT + step * i + step * 0.22} y={AXIS - h} width={step * 0.56} height={h} rx="3"
              className={index === i ? "portal-chart__bar portal-chart__bar--on" : "portal-chart__bar"} />;
          })}
        {/* The month is chosen on the chart itself, as the export's is: a
            transparent column over each month (`hits`), the height of the
            plot, so a thumb need not find a small point. A keyboard reaches
            every month through them too. */}
        {rows.map((row, i) => <rect key={`hit-${row.month}`} x={LEFT + step * i} y="0" width={step} height="110" className="portal-chart__hit"
          role="button" tabIndex={0} aria-label={formatMonth(row.month)} aria-pressed={index === i}
          onClick={() => setPicked(row.month)}
          onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setPicked(row.month); } }} />)}
      </svg>
      {values.every(value => value === null) && <p className="portal-home__note">This history is not available yet.</p>}
    </>}
  </section>;
}
