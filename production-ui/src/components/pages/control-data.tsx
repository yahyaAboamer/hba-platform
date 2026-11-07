"use client";

import { Fragment, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, ClipboardList, Clock3, ImagePlus, Pencil, Plus, Search, Shirt, Trash2, UserRoundCheck, X } from "lucide-react";
import { RecordPhotos } from '@/components/record-photos';
import { productionProblems, type ProductionTask, type SampleRecord } from "@/lib/demo-data";
import { Badge, Panel, PageHeader, ProgressBar, StatCard, TableWrap } from "@/components/ui";
import { fixtureText } from "@/lib/fixtures";

type Notify = (message: string, tone?: "success" | "warning" | "info") => void;

const startOfToday = () => {
  const value = new Date();
  value.setHours(0, 0, 0, 0);
  return value.getTime();
};
const isOverdue = (date: string) => Date.parse(date) < startOfToday();
const isDueToday = (date: string) => {
  const parsed = Date.parse(date);
  const today = startOfToday();
  return parsed >= today && parsed < today + 86400000;
};
const toDateInput = (date: string) => {
  const parsed = Date.parse(date);
  return Number.isNaN(parsed) ? "" : new Date(parsed).toISOString().slice(0, 10);
};
const taskMonthKey = (date: string) => {
  const parsed = Date.parse(date);
  if (Number.isNaN(parsed)) return "";
  const value = new Date(parsed);
  return `${value.getUTCFullYear()}-${String(value.getUTCMonth() + 1).padStart(2, "0")}`;
};
const taskMonthLabel = (month: string) => {
  const parsed = new Date(`${month}-01T00:00:00Z`);
  return parsed.toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });
};

