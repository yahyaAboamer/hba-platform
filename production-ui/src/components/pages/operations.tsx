"use client";

import { useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  AlertTriangle,
  Archive,
  Bell,
  Check,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  Clock3,
  Download,
  FileImage,
  FileText,
  Filter,
  FolderOpen,
  LockKeyhole,
  PackageCheck,
  Plus,
  ReceiptText,
  Search,
  Send,
  Settings2,
  Shield,
  ShieldAlert,
  SlidersHorizontal,
  Truck,
  Upload,
  WalletCards,
  XCircle,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  activityLog,
  chartProductionByWeek,
  costLines,
  documents,
  notifications as initialNotifications,
  payments as initialPayments,
  productionOrders,
  productionProblems,
  productionTasks,
  qcInspections,
  sampleRecords,
  suppliers,
} from "@/lib/demo-data";
import { calculateActualUnitCost, formatCurrency } from "@/lib/business-logic";
import { Badge, Metric, Panel, PageHeader, ProgressBar, StatCard, TableWrap } from "@/components/ui";
import { fixtureText } from "@/lib/fixtures";

type Notify = (message: string, tone?: "success" | "warning" | "info") => void;
type Navigate = (path: string) => void;

export function QualityControlPage({ notify }: { notify: Notify }) {
  const [filter, setFilter] = useState("All results");
  const rows = filter === "All results" ? qcInspections : qcInspections.filter((item) => item.result === filter);
  const inspected = qcInspections.reduce((sum, item) => sum + item.inspected, 0);
  const accepted = qcInspections.reduce((sum, item) => sum + item.accepted, 0);
  const rejected = qcInspections.reduce((sum, item) => sum + item.rejected, 0);
  return <div className="page-stack"><PageHeader eyebrow="Quality assurance" title="Quality control" description="Recorded sample and material reviews from the imported HBA data." actions={<button className="button primary" onClick={() => notify("New inspection checklist opened", "info")}><Plus size={16} /> New inspection</button>} /><div className="stats-grid stats-grid-four"><StatCard label="Recorded inspections" value={String(qcInspections.length)} detail="Imported reviews" icon={<ClipboardCheck size={17} />} /><StatCard label="Accepted" value={String(accepted)} detail={`${inspected} inspected`} icon={<CheckCircle2 size={17} />} emphasis="green" /><StatCard label="Rejected" value={String(rejected)} detail="Needs follow-up" icon={<AlertTriangle size={17} />} emphasis="yellow" /><StatCard label="Open material problems" value={String(productionProblems.length)} detail="Compression fabric" icon={<ShieldAlert size={17} />} emphasis="red" /></div><Panel className="table-panel"><div className="table-toolbar"><select value={filter} onChange={(event) => setFilter(event.target.value)}><option>All results</option><option>Pass with Comments</option><option>Review Required</option></select><span className="toolbar-spacer" /><span className="result-count">{rows.length} inspections</span></div><TableWrap><table><thead><tr><th>Inspection</th><th>Sample</th><th>Type</th><th>Supplier</th><th>Inspector</th><th>Inspected</th><th>Rejected</th><th>Defect rate</th><th>Result</th></tr></thead><tbody>{rows.map((inspection) => <tr key={inspection.number} className="clickable-row" onClick={() => notify(`${inspection.number} inspection report opened`, "info")}><td><strong className="mono-cell">{inspection.number}</strong><small>{inspection.date}</small></td><td>{inspection.order}</td><td>{inspection.type}</td><td>{inspection.supplier}</td><td>{inspection.inspector}</td><td>{inspection.inspected}</td><td>{inspection.rejected}</td><td className={inspection.defectRate > 10 ? "danger-text" : ""}>{inspection.defectRate}%</td><td><Badge>{inspection.result}</Badge></td></tr>)}</tbody></table></TableWrap></Panel><div className="detail-grid"><Panel title="Current quality focus"><div className="note-box"><strong>Real Tree sample</strong><p>{fixtureText("qcRealTreeNote")}</p></div></Panel><Panel title="Corrective actions"><div className="task-list"><button onClick={() => notify("Compression material issue opened", "info")}><span><strong>Replace burgundy compression fabric</strong><small>{fixtureText("qcProblemDetail")}</small></span><Badge tone="red">Open</Badge></button><button onClick={() => notify("Real Tree sample opened", "info")}><span><strong>Verify Real Tree approved sample</strong><small>{fixtureText("qcSampleDetail")}</small></span><Badge tone="yellow">Review</Badge></button></div></Panel></div></div>;
}

