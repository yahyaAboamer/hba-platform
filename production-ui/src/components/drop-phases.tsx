"use client";
import { useState } from 'react';
import { Pencil, Plus, Trash2, X } from 'lucide-react';
import { Panel } from '@/components/ui';
import { ConfirmDelete, RowMenu } from '@/components/row-menu';
import type { DropPhase, ProductionOrder } from '@/lib/demo-data';
type Notify=(message:string,tone?:'success'|'warning'|'info')=>void;

async function act(body:Record<string,unknown>,fallback:string) {
  const response=await fetch('/api/production/actions',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});
  const result=await response.json() as {error?:string;recordId:string};
  if(!response.ok) throw new Error(result.error || fallback);
  return result;
}

export function DropPhasePanel({phases,orders,canManage,selected,onSelect,notify,refresh}:{phases:DropPhase[];orders:ProductionOrder[];canManage:boolean;selected:string;onSelect:(id:string)=>void;notify:Notify;refresh:()=>Promise<void>}) {
  const [adding,setAdding]=useState(false);
  const [renaming,setRenaming]=useState<DropPhase|null>(null);
  const [deleting,setDeleting]=useState<DropPhase|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  async function submit(event:React.FormEvent<HTMLFormElement>) {
    event.preventDefault();setBusy(true);setError('');
    const name=new FormData(event.currentTarget).get('name');
    try {
      if(renaming) {
        await act({action:'rename_phase',recordId:renaming.id,payload:{name}},'Could not rename phase');
        await refresh();setRenaming(null);notify('Drop phase renamed','success');
      } else {
        const result=await act({action:'create_phase',payload:{name}},'Could not add phase');
        await refresh();setAdding(false);onSelect(result.recordId);notify('Drop phase saved','success');
      }
    } catch(error) {setError(error instanceof Error ? error.message : 'Could not save phase');} finally {setBusy(false);}
  }
  async function remove() {
    if(!deleting) return;
    setBusy(true);setError('');
    try {
      await act({action:'delete_phase',recordId:deleting.id},'Could not delete phase');
      if(selected===deleting.id) onSelect('all');
      await refresh();notify(`${deleting.name} deleted`,'success');setDeleting(null);
    } catch(error) {setError(error instanceof Error ? error.message : 'Could not delete phase');} finally {setBusy(false);}
  }
  const closeForm=()=>{setAdding(false);setRenaming(null);};
  const deletingCount=deleting ? orders.filter(order=>order.phaseId===deleting.id).length : 0;
  return <>
    <Panel title="Drop phases" action={<button className="button secondary" disabled={!canManage} title={!canManage ? 'Sign in to add phases' : undefined} onClick={()=>{setError('');setRenaming(null);setAdding(true);}}><Plus size={16}/> Add phase</button>}>
      <div className="drop-phase-grid">{phases.map(phase=>{
        const items=orders.filter(order=>order.phaseId===phase.id);
        return <div key={phase.id} className="drop-phase-item"><button type="button" className={`drop-phase-card ${selected===phase.id ? 'selected' : ''}`} aria-pressed={selected===phase.id} onClick={()=>onSelect(selected===phase.id ? 'all' : phase.id)}><strong>{phase.name}</strong><span>{items.length} {items.length===1 ? 'order' : 'orders'}</span><small>{items.filter(order=>order.status==='In Progress').length} in progress</small></button>
          {canManage && <RowMenu className="drop-phase-menu" label={`Actions for ${phase.name}`} items={[
            {label:'Rename',icon:<Pencil size={15}/>,onSelect:()=>{setError('');setAdding(false);setRenaming(phase);}},
            {label:'Delete',icon:<Trash2 size={15}/>,danger:true,onSelect:()=>{setError('');setDeleting(phase);}},
          ]}/>}
        </div>;
      })}</div>
    </Panel>
    {(adding || renaming) && <div className="modal-backdrop"><section className="modal phase-modal" role="dialog" aria-modal="true" aria-labelledby="phase-dialog-title"><header><div><h2 id="phase-dialog-title">{renaming ? `Rename ${renaming.name}` : 'Add drop phase'}</h2><p>{renaming ? 'Its orders stay in this phase under the new name.' : 'Create a phase, then assign production orders to it.'}</p></div><button className="icon-button" onClick={closeForm} disabled={busy} aria-label={renaming ? 'Close rename phase' : 'Close add phase'}><X size={18}/></button></header><form className="modal-form" onSubmit={submit}><label>Phase name<input autoFocus name="name" required maxLength={80} defaultValue={renaming?.name ?? ''} placeholder="e.g. Phase Three Drop"/></label>{error && <p role="alert" className="danger-text">{error}</p>}<footer><button className="button subtle" type="button" disabled={busy} onClick={closeForm}>Cancel</button><button className="button primary" disabled={busy}>{busy ? 'Saving…' : renaming ? 'Save name' : 'Add phase'}</button></footer></form></section></div>}
    {deleting && <ConfirmDelete title={`Delete ${deleting.name}?`} busy={busy} error={error} confirmLabel="Delete phase" onCancel={()=>{setDeleting(null);setError('');}} onConfirm={()=>void remove()}
      detail={deletingCount ? `Its ${deletingCount} ${deletingCount===1 ? 'order moves' : 'orders move'} to Unassigned. No orders are deleted.` : 'This phase has no orders. No orders are affected.'}/>}
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