export function ProductionTasksPage({ notify, tasks, actorName, onSharedChange, canManage }: { notify: Notify; tasks: ProductionTask[]; actorName: string; canManage: boolean; onSharedChange: () => Promise<void> }) {
  const [search, setSearch] = useState("");
  const [priority, setPriority] = useState("All priorities");
  const [supplier, setSupplier] = useState("All suppliers");
  const [schedule, setSchedule] = useState("All schedules");
  const [month, setMonth] = useState("All months");
  const [section, setSection] = useState<"Active" | "Confirmed">("Active");
  const activeTasks=tasks.filter(task=>!task.confirmed);
  const confirmedTasks=tasks.filter(task=>task.confirmed);
  const [addingTask, setAddingTask] = useState(false);
  const [editingTask, setEditingTask] = useState<ProductionTask | null>(null);
  const [deletingTask, setDeletingTask] = useState<ProductionTask | null>(null);
  const [saving, setSaving] = useState(false);
  const suppliers = useMemo(() => Array.from(new Set(tasks.map((task) => task.supplier))).sort(), [tasks]);
  const months = useMemo(() => Array.from(new Set(tasks.map((task) => taskMonthKey(task.actionDate)).filter(Boolean))).sort().reverse(), [tasks]);
  const filtersActive = Boolean(search || priority !== "All priorities" || supplier !== "All suppliers" || schedule !== "All schedules" || month !== "All months");

  const rows = useMemo(() => tasks.filter((task) => {
    const matchesSearch = `${task.name} ${task.id} ${task.supplier} ${task.nextAction}`.toLowerCase().includes(search.toLowerCase());
    const matchesPriority = priority === "All priorities" || task.priority === priority;
    const matchesSupplier = supplier === "All suppliers" || task.supplier === supplier;
    const matchesMonth = month === "All months" || taskMonthKey(task.actionDate) === month;
    const matchesSchedule = schedule === "All schedules"
      || (schedule === "Overdue" && isOverdue(task.deadline))
      || (schedule === "Due today" && isDueToday(task.deadline))
      || (schedule === "Upcoming" && Date.parse(task.deadline) >= startOfToday() + 86400000);
    return Boolean(task.confirmed) === (section === "Confirmed") && matchesSearch && matchesPriority && matchesSupplier && matchesMonth && matchesSchedule;
  }), [month, priority, schedule, search, supplier, tasks, section]);

  const clearFilters = () => {
    setSearch("");
    setPriority("All priorities");
    setSupplier("All suppliers");
    setSchedule("All schedules");
    setMonth("All months");
  };

  const confirmTask = async (task: ProductionTask) => {
    setSaving(true);
    try {
      const response=await fetch("/api/production/actions", {method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({action:task.confirmed ? "reopen_task" : "confirm_task",recordId:task.id})});
      const result=await response.json() as {error?:string};
      if(!response.ok) throw new Error(result.error || "Could not confirm task");
      await onSharedChange();
      setEditingTask(null);setDeletingTask(null);
      notify(task.confirmed ? "Task moved to Active tasks" : "Task moved to Confirmed", "success");
    } catch(error) {notify(error instanceof Error ? error.message : "Could not update task", "warning");}
    finally {setSaving(false);}
  };

  const saveTask = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editingTask) return;
    setSaving(true);
    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch("/api/production/actions", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ action: "update_task", recordId: editingTask.id, actorName, payload: Object.fromEntries(form.entries()) }),
      });
      const result = await response.json() as { error?: string };
      if (!response.ok) throw new Error(result.error || "Could not update the task");
      await onSharedChange();
      setEditingTask(null);
      notify(`${editingTask.id} updated for everyone`, "success");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not update the task", "warning");
    } finally {
      setSaving(false);
    }
  };

  const deleteTask = async () => {
    if (!deletingTask) return;
    setSaving(true);
    try {
      const response = await fetch("/api/production/actions", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ action: "delete_task", recordId: deletingTask.id, actorName }),
      });
      const result = await response.json() as { error?: string };
      if (!response.ok) throw new Error(result.error || "Could not delete the task");
      await onSharedChange();
      notify(`${deletingTask.id} deleted for everyone`, "success");
      setDeletingTask(null);
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not delete the task", "warning");
    } finally {
      setSaving(false);
    }
  };

  return <div className="page-stack">
    {addingTask && <NewControlRecord kind="task" suppliers={suppliers} owner={actorName} notify={notify} onSharedChange={onSharedChange} onClose={()=>setAddingTask(false)} />}
    <PageHeader eyebrow="Production control" title="Production tasks" description="Current work and completed task history." actions={<button className="button primary" disabled={!canManage} title={!canManage ? "Sign in with an owner or production account" : undefined} onClick={()=>setAddingTask(true)}><Plus size={16}/> Add task</button>} />
    <div className="stats-grid stats-grid-four">
      <StatCard label="Active tasks" value={String(activeTasks.length)} detail="Assigned production work" icon={<ClipboardList size={17} />} />
      <StatCard label="Overdue" value={String(activeTasks.filter((task) => isOverdue(task.deadline)).length)} detail="Needs a new committed date" icon={<Clock3 size={17} />} emphasis="yellow" />
      <StatCard label="Critical" value={String(activeTasks.filter((task) => task.priority === "Critical").length)} detail="Immediate management focus" icon={<AlertTriangle size={17} />} emphasis="red" />
      <StatCard label="Confirmed" value={String(confirmedTasks.length)} detail="Confirmed task history" icon={<CheckCircle2 size={17} />} emphasis="green" />
    </div>
    <div className="segmented task-sections" role="tablist" aria-label="Task sections">{(["Active","Confirmed"] as const).map(value=><button key={value} role="tab" aria-selected={section===value} className={section===value ? "active" : ""} disabled={saving} onClick={()=>{setSection(value);clearFilters();setEditingTask(null);setDeletingTask(null);}}>{value === "Active" ? "Active tasks" : "Confirmed"} ({value === "Active" ? activeTasks.length : confirmedTasks.length})</button>)}</div>
    {!canManage && <p>Sign in with the owner or production account to edit, delete or confirm tasks.</p>}
    <Panel className="table-panel">
      <div className="table-toolbar">
        <div className="search-field"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search tasks, supplier or next action" /></div>
        <select value={priority} onChange={(event) => setPriority(event.target.value)} aria-label="Filter by priority"><option>All priorities</option><option>Critical</option><option>High</option><option>Normal</option><option>Low</option></select>
        <select value={supplier} onChange={(event) => setSupplier(event.target.value)} aria-label="Filter by supplier"><option>All suppliers</option>{suppliers.map((item) => <option key={item}>{item}</option>)}</select>
        <select value={month} onChange={(event) => setMonth(event.target.value)} aria-label="Filter tasks by month"><option>All months</option>{months.map((item) => <option key={item} value={item}>{taskMonthLabel(item)}</option>)}</select>
        <select value={schedule} onChange={(event) => setSchedule(event.target.value)} aria-label="Filter by schedule"><option>All schedules</option><option>Overdue</option><option>Due today</option><option>Upcoming</option></select>
        {filtersActive && <button className="button subtle filter-clear" onClick={clearFilters}><X size={14} /> Clear</button>}
        <span className="toolbar-spacer" /><span className="result-count">{rows.length} tasks</span>
      </div>
      <TableWrap><table><thead><tr><th>Task</th><th>Supplier</th><th>Stage</th><th>Next action</th><th>Owner</th><th>Deadline</th><th>Progress</th><th aria-label="Actions" /></tr></thead><tbody>{rows.map((task) => <Fragment key={task.id}><tr className="clickable-row" onClick={() => notify(`${task.id}: ${task.nextAction}`, "info")}><td><strong>{task.name}</strong><small className="mono-cell">{task.id} · {task.priority}</small></td><td><strong>{task.supplier}</strong><small>{task.supplierType}</small></td><td><Badge tone="grey">{task.stage}</Badge></td><td><strong>{task.nextAction}</strong><small>Action set {task.actionDate}</small></td><td>{task.owner}</td><td>{task.deadline}<small className={!task.confirmed && isOverdue(task.deadline) ? "danger-text" : "muted-text"}>{task.confirmed ? "Completed" : task.deadline === "—" ? "Date not set" : isOverdue(task.deadline) ? "Overdue" : isDueToday(task.deadline) ? "Due today" : "On schedule"}</small></td><td className="progress-cell"><div><ProgressBar value={task.progress} tone={task.progress < 25 ? "red" : task.progress < 75 ? "yellow" : "green"} /><span>{task.progress}%</span></div></td><td className="task-visible-actions"><div onClick={event=>event.stopPropagation()}>{canManage ? <><button type="button" className="button secondary" disabled={saving} onClick={()=>{setEditingTask(task);setDeletingTask(null);}}><Pencil size={14}/> Edit</button><button type="button" className="button danger" disabled={saving} onClick={()=>{setDeletingTask(task);setEditingTask(null);}}><Trash2 size={14}/> Delete</button><button type="button" className="button primary" disabled={saving} onClick={()=>void confirmTask(task)}><CheckCircle2 size={14}/> {task.confirmed ? "Reopen" : "Confirm"}</button></> : <Badge tone="grey">View only</Badge>}</div>{task.confirmed && <small>Confirmed by {task.confirmedBy} · {task.confirmedAt} UTC</small>}</td></tr>
        {editingTask?.id === task.id && <tr className="task-inline-row"><td colSpan={8}><form className="task-inline-editor" onSubmit={saveTask}><div className="task-inline-heading"><span><Pencil size={17} /></span><div><strong>Edit {editingTask.id}</strong><small>Change the task here without leaving this page.</small></div><button className="icon-button" type="button" onClick={() => setEditingTask(null)} aria-label="Close inline task editor" disabled={saving}><X size={17} /></button></div><div className="task-inline-grid"><label>Task name<input name="name" defaultValue={editingTask.name} required /></label><label>Supplier<input name="supplier" defaultValue={editingTask.supplier} required /></label><label>Supplier type<input name="supplierType" defaultValue={editingTask.supplierType} required /></label><label>Stage<input name="stage" defaultValue={editingTask.stage} required /></label><label>Owner<input name="owner" defaultValue={editingTask.owner} required /></label><label>Priority<select name="priority" defaultValue={editingTask.priority}><option>Critical</option><option>High</option><option>Normal</option><option>Low</option></select></label><label>Action date<input name="actionDate" type="date" defaultValue={toDateInput(editingTask.actionDate)} required /></label><label>Deadline<input name="deadline" type="date" defaultValue={toDateInput(editingTask.deadline)} /></label><label>Progress %<input name="progress" type="number" min="0" max="100" step="1" defaultValue={editingTask.progress} required /></label></div><label className="task-inline-notes">Next action<textarea name="nextAction" rows={3} defaultValue={editingTask.nextAction} required /></label><footer><button className="button subtle" type="button" onClick={() => setEditingTask(null)} disabled={saving}>Cancel</button><button className="button primary" type="submit" disabled={saving}>{saving ? "Saving…" : "Save changes"}</button></footer></form></td></tr>}
        {deletingTask?.id === task.id && <tr className="task-inline-row"><td colSpan={8}><div className="task-inline-delete" role="alert"><span><Trash2 size={19} /></span><div><strong>Delete {deletingTask.id}?</strong><small>“{deletingTask.name}” will be removed for everyone and recorded in Team changes.</small></div><button className="button subtle" onClick={() => setDeletingTask(null)} disabled={saving}>Cancel</button><button className="button danger" onClick={() => void deleteTask()} disabled={saving}><Trash2 size={15} /> {saving ? "Deleting…" : "Delete"}</button></div></td></tr>}
      </Fragment>)}{rows.length===0 && <tr><td colSpan={8} className="empty-task-section">{filtersActive ? "No tasks match your filters." : section==="Confirmed" ? "No confirmed tasks yet. Confirm a task from Active tasks to move it here." : "No active tasks."}</td></tr>}</tbody></table></TableWrap>
    </Panel>
  </div>;
}