export function CostingPage({ notify, onExport }: { notify: Notify; onExport: () => void }) {
  const planned = costLines.reduce((sum, line) => sum + line.planned, 0);
  const actual = costLines.reduce((sum, line) => sum + line.actual, 0);
  return <div className="page-stack"><PageHeader eyebrow="Cost control" title="Production costing" description="No old demo costs were retained. Add confirmed supplier costs against the imported orders." actions={<><button className="button secondary" onClick={onExport}><Download size={16} /> Export</button><button className="button primary" onClick={() => notify("New cost line form opened", "info")}><Plus size={16} /> Add cost</button></>} /><div className="cost-hero-grid"><div><span>Planned total</span><strong>{formatCurrency(planned)}</strong><small>No costs entered</small></div><div><span>Actual to date</span><strong>{formatCurrency(actual)}</strong><small>{planned ? Math.round((actual / planned) * 100) : 0}% committed</small></div><div><span>Current variance</span><strong className={actual > planned ? "danger-text" : "success-text"}>{formatCurrency(actual - planned)}</strong><small>against accrued plan</small></div><div><span>Actual accepted unit cost</span><strong>{formatCurrency(calculateActualUnitCost(actual, 906))}</strong><small>906 completed units in tracker</small></div></div><Panel title="Production cost records" description="Add cost lines when supplier prices are confirmed"><TableWrap><table><thead><tr><th>Category</th><th>Supplier</th><th>Planned</th><th>Actual</th><th>Variance</th><th>Status</th><th></th></tr></thead><tbody>{costLines.map((line) => <tr key={line.category}><td><strong>{line.category}</strong></td><td>{line.supplier}</td><td>{formatCurrency(line.planned)}</td><td>{formatCurrency(line.actual)}</td><td className={line.variance > 0 ? "danger-text" : "success-text"}>{line.variance > 0 ? "+" : ""}{formatCurrency(line.variance)}</td><td><Badge>{line.status}</Badge></td><td><button className="icon-button table-icon-button" onClick={() => notify(`${line.category} cost editor opened`, "info")}><ChevronRight size={15} /></button></td></tr>)}</tbody><tfoot><tr><td colSpan={2}>Production total</td><td>{formatCurrency(planned)}</td><td>{formatCurrency(actual)}</td><td className="success-text">{formatCurrency(actual - planned)}</td><td colSpan={2} /></tr></tfoot></table></TableWrap></Panel></div>;
}

