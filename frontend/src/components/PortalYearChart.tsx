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
export function chartPoints(values: (number | null)[]) {
  const max = Math.max(1, ...values.filter((v): v is number => v !== null && Number.isFinite(v)));
  return values.map((value, index) => value === null || !Number.isFinite(value) ? null : {
    x: values.length === 1 ? 180 : 38 + index * 284 / Math.max(1, values.length - 1),
    y: 132 - Math.max(0, value) / max * 102,
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
  const points = chartPoints(values);
  const scale = Math.max(1, ...values.filter((v): v is number => v !== null && Number.isFinite(v)));
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
      <svg viewBox="0 0 342 160" role="img" aria-label={`${metric === "sales" ? "Sales" : "Code uses"} by month`}>
        {[0,1,2,3].map(i => <g key={i}><line x1="38" x2="322" y1={132-i*34} y2={132-i*34} className="portal-chart__grid" />
          <text x="30" y={135-i*34} textAnchor="end">{metric === "sales" ? (scale*i/3 >= 100000 ? `${(scale*i/3/100000).toFixed(1)}K` : `${Math.round(scale*i/3/100)}`) : Math.round(scale*i/3)}</text></g>)}
        {metric === "sales" ? segments.map((path,i) => <polyline key={i} points={path} className="portal-chart__line" />) : points.map((p,i) => p && <rect key={i} x={p.x-7} y={p.y} width="14" height={132-p.y} rx="3" className="portal-chart__bar" />)}
        {points.map((p,i) => p && <g key={rows[i].month} onClick={() => setPicked(rows[i].month)}>
          <circle cx={p.x} cy={p.y} r={index === i ? 4 : 3} className="portal-chart__point" />
          <text x={p.x} y="150" textAnchor="middle" className={index === i ? "portal-chart__tick--on" : undefined}>{Number(rows[i].month.slice(5))}</text></g>)}
      </svg>
      <select className="portal-chart__pick" aria-label="Inspect chart month" value={selected.month} onChange={event => setPicked(event.target.value)}>
        {rows.map(row => <option key={row.month} value={row.month}>{formatMonth(row.month)}</option>)}
      </select>
      {values.every(value => value === null) && <p className="portal-home__note">This history is not available yet.</p>}
    </>}
  </section>;
}