export function SamplesPage({ canManage, notify, samples: sampleRecords, onSharedChange }: { canManage: boolean; notify: Notify; samples: SampleRecord[]; onSharedChange: ()=>Promise<void> }) {
  const [photoSample,setPhotoSample]=useState<SampleRecord | null>(null);
  const [addingSample,setAddingSample]=useState(false);
  const [editingSample,setEditingSample]=useState<SampleRecord | null>(null);
  const [section,setSection]=useState<"Active" | "Done">("Active");
  const [saving,setSaving]=useState("");
  async function toggleDone(sample:SampleRecord) {
    setSaving(sample.id);
    try {
      const response=await fetch("/api/production/actions",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({action:"sample_status",recordId:sample.id,payload:{done:!["Done","Approved"].includes(sample.stage)}})});
      const result=await response.json() as {error?:string};if(!response.ok) throw new Error(result.error || "Could not update sample");
      await onSharedChange();notify("Sample status saved", "success");
    } catch(error){notify(error instanceof Error ? error.message : "Could not save", "warning");} finally{setSaving("");}
  }
  const [search, setSearch] = useState("");
  const [stage, setStage] = useState("All stages");
  const rows = useMemo(() => sampleRecords.filter((sample) => (["Done","Approved"].includes(sample.stage) === (section === "Done")) && (stage === "All stages" || sample.stage === stage) && `${sample.name} ${sample.supplier} ${sample.latestProgress} ${sample.nextStep}`.toLowerCase().includes(search.toLowerCase())), [search, stage, sampleRecords, section]);
  const approved = sampleRecords.filter((sample) => ["Approved","Done"].includes(sample.stage)).length;
  const attention = sampleRecords.length - approved;

  return <div className="page-stack">
    {photoSample && <div className="modal-backdrop" onClick={()=>setPhotoSample(null)}><section className="modal sample-photos-modal" role="dialog" aria-modal="true" aria-labelledby="sample-photo-title" onClick={event=>event.stopPropagation()}><header><div><h2 id="sample-photo-title">{photoSample.name}</h2><p>{photoSample.id} · Reference images and sample details</p></div><button className="icon-button" onClick={()=>setPhotoSample(null)} aria-label="Close sample photos"><X size={18}/></button></header><RecordPhotos key={photoSample.id} kind="sample" recordId={photoSample.id} recordName={photoSample.name} canUpload={canManage} onSaved={onSharedChange}/></section></div>}
    {(addingSample || editingSample) && <NewControlRecord kind="sample" sample={editingSample ?? undefined} suppliers={Array.from(new Set(sampleRecords.map(sample=>sample.supplier)))} owner={fixtureText("defaultSampleOwner")} notify={notify} onSharedChange={onSharedChange} onClose={()=>{setAddingSample(false);setEditingSample(null);}} />}
    <PageHeader eyebrow="Pre-production workspace" title="Product samples" description="Samples, supplier ownership, deadlines, and production readiness." actions={<button className="button primary" disabled={!canManage} title={!canManage ? "Sign in with an owner or production account" : undefined} onClick={()=>setAddingSample(true)}><Plus size={16}/> Add sample</button>} />
    <div className="stats-grid stats-grid-four">
      <StatCard label="Total samples" value={String(sampleRecords.length)} detail="Collection and sample history" icon={<Shirt size={17} />} />
      <StatCard label="Done / Approved" value={String(approved)} detail="Completed sample history" icon={<CheckCircle2 size={17} />} emphasis="green" />
      <StatCard label="Needs attention" value={String(attention)} detail="Still in progress" icon={<AlertTriangle size={17} />} emphasis="yellow" />
      <StatCard label="Overdue" value={String(sampleRecords.filter((sample) => !["Done","Approved"].includes(sample.stage) && isOverdue(sample.deadline)).length)} detail="Active samples past deadline" icon={<Clock3 size={17} />} emphasis="red" />
    </div>
    <div className="segmented task-sections" role="tablist" aria-label="Sample sections">{(["Active","Done"] as const).map(value=><button key={value} role="tab" aria-selected={section===value} className={section===value ? "active" : ""} onClick={()=>{setSection(value);setStage("All stages");}}>{value === "Active" ? "Active samples" : "Done / Approved"} ({value === "Active" ? attention : approved})</button>)}</div>
    {!canManage && <p>Sign in with the owner or production account to add or update samples.</p>}
    <Panel className="table-panel">
      <div className="table-toolbar"><div className="search-field"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search sample, supplier or action" /></div><select value={stage} onChange={(event) => setStage(event.target.value)}><option>All stages</option><option>Done</option><option>Approved</option><option>In Progress</option><option>Revision Requested</option><option>On Hold</option><option>Rejected</option></select><span className="toolbar-spacer" /><span className="result-count">{rows.length} samples</span></div>
      <TableWrap><table><thead><tr><th>Sample</th><th>Supplier</th><th>Stage</th><th>Latest progress</th><th>Next step</th><th>Deadline</th><th>Progress</th><th>Production</th><th>Actions</th></tr></thead><tbody>{rows.map((sample) => <tr key={sample.id} className="clickable-row" onClick={() => notify(`${sample.name}: ${sample.nextStep}`, "info")}><td>{sample.photoUrl && <img className="sample-thumbnail" src={sample.photoUrl} alt={`${sample.name} reference`} loading="lazy"/>}<strong>{sample.name}</strong><small>{sample.id} · {sample.priority}{sample.material ? ` · ${sample.material}` : ""}</small></td><td><strong>{sample.supplier}</strong><small>Owner: {sample.owner}</small></td><td><Badge tone={["Approved","Done"].includes(sample.stage) ? "green" : "yellow"}>{sample.stage}</Badge></td><td><strong>{sample.latestProgress}</strong><small>Updated {sample.updatedAt} · {sample.updates} updates</small></td><td>{sample.nextStep}</td><td>{sample.deadline}<small className={!["Done","Approved"].includes(sample.stage) && isOverdue(sample.deadline) ? "danger-text" : "muted-text"}>{["Done","Approved"].includes(sample.stage) ? "Completed" : sample.deadline === "—" ? "Date not set" : isOverdue(sample.deadline) ? "Overdue" : "On schedule"}</small></td><td className="progress-cell"><div><ProgressBar value={sample.progress} tone={["Approved","Done"].includes(sample.stage) ? "green" : sample.priority === "Critical" || sample.priority === "Urgent" ? "red" : "yellow"} /><span>{sample.progress}%</span></div></td><td>{sample.manufacturingNotes?.includes("Production completed") ? <Badge tone="green">Completed</Badge> : sample.manufacturingNotes?.includes("Production not started") ? <Badge tone="grey">Not Started</Badge> : sample.manufacturingNotes?.includes("Production in progress") ? <Badge tone="yellow">In Progress</Badge> : "Not recorded"}</td><td><button className="button secondary" onClick={event=>{event.stopPropagation();setPhotoSample(sample);}}><ImagePlus size={14}/> Photos{sample.photoCount ? ` (${sample.photoCount})` : ""}</button>{canManage && <button className="button secondary" onClick={event=>{event.stopPropagation();setEditingSample(sample);}}><Pencil size={14}/> Edit</button>}<button className="button secondary" disabled={!canManage || saving===sample.id} onClick={event=>{event.stopPropagation();void toggleDone(sample);}}>{saving===sample.id ? "Saving…" : ["Done","Approved"].includes(sample.stage) ? "Reopen" : "Mark Done"}</button></td></tr>)}</tbody></table></TableWrap>
    </Panel>
    <Panel title="Approved production references" description="Completed sample records and manufacturing notes"><div className="compact-list">{sampleRecords.filter((sample) => ["Approved","Done"].includes(sample.stage)).map((sample) => <button key={sample.id} onClick={() => notify(sample.manufacturingNotes || "No manufacturing notes recorded", "info")}><span><strong>{sample.name}</strong><small>{sample.manufacturingNotes || "No manufacturing notes recorded"}</small></span><span className="list-value"><Badge tone="green">{sample.stage}</Badge><small>{sample.approvedBy || "Approval not recorded"} · {sample.approvalDate || "Date not recorded"}</small></span></button>)}</div></Panel>
  </div>;
}