export function PaymentsPage({ notify, onExport, actorName, onSharedChange }: { notify: Notify; onExport: () => void; actorName: string; onSharedChange: () => Promise<void> }) {
  const [payments, setPayments] = useState(initialPayments);
  const approve = async (invoice: string) => {
    try {
      const response = await fetch("/api/production/actions", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "approve_payment", actorName, recordId: invoice }) });
      const result = await response.json() as { error?: string };
      if (!response.ok) throw new Error(result.error || "Could not approve payment");
      setPayments((items) => items.map((item) => item.invoice === invoice ? { ...item, status: "Approved", approval: "Approved" } : item));
      await onSharedChange();
      notify(`${invoice} approved and shared with the team`, "success");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not approve payment", "warning");
    }
  };
  const outstanding = payments.reduce((sum, item) => sum + item.amount - item.paid, 0);
  return <div className="page-stack"><PageHeader eyebrow="Supplier finance" title="Payments" description="No old demo invoices were retained. Add real supplier invoices when received." actions={<><button className="button secondary" onClick={onExport}><Download size={16} /> Export</button><button className="button primary" onClick={() => notify("Invoice submission form opened", "info")}><Plus size={16} /> Add invoice</button></>} /><div className="stats-grid stats-grid-four"><StatCard label="Outstanding" value={formatCurrency(outstanding)} detail={`${payments.length} invoices`} icon={<WalletCards size={17} />} /><StatCard label="Due in 7 days" value={formatCurrency(0)} detail="No invoices recorded" icon={<Clock3 size={17} />} emphasis="yellow" /><StatCard label="Awaiting approval" value="0" detail="No pending approvals" icon={<Shield size={17} />} emphasis="blue" /><StatCard label="Paid this month" value={formatCurrency(0)} detail="No payments recorded" icon={<CheckCircle2 size={17} />} emphasis="green" /></div><Panel className="table-panel"><TableWrap><table><thead><tr><th>Invoice</th><th>Supplier</th><th>Production order</th><th>Amount</th><th>Paid</th><th>Remaining</th><th>Due</th><th>Status</th><th>Approval</th></tr></thead><tbody>{payments.map((item) => <tr key={item.invoice}><td><strong className="mono-cell">{item.invoice}</strong></td><td>{item.supplier}</td><td>{item.order}</td><td>{formatCurrency(item.amount)}</td><td>{formatCurrency(item.paid)}</td><td><strong>{formatCurrency(item.amount - item.paid)}</strong></td><td>{item.due}</td><td><Badge>{item.status}</Badge></td><td>{item.approval === "Required" ? <button className="table-action" onClick={() => approve(item.invoice)}>Approve</button> : <Badge tone="green">Approved</Badge>}</td></tr>)}</tbody></table></TableWrap></Panel></div>;
}

export function WarehousePage({ notify, onExport }: { notify: Notify; onExport: () => void }) {
  const [draft, setDraft] = useState(false);
  const completedUnits = productionOrders.filter((order) => order.status === "Completed").reduce((sum, order) => sum + order.quantity, 0);
  const pendingUnits = productionOrders.filter((order) => order.status !== "Completed").reduce((sum, order) => sum + order.quantity, 0);
  return <div className="page-stack">
    <PageHeader eyebrow="Inbound operations" title="Warehouse receiving" description="No demo GRNs were retained. Create a receipt when completed production physically reaches the warehouse." actions={<><button className="button secondary" onClick={onExport}><Download size={16} /> Export</button><button className="button primary" onClick={() => { setDraft(true); notify("Draft GRN created", "success"); }}><Plus size={16} /> New GRN</button></>} />
    <div className="stats-grid stats-grid-four"><StatCard label="Confirmed receipts" value="0 units" detail="No GRNs recorded" icon={<PackageCheck size={17} />} emphasis="green" /><StatCard label="Completed production" value={`${completedUnits} units`} detail="Await warehouse confirmation" icon={<Truck size={17} />} /><StatCard label="Open production" value={`${pendingUnits} units`} detail="In production or waiting" icon={<ClipboardCheck size={17} />} emphasis="yellow" /><StatCard label="Short / damaged" value="0 units" detail="No receipt exceptions recorded" icon={<ShieldAlert size={17} />} emphasis="red" /></div>
    {draft && <Panel className="draft-grn"><div className="draft-grn-head"><span className="warehouse-icon"><ReceiptText size={22} /></span><div><p className="eyebrow">Draft GRN</p><h2>New warehouse receipt</h2><p>Select one of the imported manufacturing orders.</p></div><Badge tone="blue">Draft</Badge></div><div className="grn-fields"><label>Production order<select>{productionOrders.map((order) => <option key={order.code}>{order.code} · {order.product}</option>)}</select></label><label>Warehouse<input defaultValue="HBA Warehouse" /></label><label>Delivery date<input type="date" defaultValue="2026-09-04" /></label><label>Received quantity<input type="number" defaultValue="0" min="0" /></label></div><div className="panel-actions"><button className="button subtle" onClick={() => setDraft(false)}>Discard draft</button><button className="button primary" onClick={() => notify("Draft GRN saved for review.", "success")}>Save draft</button></div></Panel>}
    <Panel title="Goods received notes"><TableWrap><table><thead><tr><th>GRN</th><th>Production order</th><th>Product</th><th>Delivery date</th><th>Expected</th><th>Accepted</th><th>Damaged</th><th>Status</th></tr></thead><tbody><tr><td colSpan={8}><small>No warehouse receipts have been recorded yet.</small></td></tr></tbody></table></TableWrap></Panel>
  </div>;
}

