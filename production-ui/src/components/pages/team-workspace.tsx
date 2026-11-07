"use client";
import { useState } from "react";
import { Badge, Panel, PageHeader, ProgressBar } from "@/components/ui";
import { qcSteps, type QcCheck, type TeamUser } from "@/lib/qc-checklist";
import type { ProductionOrder } from "@/lib/demo-data";
import { fixtureText } from "@/lib/fixtures";

export function TeamLogin({ user, refresh }: { user: TeamUser; refresh: () => Promise<void> }) {
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();setBusy(true);setError("");
    const form=new FormData(event.currentTarget);
    try {
      if(user.mustChangePassword && form.get("password")!==form.get("confirm")) throw new Error("Passwords do not match");
      const response=await fetch("/api/production/session",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({action:user.mustChangePassword ? "change_password" : "login",username:form.get("username"),password:form.get("password")})});
      const result=await response.json() as {error?:string};
      if(!response.ok) throw new Error(result.error || "Could not sign in");
      await refresh();
    } catch(error) { setError(error instanceof Error ? error.message : "Could not sign in"); } finally {setBusy(false);}
  }
  if(user.username && !user.mustChangePassword) return <Panel title={`Welcome, ${user.name}`}><p>You are signed in. Open {user.role==="qc" ? "Quality control" : "Production orders"} from the menu to start.</p><button className="button secondary" onClick={async()=>{await fetch("/api/auth/logout",{method:"POST"});(window.top ?? window).location.assign("/");}}>Sign out</button></Panel>;
  return <div className="team-login"><Panel title={user.mustChangePassword ? "Choose your own password" : "Team sign in"} description={user.mustChangePassword ? "Replace your temporary password before editing." : "Use your HBA team username and password."}><form className="modal-form" onSubmit={submit}>
    {!user.mustChangePassword && <label>Username<input name="username" autoComplete="username" placeholder={fixtureText("loginPlaceholder")} required /></label>}
    <label>{user.mustChangePassword ? "New password" : "Password"}<input name="password" type="password" minLength={user.mustChangePassword ? 12 : 1} maxLength={200} autoComplete={user.mustChangePassword ? "new-password" : "current-password"} required /></label>
    {user.mustChangePassword && <label>Confirm new password<input name="confirm" type="password" autoComplete="new-password" required /></label>}
    {error && <p role="alert" className="danger-text">{error}</p>}
    <button className="button primary" disabled={busy}>{busy ? "Please wait…" : user.mustChangePassword ? "Save password" : "Sign in"}</button>
  </form></Panel></div>;
}

function CheckRow({check, label, canEdit, save}: {check:QcCheck;label:string;canEdit:boolean;save:(check:QcCheck)=>Promise<void>}) {
  const [result,setResult]=useState(check.result);
  const [notes,setNotes]=useState(check.notes);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  return <div className="qc-check-row"><div><strong>{label}</strong>{check.updatedAt && <small>Saved by {check.checkedBy} · {check.updatedAt} UTC</small>}</div><select aria-label={`${label}: result`} value={result} disabled={!canEdit||busy} onChange={event=>setResult(event.target.value as QcCheck["result"])}>{["Pending","Pass","Fail","N/A"].map(value=><option key={value}>{value}</option>)}</select><textarea aria-label={`${label}: notes`} rows={2} value={notes} maxLength={1000} disabled={!canEdit||busy} onChange={event=>setNotes(event.target.value)} placeholder="Measurements, defects or corrective action" />{canEdit && <button className="button secondary" disabled={busy || (result===check.result && notes===check.notes)} onClick={async()=>{setBusy(true);setError("");try{await save({...check,result,notes});}catch(error){setError(error instanceof Error ? error.message : "Could not save");}finally{setBusy(false);}}}>{busy ? "Saving…" : "Save check"}</button>}{error && <p role="alert" className="danger-text">{error}</p>}</div>;
}

export function OrderQcPage({orders,checks,user,refresh}: {orders:ProductionOrder[];checks:QcCheck[];user:TeamUser;refresh:()=>Promise<void>}) {
  const [selected,setSelected]=useState("");
  const order=orders.find(order=>order.code===selected || order.legacyCode===selected) ?? orders[0];
  const code=order?.code || "";
  const canEdit=user.role==="qc" || user.role==="admin";
  async function save(check:QcCheck) {
    const response=await fetch("/api/production/actions",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({action:"qc_check",recordId:code,payload:check})});
    const result=await response.json() as {error?:string};if(!response.ok) throw new Error(result.error || "Could not save check");await refresh();
  }
  return <div className="page-stack"><PageHeader eyebrow={`${fixtureText("qcInspectorName")} · Quality control`} title="Production order QC" description="Record each check at every production step. Failed checks remain visible until corrected." />
    <Panel title="Select production order"><select className="qc-order-select" aria-label="Production order" value={code} onChange={event=>setSelected(event.target.value)}>{orders.map(order=><option key={order.code} value={order.code}>{order.code} · {order.product} · {order.supplier}</option>)}</select>{order && <p>{order.quantity} units · {order.color} · {order.status}</p>}{!canEdit && <p>Sign in with the QC account to record checks.</p>}</Panel>
    {!order ? <p>No production orders available.</p> : qcSteps.map(step=>{
      const records=step.checks.map((_,item)=>checks.find(check=>check.orderCode===code&&check.step===step.id&&check.item===item));
      const complete=records.filter(check=>check && ["Pass","N/A"].includes(check.result)).length;
      const failed=records.some(check=>check?.result==="Fail");
      return <Panel key={`${code}-${step.id}`} title={step.name} action={<Badge tone={failed ? "red" : complete===step.checks.length ? "green" : "yellow"}>{failed ? "Needs correction" : `${complete}/${step.checks.length} cleared`}</Badge>}><ProgressBar value={complete/step.checks.length*100} tone={failed?"red":"green"}/>{step.checks.map((label,item)=>{const check=records[item] ?? {orderCode:code,step:step.id,item,result:"Pending",notes:"",checkedBy:"",updatedAt:""};return <CheckRow key={`${item}-${check.updatedAt}-${check.result}-${check.notes}`} check={check} label={label} canEdit={canEdit} save={save}/>;})}</Panel>;
    })}
  </div>;
}