function NewControlRecord({kind, sample, suppliers, owner, notify, onSharedChange, onClose}: {kind:"task" | "sample"; sample?:SampleRecord; suppliers:string[]; owner:string; notify:Notify; onSharedChange:()=>Promise<void>; onClose:()=>void}) {
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  async function submit(event:React.FormEvent<HTMLFormElement>) {
    event.preventDefault();setSaving(true);setError("");
    const form = new FormData(event.currentTarget);
    try {
      const response=await fetch("/api/production/actions",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({action:kind === "task" ? "create_task" : sample ? "update_sample" : "create_sample",recordId:sample?.id,payload:Object.fromEntries(form.entries())})});
      const result=await response.json() as {error?:string};
      if(!response.ok) throw new Error(result.error || "Could not save");
      await onSharedChange();onClose();notify(sample ? "Sample updated for the team" : `${kind === "task" ? "Task" : "Sample"} added for the team`,"success");
    } catch(error) { setError(error instanceof Error ? error.message : "Could not save. Please try again."); }
    finally {setSaving(false);}
  }
  return <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-label={sample ? "Edit sample" : `Add ${kind}`}><header><div><h2>{sample ? "Edit sample" : `Add ${kind}`}</h2><p>Save this record to the shared HBA workspace.</p></div><button className="icon-button" disabled={saving} onClick={onClose} aria-label="Close"><X size={18}/></button></header><form className="modal-form" onSubmit={submit}>
    <div className="form-grid">
      <label>{kind === "task" ? "Task name" : "Sample / version name"}<input autoFocus name="name" required maxLength={180} defaultValue={sample?.name} /></label>
      <label>Supplier<input name="supplier" list="control-suppliers" defaultValue={sample?.supplier ?? "Unassigned"}/><datalist id="control-suppliers">{suppliers.map(name=><option key={name} value={name}/>)}</datalist></label>
      <label>Owner<input name="owner" required defaultValue={sample?.owner ?? owner}/></label>
      <label>Priority<select name="priority" defaultValue={sample?.priority ?? "Normal"}><option>Critical</option>{kind === "sample" && <option>Urgent</option>}<option>High</option><option>Normal</option><option>Low</option></select></label>
      <label>Stage<select name="stage" defaultValue={sample?.stage ?? (kind === "task" ? "Preparation" : "In Progress")}>{(kind === "task" ? ["Preparation","Sample","Production","Quality Control","Delivery"] : ["In Progress","Done","Approved","Revision Requested","On Hold","Rejected"]).map(stage=><option key={stage}>{stage}</option>)}</select></label>
      <label>Deadline (optional)<input name="deadline" type="date" defaultValue={sample ? toDateInput(sample.deadline) : ""}/></label>
      {kind === "task" ? <><label>Supplier type<input name="supplierType" defaultValue="Sampling"/></label><label>Action date<input name="actionDate" type="date" required defaultValue={new Date().toISOString().slice(0,10)}/></label></> : <><label>Material / color<input name="material" defaultValue={sample?.material}/></label><label>Progress %<input name="progress" type="number" min="0" max="100" defaultValue={sample?.progress ?? 0}/></label></>}
    </div>
    {kind === "sample" && <label>Latest progress<textarea name="latestProgress" rows={2} defaultValue={sample?.latestProgress}/></label>}
    <label>Next {kind === "task" ? "action" : "step"}<textarea required name={kind === "task" ? "nextAction" : "nextStep"} rows={2} defaultValue={sample?.nextStep}/></label>
    {kind === "sample" && <label>Production / manufacturing notes<textarea name="manufacturingNotes" rows={2} defaultValue={sample?.manufacturingNotes ?? "Production not started"}/></label>}
    {error && <p role="alert" className="danger-text">{error}</p>}
    <footer><button type="button" className="button subtle" onClick={onClose} disabled={saving}>Cancel</button><button className="button primary" type="submit" disabled={saving}>{saving ? "Saving…" : sample ? "Save sample" : `Add ${kind}`}</button></footer>
  </form></section></div>;
}