export function ReportsPage({ onExport }: { onExport: () => void }) {
  const [report, setReport] = useState("Production performance");
  const totalUnits = productionOrders.reduce((sum, order) => sum + order.quantity, 0);
  const completedUnits = productionOrders.filter((order) => order.status === "Completed").reduce((sum, order) => sum + order.quantity, 0);
  const pieData = [
    { name: "Completed", value: productionOrders.filter((order) => order.status === "Completed").length, color: "#a8ff60" },
    { name: "In production", value: productionOrders.filter((order) => order.status === "In Progress").length, color: "#f6c85f" },
    { name: "Waiting", value: productionOrders.filter((order) => order.status === "Not Started").length, color: "#69a7ff" },
  ];
  return <div className="page-stack">
    <PageHeader eyebrow="Performance intelligence" title="Reports & KPIs" description="KPIs calculated only from the imported HBA manufacturing and production-control data." actions={<button className="button primary" onClick={onExport}><Download size={16} /> Export report</button>} />
    <div className="report-filter-bar"><select value={report} onChange={(event) => setReport(event.target.value)}><option>Production performance</option><option>Supplier workload</option><option>Samples</option><option>Problems</option></select><select><option>04 Aug – 04 Sep 2026</option></select><select><option>HBA Production 2026</option></select><button className="button subtle"><Filter size={15} /> Apply filters</button></div>
    <div className="stats-grid stats-grid-six"><StatCard label="Manufacturing orders" value={String(productionOrders.length)} detail="Imported tracker" /><StatCard label="Total quantity" value={totalUnits.toLocaleString()} detail="All orders" /><StatCard label="Completed quantity" value={completedUnits.toLocaleString()} detail={`${Math.round(completedUnits / Math.max(1, totalUnits) * 100)}% of total`} /><StatCard label="Open tasks" value={String(productionTasks.length)} detail="Production control" /><StatCard label="Approved samples" value={String(sampleRecords.filter((sample) => sample.stage === "Approved").length)} detail={`${sampleRecords.length} total samples`} /><StatCard label="Open problems" value={String(productionProblems.filter((problem) => problem.status !== "Resolved").length)} detail="Needs action" emphasis="yellow" /></div>
    <div className="reports-grid"><Panel title={report} description="Planned versus completed units by tracker period"><div className="report-chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={chartProductionByWeek} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}><CartesianGrid stroke="#242824" strokeDasharray="3 5" vertical={false} /><XAxis dataKey="week" axisLine={false} tickLine={false} tick={{ fill: "#7f887d", fontSize: 11 }} /><YAxis axisLine={false} tickLine={false} tick={{ fill: "#7f887d", fontSize: 11 }} /><Tooltip contentStyle={{ background: "#151815", border: "1px solid #303630", borderRadius: 12 }} /><Bar dataKey="planned" fill="#4b534b" radius={[4, 4, 0, 0]} /><Bar dataKey="completed" fill="#a8ff60" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></div></Panel><Panel title="Order health" description="Current manufacturing tracker"><div className="pie-layout"><div className="pie-chart"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={pieData} dataKey="value" nameKey="name" innerRadius={52} outerRadius={78} paddingAngle={4}>{pieData.map((entry) => <Cell key={entry.name} fill={entry.color} />)}</Pie><Tooltip contentStyle={{ background: "#151815", border: "1px solid #303630", borderRadius: 12 }} /></PieChart></ResponsiveContainer><span><strong>{productionOrders.length}</strong><small>orders</small></span></div><div className="pie-legend">{pieData.map((entry) => <div key={entry.name}><i style={{ background: entry.color }} /><span>{entry.name}</span><strong>{entry.value}</strong></div>)}</div></div></Panel></div>
    <Panel title="Supplier records" description="Performance scores will appear after real reviews are entered"><TableWrap><table><thead><tr><th>Supplier</th><th>Category</th><th>Active work</th><th>On-time</th><th>Quality</th><th>Overall</th></tr></thead><tbody>{suppliers.map((supplier) => <tr key={supplier.code}><td><strong>{supplier.name}</strong><small>{supplier.code}</small></td><td>{supplier.category}</td><td>{supplier.activeOrders}</td><td>{supplier.onTime ? `${supplier.onTime}%` : "Not rated"}</td><td>{supplier.rating ? `${(100 - supplier.defectRate).toFixed(1)}%` : "Not rated"}</td><td>{supplier.rating ? `★ ${supplier.rating}` : "Not rated"}</td></tr>)}</tbody></table></TableWrap></Panel>
  </div>;
}

