"use client";
import { useState } from 'react';
import { Plus, X } from 'lucide-react';
import { Panel } from '@/components/ui';
import type { DropPhase, ProductionOrder } from '@/lib/demo-data';
type Notify=(message:string,tone?:'success'|'warning'|'info')=>void;

export function DropPhasePanel({phases,orders,canManage,selected,onSelect,notify,refresh}:{phases:DropPhase[];orders:ProductionOrder[];canManage:boolean;selected:string;onSelect:(id:string)=>void;notify:Notify;refresh:()=>Promise<void>}) {
  const [adding,setAdding]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  async function submit(event:React.FormEvent<HTMLFormElement>) {
    event.preventDefault();setBusy(true);setError('');
    const name=new FormData(event.currentTarget).get('name');
    try {
      const response=await fetch('/api/production/actions',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({action:'create_phase',payload:{name}})});
      const result=await response.json() as {error?:string;recordId:string};
      if(!response.ok) throw new Error(result.error || 'Could not add phase');
      await refresh();setAdding(false);onSelect(result.recordId);notify('Drop phase saved','success');
    } catch(error) {setError(error instanceof Error ? error.message : 'Could not add phase');} finally {setBusy(false);}
  }
  return <>
    <Panel title="Drop phases" action={<button className="button secondary" disabled={!canManage} title={!canManage ? 'Sign in to add phases' : undefined} onClick={()=>{setError('');setAdding(true);}}><Plus size={16}/> Add phase</button>}>
      <div className="drop-phase-grid">{phases.map(phase=>{
        const items=orders.filter(order=>order.phaseId===phase.id);
        return <button type="button" key={phase.id} className={`drop-phase-card ${selected===phase.id ? 'selected' : ''}`} aria-pressed={selected===phase.id} onClick={()=>onSelect(selected===phase.id ? 'all' : phase.id)}><strong>{phase.name}</strong><span>{items.length} {items.length===1 ? 'order' : 'orders'}</span><small>{items.filter(order=>order.status==='In Progress').length} in progress</small></button>;
      })}</div>
    </Panel>
    {adding && <div className="modal-backdrop"><section className="modal phase-modal" role="dialog" aria-modal="true" aria-labelledby="phase-dialog-title"><header><div><h2 id="phase-dialog-title">Add drop phase</h2><p>Create a phase, then assign production orders to it.</p></div><button className="icon-button" onClick={()=>setAdding(false)} disabled={busy} aria-label="Close add phase"><X size={18}/></button></header><form className="modal-form" onSubmit={submit}><label>Phase name<input autoFocus name="name" required maxLength={80} placeholder="e.g. Phase Three Drop"/></label>{error && <p role="alert" className="danger-text">{error}</p>}<footer><button className="button subtle" type="button" disabled={busy} onClick={()=>setAdding(false)}>Cancel</button><button className="button primary" disabled={busy}>{busy ? 'Saving…' : 'Add phase'}</button></footer></form></section></div>}
  </>;
}
export function OrderPhasePicker({order,phases,canManage,notify,refresh}:{order:ProductionOrder;phases:DropPhase[];canManage:boolean;notify:Notify;refresh:()=>Promise<void>}) {
  const [busy,setBusy]=useState(false);
  async function assign(phaseId:string) {
    setBusy(true);
    try {
      const response=await fetch('/api/production/actions',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({action:'assign_phase',recordId:order.code,payload:{phaseId}})});
      const result=await response.json() as {error?:string};
      if(!response.ok) throw new Error(result.error || 'Could not assign phase');
      await refresh();notify('Order phase saved','success');
    } catch(error) {notify(error instanceof Error ? error.message : 'Could not save phase','warning');} finally {setBusy(false);}
  }
  return canManage ? <select className="order-phase-select" aria-label={`Drop phase for ${order.code}`} value={order.phaseId || ''} disabled={busy} onClick={event=>event.stopPropagation()} onChange={event=>void assign(event.target.value)}><option value="">Unassigned</option>{phases.map(phase=><option key={phase.id} value={phase.id}>{phase.name}</option>)}</select> : <span>{order.phaseName || 'Unassigned'}</span>;
}
