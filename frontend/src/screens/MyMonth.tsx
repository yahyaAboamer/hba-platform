import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { usePortal } from "../components/AffiliateLayout";
import { Money } from "../components/Money";
import { PortalYearChart } from "../components/PortalYearChart";
import { api } from "../lib/api";
import { formatMonth } from "../lib/money";
import type { MyEarnings, MyPayments } from "../lib/portal";
import "./MyMonth.css";

/** Present server figures in the approved Home hierarchy. Approval is not payment. */
export function MyMonth() {
  const { month, months } = usePortal();
  const [body,setBody] = useState<MyEarnings | null>(null);
  const [payments,setPayments] = useState<MyPayments | null>(null);
  const [error,setError] = useState<string | null>(null);
  const [paymentError,setPaymentError] = useState<string | null>(null);
  const [retry,setRetry] = useState(0);
  useEffect(() => { let live=true; setBody(null); setError(null); setPayments(null); setPaymentError(null);
    api.get<MyEarnings>(`/api/me/earnings/${month}`).then(value=>{if(live)setBody(value);}).catch(e=>{if(live)setError(e.message);});
    api.get<MyPayments>("/api/me/payments").then(value=>{if(live)setPayments(value);}).catch(e=>{if(live)setPaymentError(e.message);});
    return ()=>{live=false;};
  },[month,retry]);
  if(error) return <p className="notice notice--refused" role="alert">{error} <button className="button" onClick={()=>setRetry(n=>n+1)}>Retry</button></p>;
  if(!body) return <p className="empty">Loading…</p>;
  const settlement=payments?.months.find(row=>row.month===month);
  const approval=body.state === "agreed" ? "Approved" : body.state === "historical" ? "Closed" : "In progress";
  const paymentLabel=settlement ? ({unpaid:"Not paid yet",partially_paid:"Part paid",settled:"Settled",overpaid:"Overpaid"}[settlement.state]) : "No payments recorded here for this month";
  return <div className="portal-home">
    <div className="portal-home__month"><h1>{formatMonth(month)}</h1><span className="state">{approval}</span></div>
    <section className="portal-home__hero">
      <h2>{body.state === "agreed" ? "Approved earnings" : "Your earnings"}</h2>
      <div className="portal-home__amount">{body.amount_piastres === null ? "—" : <Money piastres={body.amount_piastres} />}</div>
      {body.amount_piastres === null && <p className="portal-home__note">Earnings are not available for this month yet.</p>}
      <div className="portal-home__metrics"><div><span>Net sales counted</span><strong><Money piastres={body.sales.earned_piastres} /></strong></div>
        <div><span>Code uses</span><strong>{body.orders.uses ?? "—"}</strong></div></div>
      <div className="portal-home__states">
        <Link to="/orders?status=earned">{body.orders.earned} counted</Link>
        <Link to="/orders?status=pending">{body.orders.pending} pending</Link>
        <Link to="/orders?status=void">{body.orders.void} excluded</Link>
      </div>
    </section>
    <PortalYearChart month={month} eligible={months} />
    <Link className="portal-home__open" to={`/earnings?month=${month}`}>How this adds up <span>→</span></Link>
    {(body.credited_from ?? []).map(row=><div className="portal-home__correction" key={row.month}>{row.text}</div>)}
    {body.waiting_on?.length > 0 && <div className="portal-home__correction">{body.waiting_on.map(row=><p key={row.text}>{row.text}</p>)}</div>}
    <section className="portal-home__payment"><div><h2>Payment</h2>{paymentError ? <p role="alert">Could not load payment status. <button className="button" onClick={()=>setRetry(n=>n+1)}>Retry</button></p> : !payments ? <p>Loading payment status…</p> : <>
      <p>{paymentLabel}</p>{settlement && <strong><Money piastres={settlement.paid_piastres} /> recorded</strong>}
    </>}</div><Link to="/payments" aria-label="Open payment history">→</Link></section>
    <Link className="portal-home__history" to="/payments">View payment history →</Link>
  </div>;
}