export function NotificationsPage({ notify }: { notify: Notify }) {
  const [items, setItems] = useState(initialNotifications);
  const markAll = () => { setItems((current) => current.map((item) => ({ ...item, read: true }))); notify("All notifications marked as read", "success"); };
  return <div className="page-stack"><PageHeader eyebrow="Action centre" title="Notifications" description="Approvals, delays, QC exceptions and due-date alerts." actions={<button className="button secondary" onClick={markAll}><Check size={16} /> Mark all read</button>} /><Panel><div className="notifications-list">{items.map((item) => <button key={item.id} className={item.read ? "read" : "unread"} onClick={() => setItems((current) => current.map((notification) => notification.id === item.id ? { ...notification, read: true } : notification))}><span className={`notification-symbol symbol-${item.severity}`}>{item.severity === "critical" ? <XCircle size={18} /> : item.severity === "warning" ? <AlertTriangle size={18} /> : item.severity === "success" ? <CheckCircle2 size={18} /> : <Bell size={18} />}</span><span><strong>{item.title}</strong><small>{item.detail}</small></span><time>{item.time}</time>{!item.read && <i />}</button>)}</div></Panel></div>;
}

export function DocumentsPage({ notify }: { notify: Notify }) {
  const uploadRef = useRef<HTMLInputElement>(null);
  const [search, setSearch] = useState("");
  const rows = documents.filter((item) => `${item.name} ${item.type} ${item.related}`.toLowerCase().includes(search.toLowerCase()));
  const uploadFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    let uploaded = 0;
    for (const file of Array.from(files)) {
      const form = new FormData();
      form.append("file", file);
      form.append("module", "Documents");
      form.append("recordId", "general");
      form.append("documentType", "Other");
      try {
        const response = await fetch("/api/production/documents", { method: "POST", body: form });
        if (response.ok) uploaded += 1;
      } catch {
        // Keep the demo surface responsive when storage is unavailable locally.
      }
    }
    notify(uploaded ? `${uploaded} document(s) uploaded` : `${files.length} document(s) queued; storage will sync when connected`, uploaded ? "success" : "warning");
  };
  return <div className="page-stack"><PageHeader eyebrow="Production library" title="Documents" description="No demo files were retained. Upload real tech packs, sample photos, QC evidence and invoices here." actions={<><input className="sr-only" ref={uploadRef} type="file" multiple onChange={(event) => void uploadFiles(event.target.files)} /><button className="button primary" onClick={() => uploadRef.current?.click()}><Upload size={16} /> Upload documents</button></>} /><div className="document-stat-grid"><button onClick={() => setSearch("Tech pack")}><span><FileText size={20} /></span><strong>Tech packs</strong><small>0 files</small></button><button onClick={() => setSearch("QC")}><span><ClipboardCheck size={20} /></span><strong>QC & defects</strong><small>0 files</small></button><button onClick={() => setSearch("Invoice")}><span><ReceiptText size={20} /></span><strong>Invoices</strong><small>0 files</small></button><button onClick={() => setSearch("")}><span><FolderOpen size={20} /></span><strong>All documents</strong><small>{documents.length} files</small></button></div><Panel className="table-panel"><div className="table-toolbar"><div className="search-field"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search document or related record" /></div><span className="toolbar-spacer" /><span className="result-count">{rows.length} files</span></div><div className="documents-table-list">{rows.map((item) => <button key={item.name} onClick={() => notify(`${item.name} opened`, "info")}><span className="file-type-icon">{item.type.includes("sample") ? <FileImage size={19} /> : <FileText size={19} />}</span><span><strong>{item.name}</strong><small>{item.type}</small></span><span>{item.related}</span><span>{item.owner}<small>{item.updated}</small></span><span>{item.size}</span><Download size={16} /></button>)}</div></Panel></div>;
}