export function ProblemsPage({ notify }: { notify: Notify }) {
  return <div className="page-stack">
    <PageHeader eyebrow="Urgent production control" title="Problems control room" description="Open blockers, immediate controls, owners, solutions and committed action dates." />
    <div className="stats-grid stats-grid-four"><StatCard label="Open problems" value={String(productionProblems.filter((problem) => problem.status !== "Resolved").length)} detail="Needs control" icon={<AlertTriangle size={17} />} emphasis="red" /><StatCard label="High severity" value={String(productionProblems.filter((problem) => problem.severity === "High" || problem.severity === "Critical").length)} detail="Escalate now" icon={<Clock3 size={17} />} emphasis="yellow" /><StatCard label="Suppliers involved" value={String(new Set(productionProblems.map((problem) => problem.supplier)).size)} detail="Current issue ownership" icon={<UserRoundCheck size={17} />} /><StatCard label="Resolved" value={String(productionProblems.filter((problem) => problem.status === "Resolved").length)} detail="Closed history" icon={<CheckCircle2 size={17} />} emphasis="green" /></div>
    {productionProblems.map((problem) => <Panel key={problem.id} title={problem.name} description={`${problem.category} · ${problem.supplier}`} action={<Badge tone="red">{problem.severity}</Badge>}><div className="detail-grid"><div className="note-box"><strong>Problem</strong><p>{problem.description}</p></div><div className="note-box"><strong>Immediate control</strong><p>{problem.immediateControl}</p></div></div><div className="definition-grid"><div><span>Owner</span><strong>{problem.owner}</strong></div><div><span>Next review</span><strong>{problem.nextReview}</strong></div><div><span>Due date</span><strong>{problem.dueDate}</strong></div><div><span>Status</span><strong>{problem.status}</strong></div></div><div className="note-box"><strong>Possible solutions</strong><p>{problem.solutions.map((solution, index) => `${index + 1}. ${solution}`).join("  ")}</p></div><button className="button secondary" onClick={() => notify(`${problem.id} is assigned to ${problem.owner}`, "info")}>Review problem</button></Panel>)}
  </div>;
}
