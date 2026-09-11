import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { usePortal } from "../components/AffiliateLayout";
import { Money } from "../components/Money";
import { api } from "../lib/api";
import { formatMonth } from "../lib/money";
import type { MyEarnings } from "../lib/portal";

export function MyCalculation() {
  const {month:selectedMonth,months}=usePortal();
  const [query]=useSearchParams();
  const month=query.get("month") ?? selectedMonth;
  const eligible=months.includes(month);
  const [body,setBody]=useState<MyEarnings|null>(null);
  const [error,setError]=useState<string|null>(null);
  const [retry,setRetry]=useState(0);
  useEffect(()=>{let live=true;setBody(null);setError(null);if(!eligible){setError("This month is not available in your history.");return;}api.get<MyEarnings>(`/api/me/earnings/${month}`).then(value=>{if(live)setBody(value);}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[month,retry,eligible]);
  if(error)return <p role="alert">{error} <button className="button" onClick={()=>setRetry(n=>n+1)}>Retry</button></p>;
  if(!body)return <p className="empty">Loading…</p>;
  return <div className="portal-home">
    <div className="portal-home__month"><h1>{formatMonth(month)}</h1><span className="state">{body.state === "agreed" ? "Approved" : body.state === "historical" ? "Closed" : "In progress"}</span></div>
    <dl className="portal-calculation">{body.makeup.map((line,index)=><div key={index}><dt>{line.label}{line.detail&&<small>{line.detail}</small>}</dt><dd><Money piastres={line.piastres}/></dd></div>)}
      <div><dt>{body.state === "agreed" ? "Approved earnings" : "Earnings"}</dt><dd>{body.amount_piastres === null ? "Not available" : <Money piastres={body.amount_piastres}/>}</dd></div>
    </dl>
    {(body.credited_from ?? []).map(row=><p className="portal-home__correction" key={row.month}>{row.text}</p>)}
    {body.note&&<p className="portal-home__note">{body.note}</p>}
    {body.policy_version&&<a href={`/policy/${body.policy_version.id}`}>Calculation rules →</a>}
  </div>;
}