export function UsersPage({ notify }: { notify: Notify }) {
  const users = JSON.parse(fixtureText("usersPageRows") || "[]") as Array<{ id: string; name: string; role: string; access: string; last: string; status: string }>;
  return <div className="page-stack"><PageHeader eyebrow="Access control" title="Users & roles" description="Team names imported from the production-control workspace. The Site remains publicly editable by link." actions={<button className="button primary" onClick={() => notify("User invitation form opened", "info")}><Plus size={16} /> Invite user</button>} /><div className="stats-grid stats-grid-four compact-stats"><Metric label="Team records" value={String(users.length)} /><Metric label="Owners" value="1" /><Metric label="Production team" value="2" /><Metric label="Public editing" value="On" /></div><Panel title="Users"><TableWrap><table><thead><tr><th>User</th><th>Role</th><th>Access scope</th><th>Source</th><th>Status</th><th></th></tr></thead><tbody>{users.map((user) => <tr key={user.id}><td><strong>{user.name}</strong><small>Email not recorded</small></td><td><Badge tone="grey">{user.role}</Badge></td><td>{user.access}</td><td>{user.last}</td><td><Badge>{user.status}</Badge></td><td><button className="table-action" onClick={() => notify(`${user.name} access editor opened`, "info")}>Manage</button></td></tr>)}</tbody></table></TableWrap></Panel></div>;
}

export function SettingsPage({ notify }: { notify: Notify }) {
  const [saved, setSaved] = useState(false);
  const [prefix, setPrefix] = useState("HBA-PO-{YYMMDD}-{SEQ}");
  const [staleDays, setStaleDays] = useState(2);
  const save = () => { setSaved(true); notify("System settings saved", "success"); window.setTimeout(() => setSaved(false), 2200); };
  return <div className="page-stack"><PageHeader eyebrow="Configuration" title="System settings" description="Codes, workflow thresholds, notifications and production defaults." actions={<button className="button primary" onClick={save}>{saved ? <Check size={16} /> : <Settings2 size={16} />}{saved ? "Saved" : "Save changes"}</button>} /><div className="settings-layout"><nav className="settings-nav"><button className="active"><SlidersHorizontal size={16} /> General</button><button onClick={() => notify("Code format section is visible in General", "info")}><Archive size={16} /> Numbering</button><button onClick={() => notify("Notification defaults are visible in General", "info")}><Bell size={16} /> Notifications</button><button onClick={() => notify("Role permissions are managed under Users & Roles", "info")}><LockKeyhole size={16} /> Permissions</button></nav><div className="settings-content"><Panel title="Production defaults"><div className="form-grid"><label>Default currency<select defaultValue="EGP"><option>EGP</option><option>USD</option><option>EUR</option></select></label><label>Working week<select defaultValue="Sunday – Thursday"><option>Sunday – Thursday</option><option>Monday – Friday</option></select></label><label>Default QC sample method<select defaultValue="AQL 2.5"><option>AQL 2.5</option><option>AQL 1.5</option><option>100% inspection</option></select></label><label>Supplier update becomes stale after<div className="input-suffix"><input type="number" min="1" value={staleDays} onChange={(event) => setStaleDays(Number(event.target.value))} /><span>days</span></div></label></div></Panel><Panel title="Order number format"><label className="wide-label">Production order pattern<input value={prefix} onChange={(event) => setPrefix(event.target.value)} /><small>Preview: HBA-PO-260904-001 · Available tokens: YY, MM, DD, SEQ</small></label></Panel><Panel title="Notification thresholds"><div className="toggle-list"><label><span><strong>Stage due soon</strong><small>Notify responsible users two days before plan date.</small></span><input type="checkbox" defaultChecked /></label><label><span><strong>Supplier update overdue</strong><small>Notify Production Manager after {staleDays} days without an update.</small></span><input type="checkbox" defaultChecked /></label><label><span><strong>QC failure escalation</strong><small>Notify CPO immediately for failed final inspection.</small></span><input type="checkbox" defaultChecked /></label><label><span><strong>Payment due reminder</strong><small>Notify three days before approved invoice is due.</small></span><input type="checkbox" defaultChecked /></label></div></Panel></div></div></div>;
}

export function AuditLogsPage({ onExport, activityData }: { onExport: () => void; activityData: typeof activityLog }) {
  const [search, setSearch] = useState("");
  const logs = activityData.filter((item) => `${item.user} ${item.action} ${item.module} ${item.record}`.toLowerCase().includes(search.toLowerCase()));
  return <div className="page-stack"><PageHeader eyebrow="Shared collaboration" title="Team changes" description="Live record of edits made by everyone using the public workspace." actions={<button className="button secondary" onClick={onExport}><Download size={16} /> Export log</button>} /><Panel className="table-panel"><div className="table-toolbar"><div className="search-field"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search editor, action, module or record" /></div><button className="button subtle"><Filter size={15} /> Filters</button><span className="toolbar-spacer" /><Badge tone="green"><Shield size={13} /> Live sync enabled</Badge></div><TableWrap><table><thead><tr><th>Editor</th><th>Action</th><th>Module</th><th>Record</th><th>Previous</th><th>Shared change</th><th>Timestamp</th><th>Source</th></tr></thead><tbody>{logs.map((item, index) => <tr key={`${item.time}-${index}`}><td><strong>{item.user}</strong></td><td>{item.action}</td><td><Badge tone="grey">{item.module}</Badge></td><td>{item.record}</td><td>{item.old}</td><td>{item.next}</td><td>{item.time}</td><td><small>Public workspace · Web</small></td></tr>)}</tbody></table></TableWrap></Panel></div>;
}

const supplierUpdateSchema = z.object({
  status: z.string().min(1, "Select a status"),
  completed: z.number().min(0).max(100000),
  rejected: z.number().min(0).max(100000),
  forecast: z.string().min(1, "Forecast date is required"),
  delayExpected: z.boolean(),
  delayReason: z.string().optional(),
  notes: z.string().min(8, "Add at least 8 characters of useful context"),
}).refine((data) => !data.delayExpected || Boolean(data.delayReason?.trim()), { path: ["delayReason"], message: "Explain the expected delay" });
type SupplierUpdateInput = z.infer<typeof supplierUpdateSchema>;

export function SupplierPortalPage({ notify, navigate, actorName, onSharedChange }: { notify: Notify; navigate: Navigate; actorName: string; onSharedChange: () => Promise<void> }) {
  const [submitted, setSubmitted] = useState(false);
  const { register, handleSubmit, watch, formState: { errors, isSubmitting }, reset } = useForm<SupplierUpdateInput>({ resolver: zodResolver(supplierUpdateSchema), defaultValues: { status: "In Progress", completed: 0, rejected: 0, forecast: "2026-09-10", delayExpected: false, delayReason: "", notes: "Production update for Cotton Candy order 807." } });
  // React Hook Form intentionally exposes an imperative subscription API.
  // eslint-disable-next-line react-hooks/incompatible-library
  const delayExpected = watch("delayExpected");
  const onSubmit = async (data: SupplierUpdateInput) => {
    try {
      const response = await fetch("/api/production/actions", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ action: "supplier_update", actorName, recordId: "807", payload: data }),
      });
      const result = await response.json() as { error?: string };
      if (!response.ok) throw new Error(result.error || "Could not submit the update");
      await onSharedChange();
      setSubmitted(true);
      notify(`Update submitted and shared: ${data.completed} completed units`, "success");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not submit the update", "warning");
    }
  };
  if (submitted) return <div className="supplier-portal standalone-portal"><div className="portal-success"><span><CheckCircle2 size={30} /></span><p className="eyebrow">Update submitted</p><h1>Waiting for HBA review</h1><p>Your update for order 807 was recorded and shared with the team.</p><button className="button primary" onClick={() => { setSubmitted(false); reset(); }}>Submit another update</button><button className="button secondary" onClick={() => navigate("/production-orders/807")}>View order summary</button></div></div>;
  return <div className="page-stack supplier-portal"><PageHeader eyebrow="Supplier workspace · Cotton Candy" title="Assigned production" description="Updates are saved to the shared HBA workspace and appear for the team within seconds." actions={<Badge tone="green">Public shared editing</Badge>} /><div className="portal-order-card"><div><span className="mono-cell">807</span><Badge tone="yellow">In Progress</Badge></div><h2>Snake Pants</h2><p>In Production · 85 units · Original estimate 21 Aug</p><div className="portal-progress"><ProgressBar value={60} tone="yellow" /><strong>60%</strong></div><div className="portal-metrics"><Metric label="Ordered" value="85" /><Metric label="Completed" value="Not recorded" /><Metric label="Rejected" value="0" /><Metric label="Remaining" value="Update required" /></div></div><div className="portal-form-grid"><Panel title="Submit shared stage update" description="HBA Production Manager will see this update immediately"><form className="supplier-update-form" onSubmit={handleSubmit(onSubmit)}><label>Current status<select {...register("status")}><option>In Progress</option><option>At Risk</option><option>Blocked</option><option>Partially Completed</option><option>Completed</option></select>{errors.status && <small className="field-error">{errors.status.message}</small>}</label><div className="form-grid"><label>Completed quantity<input type="number" {...register("completed", { valueAsNumber: true })} />{errors.completed && <small className="field-error">{errors.completed.message}</small>}</label><label>Rejected quantity<input type="number" {...register("rejected", { valueAsNumber: true })} />{errors.rejected && <small className="field-error">{errors.rejected.message}</small>}</label></div><label>Expected completion date<input type="date" {...register("forecast")} />{errors.forecast && <small className="field-error">{errors.forecast.message}</small>}</label><label className="checkbox-row"><input type="checkbox" {...register("delayExpected")} /><span><strong>A delay is expected</strong><small>HBA will receive an immediate at-risk update.</small></span></label>{delayExpected && <label>Delay reason<textarea rows={3} {...register("delayReason")} />{errors.delayReason && <small className="field-error">{errors.delayReason.message}</small>}</label>}<label>Production notes<textarea rows={4} {...register("notes")} />{errors.notes && <small className="field-error">{errors.notes.message}</small>}</label><label className="upload-drop"><Upload size={20} /><span><strong>Attach photos or documents</strong><small>JPG, PNG or PDF up to 20 MB</small></span><input type="file" multiple accept="image/*,.pdf" /></label><button className="button primary full-button" type="submit" disabled={isSubmitting}><Send size={16} /> {isSubmitting ? "Sharing update…" : "Share update with team"}</button></form></Panel><Panel title="Update history"><div className="portal-history"><div><i /><span><strong>Imported from manufacturing tracker</strong><small>Order 807 · Cotton Candy · 85 units</small></span><Badge tone="grey">Recorded</Badge></div><div><i /><span><strong>Production status</strong><small>In Production · original estimate 21 Aug</small></span><Badge tone="yellow">Follow up</Badge></div></div></Panel></div></div>;
}
