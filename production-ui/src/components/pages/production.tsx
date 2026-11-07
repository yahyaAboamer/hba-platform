"use client";

import { useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  CalendarDays,
  Check,
  CheckCircle2,
  Circle,
  Clock3,
  Download,
  Edit3,
  FileText,
  Filter,
  LayoutGrid,
  List,
  MessageSquareText,
  MoreHorizontal,
  PackageCheck,
  Plus,
  Search,
  ShieldCheck,
  Truck,
  X,
} from "lucide-react";
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table";
import {
  activityLog,
  costLines,
  documents,
  payments,
  productionOrders,
  qcInspections,
  type DropPhase,
  type ProductionOrder,
  type ProductionStage,
  type Supplier,
} from "@/lib/demo-data";
import { OrderPhotos } from "@/components/order-photos";
import { ManufacturingTracker } from "@/components/manufacturing-tracker";
import { DropPhasePanel, OrderPhasePicker } from "@/components/drop-phases";
import { formatCurrency } from "@/lib/business-logic";
import { Badge, Metric, Panel, PageHeader, ProgressBar, TableWrap, statusTone } from "@/components/ui";

type Navigate = (path: string) => void;
type Notify = (message: string, tone?: "success" | "warning" | "info") => void;

function viewButtons(active: string, navigate: Navigate) {
  return (
    <div className="segmented view-switcher">
      <button className={active === "table" ? "active" : ""} onClick={() => navigate("/production-orders")} aria-label="Table view"><List size={16} /> Table</button>
      <button className={active === "tracker" ? "active" : ""} onClick={() => navigate("/production-tracker")} aria-label="Manufacturing tracker view"><List size={16} /> Tracker</button>
      <button className={active === "kanban" ? "active" : ""} onClick={() => navigate("/production-kanban")} aria-label="Kanban view"><LayoutGrid size={16} /> Kanban</button>
      <button className={active === "calendar" ? "active" : ""} onClick={() => navigate("/production-calendar")} aria-label="Calendar view"><CalendarDays size={16} /> Calendar</button>
    </div>
  );
}

export function ProductionOrdersPage({
  phaseView = false, trackerView = false, phases, canManage, notify, onSharedChange,
  navigate,
  onNewOrder,
  onExport,
  orders,
}: {
  phaseView?: boolean;
  trackerView?: boolean;
  phases: DropPhase[];
  canManage: boolean;
  notify: Notify;
  onSharedChange: ()=>Promise<void>;
  navigate: Navigate;
  onNewOrder: () => void;
  onExport: () => void;
  orders: ProductionOrder[];
}) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("All statuses");
  const [phase, setPhase] = useState(phaseView ? "phase-one-drop" : "all");
  const [sorting, setSorting] = useState<SortingState>([]);
  const [trackerOnly, setTrackerOnly] = useState(true);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return orders.filter(
      (order) =>
        (!trackerView || !trackerOnly || order.trackerOrderNumber != null) &&
        (phase === "all" || (phase === "unassigned" ? !order.phaseId : order.phaseId === phase)) &&
        (status === "All statuses" || order.status === status) &&
        (!needle || `${order.code} ${order.product} ${order.trackerModel || ""} ${order.style} ${order.supplier} ${order.color} ${order.fabric || ""}`.toLowerCase().includes(needle)),
    );
  }, [orders, search, status, phase, trackerView, trackerOnly]);

  const columns = useMemo<ColumnDef<ProductionOrder>[]>(
    () => [
      {
        accessorKey: "code",
        header: "Production order",
        cell: ({ row }) => <><strong className="mono-cell">{row.original.code}</strong><small>{row.original.collection}</small></>,
      },
      {
        accessorKey: "product",
        header: "Product",
        cell: ({ row }) => <><strong>{row.original.product}</strong><small>{row.original.color}</small></>,
      },
      {accessorKey:'style',header:'Product SKU / style',cell:({row})=><button className="text-button mono-cell" onClick={event=>{event.stopPropagation();navigate(`/products/${encodeURIComponent(row.original.style)}`);}}>{row.original.style}</button>},
      {
        accessorKey: "quantity",
        header: "Units",
        cell: ({ row }) => <><strong>{row.original.quantity || "Not set"}</strong><small>{row.original.accepted} accepted</small></>,
      },
      {
        id: "phase", header:"Drop phase", cell:({row})=><OrderPhasePicker order={row.original} phases={phases} canManage={canManage} notify={notify} refresh={onSharedChange}/>,
      },
      {
        accessorKey: "currentStage",
        header: "Current stage",
        cell: ({ row }) => <>{row.original.currentStage}<small>{row.original.supplier}</small></>,
      },
      {
        accessorKey: "progress",
        header: "Progress",
        cell: ({ row }) => <div className="table-progress"><ProgressBar value={row.original.progress} tone={statusTone(row.original.status)} /><span>{row.original.progress}%</span></div>,
      },
      {
        accessorKey: "forecastDelivery",
        header: "Forecast delivery",
        cell: ({ row }) => <>{row.original.forecastDelivery}<small className={row.original.delayDays ? "danger-text" : "muted-text"}>{row.original.forecastDelivery === "—" ? "Date not set" : row.original.delayDays ? `+${row.original.delayDays} days` : "On schedule"}</small></>,
      },
      { accessorKey: "status", header: "Status", cell: ({ row }) => <Badge>{row.original.status}</Badge> },
      { id: "menu", header: "", cell: () => <MoreHorizontal size={17} className="muted-icon" /> },
    ],
    [phases,canManage,notify,onSharedChange,navigate],
  );

  // TanStack Table returns imperative helpers by design.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: filtered,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Production control"
        title={phaseView ? "Drop phases" : trackerView ? "Manufacturing tracker" : "Production orders"}
        description={phaseView ? "Plan each drop and manage its production orders." : trackerView ? "Order quantities, fabrics, sizes and estimated completion dates." : "Plan, approve and track every order from request to warehouse receipt."}
        actions={<><button className="button secondary" onClick={onExport}><Download size={16} /> Export</button><button className="button primary" onClick={onNewOrder}><Plus size={16} /> New order</button></>}
      />
      {phaseView && <DropPhasePanel phases={phases} orders={orders} canManage={canManage} selected={phase} onSelect={setPhase} notify={notify} refresh={onSharedChange}/>}
      {trackerView ? <div className="stats-grid stats-grid-four compact-stats"><Metric label="Tracker orders" value={orders.filter(order=>order.trackerOrderNumber != null).length}/><Metric label="Units scheduled" value={orders.filter(order=>order.trackerOrderNumber != null).reduce((sum,order)=>sum+order.quantity,0).toLocaleString()}/><Metric label="Completed" value={orders.filter(order=>order.trackerOrderNumber != null && order.status==='Completed').length}/><Metric label="In production" value={orders.filter(order=>order.trackerOrderNumber != null && order.status==='In Progress').length}/></div> : <div className="stats-grid stats-grid-four compact-stats">
        <Metric label="Open orders" value={orders.filter((order) => order.status !== "Warehouse Received" && order.status !== "Completed").length} />
        <Metric label="Units scheduled" value={orders.reduce((sum, order) => sum + order.quantity, 0).toLocaleString()} />
        <Metric label="On-time forecast" value="66.7%" accent />
        <Metric label="Value committed" value="EGP 489.6K" />
      </div>}
      {!phaseView && !trackerView && <DropPhasePanel phases={phases} orders={orders} canManage={canManage} selected={phase} onSelect={setPhase} notify={notify} refresh={onSharedChange}/>}
      {trackerView && <div className="tracker-summary"><strong>October tracker · 1001–1020</strong><span>{orders.filter(order=>order.trackerOrderNumber != null).reduce((sum,order)=>sum+order.quantity,0).toLocaleString()} units · {orders.filter(order=>order.trackerOrderNumber != null && order.status==='Completed').length} completed · {orders.filter(order=>order.trackerOrderNumber != null && order.status==='In Progress').length} in production · {orders.filter(order=>order.trackerOrderNumber != null && ['Waiting','Not Started'].includes(order.status)).length} waiting</span></div>}
      <Panel className="table-panel">
        <div className="table-toolbar">
          <div className="search-field"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search order, product, style or supplier" aria-label="Search production orders" />{search && <button onClick={() => setSearch("")} aria-label="Clear search"><X size={14} /></button>}</div>
          {trackerView && <select aria-label="Tracker orders" value={trackerOnly ? "tracker" : "all"} onChange={event=>setTrackerOnly(event.target.value === "tracker")}><option value="tracker">October tracker</option><option value="all">All production orders</option></select>}
          <select aria-label="Filter by drop phase" value={phase} onChange={event=>setPhase(event.target.value)}><option value="all">All phases</option><option value="unassigned">Unassigned</option>{phases.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select>
          <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Filter by status">
            <option>All statuses</option>
            <option>Not Started</option><option>Waiting</option><option>In Progress</option><option>Completed</option><option>On Track</option><option>At Risk</option><option>Delayed</option><option>Blocked</option><option>Pending Approval</option><option>Warehouse Received</option>
          </select>
          <button className="button subtle" onClick={() => { setSearch(""); setStatus("All statuses"); setPhase("all"); setTrackerOnly(true); }}><Filter size={15} /> Reset</button>
          <span className="toolbar-spacer" />
          {viewButtons(trackerView ? "tracker" : "table", navigate)}
        </div>
        {trackerView ? <ManufacturingTracker orders={filtered} navigate={navigate}/> : <TableWrap>
          <table>
            <thead>
              {table.getHeaderGroups().map((group) => (
                <tr key={group.id}>
                  {group.headers.map((header) => (
                    <th key={header.id} onClick={header.column.getToggleSortingHandler()} className={header.column.getCanSort() ? "sortable" : ""}>
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {{ asc: " ↑", desc: " ↓" }[header.column.getIsSorted() as string] ?? null}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr key={row.id} className="clickable-row" onClick={() => navigate(`/production-orders/${row.original.code}`)}>
                  {row.getVisibleCells().map((cell) => <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>}
        <div className="table-footer"><span>Showing {filtered.length} of {orders.length} orders</span><span>Shared team data · live</span></div>
      </Panel>
    </div>
  );
}

function StageTimeline({ stages, onSelect }: { stages: ProductionStage[]; onSelect: (stage: ProductionStage) => void }) {
  return (
    <div className="production-timeline">
      {stages.map((stage, index) => (
        <button key={stage.id} className={`timeline-stage timeline-${statusTone(stage.status)}`} onClick={() => onSelect(stage)}>
          <span className="timeline-rail" />
          <span className="timeline-marker">{stage.status === "Completed" ? <Check size={15} /> : stage.progress > 0 ? <Clock3 size={14} /> : <Circle size={12} />}</span>
          <span className="timeline-copy">
            <small>0{index + 1}</small>
            <strong>{stage.shortName}</strong>
            <em>{stage.status}</em>
          </span>
          <span className="timeline-meta"><small>Plan</small><strong>{stage.planned}</strong></span>
          <span className="timeline-meta"><small>Forecast</small><strong className={stage.forecast !== stage.planned ? "warning-text" : ""}>{stage.forecast}</strong></span>
          <ProgressBar value={stage.progress} tone={statusTone(stage.status)} />
        </button>
      ))}
    </div>
  );
}

export function ProductionOrderDetailPage({ canUploadPhotos, phases, code, navigate, notify, orders, supplierData, actorName, onSharedChange }: { canUploadPhotos:boolean; phases:DropPhase[]; code: string; navigate: Navigate; notify: Notify; orders: ProductionOrder[]; supplierData: Supplier[]; actorName: string; onSharedChange: () => Promise<void> }) {
  const requestedOrder = orders.find((item) => item.code === code || item.legacyCode === code || item.id === code);
  const order = requestedOrder ?? orders[0] ?? productionOrders[0];
  const stages = order.stages.length ? order.stages : productionOrders[0].stages.map((stage, index) => ({ ...stage, id: `${order.id}-${index}`, supplier: index < 2 ? order.supplier : stage.supplier }));
  const [activeTab, setActiveTab] = useState("Overview");
  const [selectedStage, setSelectedStage] = useState<ProductionStage | null>(null);
  const [approved, setApproved] = useState(order.status !== "Pending Approval");
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const tabs = ["Overview", "Photos", "Timeline", "Size Breakdown", "Materials & BOM", "Production Stages", "Supplier Updates", "Quality Control", "Costs", "Payments", "Documents", "Warehouse Receiving", "Activity Log"];

  return (
    <div className="page-stack order-detail-page">
      <button className="back-link" onClick={() => navigate("/production-orders")}><ArrowLeft size={15} /> Production orders</button>
      <div className="order-hero">
        <div className="order-hero-main">
          <div className="order-kicker"><span className="mono-cell">{order.code}</span><Badge tone="grey">{order.phaseName || "Unassigned"}</Badge><Badge>{approved ? order.status : "Pending Approval"}</Badge><Badge tone={order.priority === "Critical" ? "red" : order.priority === "High" ? "yellow" : "grey"}>{order.priority} priority</Badge></div>
          <h1>{order.product}</h1>
          <p>{order.style} · {order.collection} · {order.color}</p>
        </div>
        <div className="order-hero-actions">
          {!approved && <button className="button primary" onClick={() => { setApproved(true); notify(`${order.code} approved`, "success"); }}><CheckCircle2 size={16} /> Approve order</button>}
          <button className="button secondary" onClick={()=>setActiveTab("Photos")}><Plus size={16}/>{canUploadPhotos ? "Add photos" : "Photos"}</button>
          <button className="button secondary" onClick={() => notify("Printable production order prepared", "success")}><FileText size={16} /> Print PO</button>
          <button className="button secondary" onClick={() => setEditing(true)}><Edit3 size={16} /> Edit</button>
        </div>
      </div>

      <div className="order-summary-strip">
        <Metric label="Ordered quantity" value={order.quantity ? `${order.quantity} units` : "Not set"} />
        <Metric label="Overall progress" value={`${order.progress}%`} accent />
        <Metric label="Current stage" value={order.currentStage} />
        <Metric label="Planned delivery" value={order.plannedDelivery} />
        <Metric label="Forecast delivery" value={order.forecastDelivery} />
        <Metric label="Delay" value={order.delayDays ? `+${order.delayDays} days` : "On schedule"} />
      </div>

      <Panel className="timeline-panel" title="Production journey" description="Select a stage to review quantities, dates and supplier notes" action={<button className="text-button" onClick={() => setActiveTab("Timeline")}>Expanded timeline <ArrowRight size={14} /></button>}>
        <StageTimeline stages={stages} onSelect={setSelectedStage} />
      </Panel>

      <div className="tabs-scroll"><div className="tabs" role="tablist">{tabs.map((tab) => <button role="tab" aria-selected={activeTab === tab} key={tab} className={activeTab === tab ? "active" : ""} onClick={() => setActiveTab(tab)}>{tab}</button>)}</div></div>

      {activeTab === "Photos" ? requestedOrder ? <OrderPhotos key={order.id} orderId={order.id} orderCode={order.code} canUpload={canUploadPhotos}/> : <Panel title="Order photos"><p>Waiting for this order to load. Refresh the workspace if it is unavailable.</p></Panel> : <OrderTabContent activeTab={activeTab} order={order} stages={stages} navigate={navigate} notify={notify} setSelectedStage={setSelectedStage} />}

      {selectedStage && (
        <div className="drawer-backdrop" onClick={() => setSelectedStage(null)}>
          <aside className="stage-drawer" onClick={(event) => event.stopPropagation()}>
            <div className="drawer-header"><div><p className="eyebrow">Stage {String(stages.findIndex((stage) => stage.id === selectedStage.id) + 1).padStart(2, "0")}</p><h2>{selectedStage.name}</h2></div><button className="icon-button" onClick={() => setSelectedStage(null)} aria-label="Close stage details"><X size={18} /></button></div>
            <Badge>{selectedStage.status}</Badge>
            <div className="drawer-progress"><span>{selectedStage.progress}% complete</span><ProgressBar value={selectedStage.progress} tone={statusTone(selectedStage.status)} /></div>
            <div className="drawer-metrics"><Metric label="Supplier" value={selectedStage.supplier} /><Metric label="Input quantity" value={selectedStage.quantity} /><Metric label="Accepted" value={selectedStage.accepted} /><Metric label="Rejected" value={selectedStage.rejected} /><Metric label="Planned finish" value={selectedStage.planned} /><Metric label="Forecast finish" value={selectedStage.forecast} /></div>
            <div className="note-box"><strong>Latest note</strong><p>{selectedStage.notes}</p></div>
            <div className="drawer-actions"><button className="button secondary" onClick={() => notify("Supplier update request sent", "success")}><MessageSquareText size={16} /> Request update</button><button className="button primary" onClick={() => { notify(`${selectedStage.shortName} marked reviewed`, "success"); setSelectedStage(null); }}><ShieldCheck size={16} /> Review stage</button></div>
          </aside>
        </div>
      )}

      {editing && (
        <div className="modal-backdrop" onClick={() => setEditing(false)}>
          <section className="modal" onClick={(event) => event.stopPropagation()}>
            <header><div><p className="eyebrow">Production order</p><h2>Edit {order.code}</h2><p>Saved changes sync to the HBA team.</p></div><button className="icon-button" onClick={() => setEditing(false)} aria-label="Close editor"><X size={18} /></button></header>
            <form className="modal-form" onSubmit={async (event) => {
              event.preventDefault();
              setSaving(true);
              const form = new FormData(event.currentTarget);
              try {
                const response = await fetch("/api/production/actions", {
                  method: "POST",
                  headers: { "content-type": "application/json" },
                  body: JSON.stringify({
                    action: "update_order",
                    recordId: order.code,
                    actorName,
                    payload: Object.fromEntries(form.entries()),
                  }),
                });
                const result = await response.json() as { error?: string };
                if (!response.ok) throw new Error(result.error || "Could not update the order");
                await onSharedChange();
                setEditing(false);
                notify(`${order.code} updated for everyone`, "success");
              } catch (error) {
                notify(error instanceof Error ? error.message : "Could not save the changes", "warning");
              } finally {
                setSaving(false);
              }
            }}>
              <div className="form-grid">
                <label>Drop phase<select name="phaseId" defaultValue={order.phaseId || ""}><option value="">Unassigned</option>{phases.map(phase=><option key={phase.id} value={phase.id}>{phase.name}</option>)}</select></label><label>Collection<input name="collection" defaultValue={order.collection} required /></label>
                <label>Colour<input name="color" defaultValue={order.color} required /></label>
                <label>Total quantity<input name="quantity" type="number" min="0" max="100000" defaultValue={order.quantity} required /></label>
                <label>Fabric<input name="fabric" defaultValue={order.fabric || ""} /></label>
                <label>Fabric weight (KG)<input name="fabricKg" type="number" min="0" step="0.1" defaultValue={order.fabricKg ?? ""} /></label>
                <label>Priority<select name="priority" defaultValue={order.priority}><option>Critical</option><option>High</option><option>Normal</option><option>Low</option></select></label>
                <label>Status<select name="status" defaultValue={order.status}><option>Pending Approval</option><option>Not Started</option><option>Waiting</option><option>In Progress</option><option>On Track</option><option>At Risk</option><option>Delayed</option><option>Blocked</option><option>Waiting for QC</option><option>Rework</option><option>Completed</option><option>Warehouse Received</option></select></label>
                <label>Progress %<input name="progress" type="number" min="0" max="100" step="1" defaultValue={order.progress} required /></label>
                <label>Current stage<input name="currentStage" defaultValue={order.currentStage} required /></label>
                <label>Planned start<input name="startDate" type="date" defaultValue={order.startDateISO} /></label>
                <label>Planned delivery<input name="plannedDelivery" type="date" defaultValue={order.plannedDeliveryISO} /></label>
                <label>Forecast delivery<input name="forecastDelivery" type="date" defaultValue={order.forecastDeliveryISO} /></label>
                <label>Main manufacturer<select name="supplier" defaultValue={order.supplier}>{supplierData.map((supplier) => <option key={supplier.code}>{supplier.name}</option>)}</select></label>
                <label>Target unit cost (EGP)<input name="targetCost" type="number" min="0" step="0.01" defaultValue={order.targetCost} /></label>
              </div>
              <fieldset className="tracker-size-fields"><legend>Size quantities</legend>{['S','M','L','XL','XXL'].map(size=><label key={size}>{size}<input name={`size_${size}`} type="number" min="0" step="1" defaultValue={order.sizeBreakdown[size] ?? 0}/></label>)}</fieldset>
              <label>Production notes<textarea name="notes" rows={4} defaultValue={order.notes} placeholder="Shared notes for the production team" /></label>
              <footer><button className="button subtle" type="button" onClick={() => setEditing(false)}>Cancel</button><button className="button primary" type="submit" disabled={saving}>{saving ? "Saving for everyone…" : "Save shared changes"}</button></footer>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}

function OrderTabContent({ activeTab, order, stages, navigate, notify, setSelectedStage }: { activeTab: string; order: ProductionOrder; stages: ProductionStage[]; navigate: Navigate; notify: Notify; setSelectedStage: (stage: ProductionStage) => void }) {
  if (activeTab === "Overview") {
    return (
      <div className="detail-grid">
        <Panel title="Order brief" className="detail-main-card"><div className="definition-grid"><Metric label="Product" value={order.product} /><Metric label="Product SKU / style" value={order.style} /><Metric label="Collection" value={order.collection} /><Metric label="Colour" value={order.color} /><Metric label="Production manager" value={order.manager} /><Metric label="Main manufacturer" value={order.supplier} /><Metric label="Planned start" value={order.startDate} /><Metric label="Source" value="HBA manufacturing tracker" /></div><div className="note-box"><strong>Production note</strong><p>{order.notes || "No production notes recorded."}</p></div></Panel>
        <Panel title="Data status" description="Information available from the imported tracker"><div className="approval-list"><button onClick={() => notify("Manufacturing tracker source", "info")}><span><CheckCircle2 size={17} /><span><strong>Order record</strong><small>Imported with quantity and size breakdown</small></span></span><Badge tone="green">Recorded</Badge></button><button onClick={() => notify("Open the Samples section for sample records", "info")}><span><Clock3 size={17} /><span><strong>Sample approval</strong><small>Tracked separately under Samples</small></span></span><Badge tone="blue">Separate</Badge></button><button onClick={() => notify("No warehouse receipt has been recorded", "warning")}><span><Truck size={17} /><span><strong>Warehouse receipt</strong><small>No GRN imported</small></span></span><Badge tone="grey">Not recorded</Badge></button></div></Panel>
      </div>
    );
  }
  if (activeTab === "Timeline") return <Panel title="Detailed production timeline" description="Plan, forecast and actual dates"><div className="expanded-timeline">{stages.map((stage, index) => <button key={stage.id} onClick={() => setSelectedStage(stage)}><span className={`expanded-marker marker-${statusTone(stage.status)}`}>{stage.status === "Completed" ? <Check size={15} /> : index + 1}</span><span><strong>{stage.name}</strong><small>{stage.supplier}</small></span><span><small>Planned</small><strong>{stage.planned}</strong></span><span><small>Forecast</small><strong>{stage.forecast}</strong></span><Badge>{stage.status}</Badge><span className="expanded-progress"><ProgressBar value={stage.progress} tone={statusTone(stage.status)} /><small>{stage.progress}%</small></span></button>)}</div></Panel>;
  if (activeTab === "Size Breakdown") return <Panel title="Size breakdown" description={`${order.quantity} units across ${Object.keys(order.sizeBreakdown).length} sizes`}><div className="size-grid">{Object.entries(order.sizeBreakdown).map(([size, quantity]) => <div key={size}><span>{size}</span><strong>{quantity}</strong><small>{Math.round((quantity / Math.max(1, order.quantity)) * 100)}%</small></div>)}</div><div className="validation-banner success"><CheckCircle2 size={17} /><span><strong>{Object.keys(order.sizeBreakdown).length ? "Breakdown imported" : "No size quantities entered"}</strong><small>{Object.keys(order.sizeBreakdown).length ? `The imported sizes total ${Object.values(order.sizeBreakdown).reduce((sum, value) => sum + value, 0)} units.` : "Add quantities when they are confirmed."}</small></span></div></Panel>;
  if (activeTab === "Materials & BOM") return <Panel title="Bill of materials" description="No demo BOM was retained"><div className="note-box"><strong>No BOM configured</strong><p>Add real consumption, wastage and cost data after the material specification is confirmed.</p></div></Panel>;
  if (activeTab === "Production Stages") return <Panel title="Stage records" description="Quantities and responsibility at each production gate"><TableWrap><table><thead><tr><th>#</th><th>Stage</th><th>Supplier</th><th>Input</th><th>Accepted</th><th>Rejected</th><th>Progress</th><th>Status</th></tr></thead><tbody>{stages.map((stage, index) => <tr key={stage.id} className="clickable-row" onClick={() => setSelectedStage(stage)}><td>0{index + 1}</td><td><strong>{stage.name}</strong></td><td>{stage.supplier}</td><td>{stage.quantity}</td><td>{stage.accepted}</td><td>{stage.rejected}</td><td>{stage.progress}%</td><td><Badge>{stage.status}</Badge></td></tr>)}</tbody></table></TableWrap></Panel>;
  if (activeTab === "Supplier Updates") return <Panel title="Supplier update history" description="Supplier submissions require Production Manager review"><div className="feed-list detailed-feed">{stages.slice(1, 6).reverse().map((stage, index) => <button key={stage.id} onClick={() => setSelectedStage(stage)}><i className={`feed-dot feed-${index === 0 ? "warning" : "success"}`} /><span><strong>{stage.supplier} updated {stage.shortName}</strong><small>{stage.notes}</small></span><time>{index === 0 ? "12 min" : `${index + 1}d`}</time></button>)}</div></Panel>;
  if (activeTab === "Quality Control") return <Panel title="Quality inspections" description="Incoming, in-line and final checks"><TableWrap><table><thead><tr><th>Inspection</th><th>Type</th><th>Supplier</th><th>Inspected</th><th>Rejected</th><th>Defect rate</th><th>Result</th></tr></thead><tbody>{qcInspections.filter((inspection) => inspection.order === order.code).map((inspection) => <tr key={inspection.number} className="clickable-row" onClick={() => navigate("/quality-control")}><td><strong className="mono-cell">{inspection.number}</strong><small>{inspection.date}</small></td><td>{inspection.type}</td><td>{inspection.supplier}</td><td>{inspection.inspected}</td><td>{inspection.rejected}</td><td>{inspection.defectRate}%</td><td><Badge>{inspection.result}</Badge></td></tr>)}</tbody></table></TableWrap></Panel>;
  if (activeTab === "Costs") return <Panel title="Planned versus actual cost" description={`Actual unit cost uses accepted quantity only (${order.accepted || 1} units)`}><TableWrap><table><thead><tr><th>Category</th><th>Supplier</th><th>Planned</th><th>Actual</th><th>Variance</th><th>Status</th></tr></thead><tbody>{costLines.map((line) => <tr key={line.category}><td><strong>{line.category}</strong></td><td>{line.supplier}</td><td>{formatCurrency(line.planned)}</td><td>{formatCurrency(line.actual)}</td><td className={line.variance > 0 ? "danger-text" : "success-text"}>{line.variance > 0 ? "+" : ""}{formatCurrency(line.variance)}</td><td><Badge>{line.status}</Badge></td></tr>)}</tbody></table></TableWrap></Panel>;
  if (activeTab === "Payments") return <Panel title="Supplier invoices & payments"><TableWrap><table><thead><tr><th>Invoice</th><th>Supplier</th><th>Amount</th><th>Paid</th><th>Due</th><th>Status</th></tr></thead><tbody>{payments.filter((item) => item.order === order.code).map((item) => <tr key={item.invoice}><td><strong className="mono-cell">{item.invoice}</strong></td><td>{item.supplier}</td><td>{formatCurrency(item.amount)}</td><td>{formatCurrency(item.paid)}</td><td>{item.due}</td><td><Badge>{item.status}</Badge></td></tr>)}</tbody></table></TableWrap></Panel>;
  if (activeTab === "Documents") return <Panel title="Order documents" action={<button className="button secondary" onClick={() => notify("Upload panel opened", "info")}><Plus size={15} /> Upload</button>}><div className="document-grid">{documents.filter((item) => item.related.includes(order.style) || item.related.includes(order.code) || item.related.includes("MAT-")).map((item) => <button key={item.name} onClick={() => notify(`${item.name} selected`, "info")}><FileText size={22} /><span><strong>{item.name}</strong><small>{item.type} · {item.size}</small></span><Download size={15} /></button>)}</div></Panel>;
  if (activeTab === "Warehouse Receiving") return <Panel title="Warehouse receiving" description="No GRN was imported for this order"><div className="warehouse-state"><span className="warehouse-icon"><PackageCheck size={28} /></span><div><h3>Receipt not recorded</h3><p>Create a GRN only after the physical quantity is counted and accepted.</p></div><button className="button secondary" onClick={() => notify("Draft GRN can be prepared in Warehouse", "info")}>Prepare draft GRN</button></div></Panel>;
  return <Panel title="Immutable activity log" description="Important field and approval changes"><TableWrap><table><thead><tr><th>User</th><th>Action</th><th>Module</th><th>Record</th><th>Old value</th><th>New value</th><th>Time</th></tr></thead><tbody>{activityLog.map((item) => <tr key={`${item.action}-${item.time}`}><td>{item.user}</td><td><strong>{item.action}</strong></td><td>{item.module}</td><td>{item.record}</td><td>{item.old}</td><td>{item.next}</td><td>{item.time}</td></tr>)}</tbody></table></TableWrap></Panel>;
}

export function ProductionKanbanPage({ navigate, onNewOrder, orders }: { navigate: Navigate; onNewOrder: () => void; orders: ProductionOrder[] }) {
  const columns = [
    { name: "Waiting", statuses: ["Waiting", "Not Started", "Pending Approval"] },
    { name: "In production", statuses: ["In Progress", "On Track", "At Risk"] },
    { name: "Exceptions", statuses: ["Delayed", "Blocked", "Rework"] },
    { name: "Completed", statuses: ["Completed", "Warehouse Received"] },
  ];
  return <div className="page-stack"><PageHeader eyebrow="Visual planning" title="Production kanban" description="Orders grouped by operational state and urgency." actions={<button className="button primary" onClick={onNewOrder}><Plus size={16} /> New order</button>} /><div className="view-row">{viewButtons("kanban", navigate)}</div><div className="kanban-board">{columns.map((column) => { const items = orders.filter((order) => column.statuses.includes(order.status)); return <section key={column.name} className="kanban-column"><header><div><h2>{column.name}</h2><span>{items.length}</span></div><MoreHorizontal size={17} /></header><div className="kanban-cards">{items.map((order) => <button key={order.code} className="kanban-card" onClick={() => navigate(`/production-orders/${order.code}`)}><div><Badge>{order.status}</Badge><span className="mono-cell">{order.code.split("-").slice(-2).join("-")}</span></div><h3>{order.product}</h3><p>{order.currentStage}</p><ProgressBar value={order.progress} tone={statusTone(order.status)} /><div className="kanban-meta"><span>{order.progress}%</span><span>{order.forecastDelivery}</span></div><footer><span>{order.quantity} units</span><span className={order.delayDays ? "danger-text" : "success-text"}>{order.delayDays ? `+${order.delayDays}d` : "On time"}</span></footer></button>)}</div></section>; })}</div></div>;
}

export function ProductionCalendarPage({ navigate, orders }: { navigate: Navigate; orders: ProductionOrder[] }) {
  const [monthOffset, setMonthOffset] = useState(0);
  const label = monthOffset === 0 ? "August 2026" : monthOffset < 0 ? "July 2026" : "September 2026";
  const dayOffset = monthOffset === 0 ? 6 : monthOffset < 0 ? 3 : 2;
  const days = monthOffset === 0 ? 31 : monthOffset < 0 ? 31 : 30;
  const events: Record<number, ProductionOrder[]> = {};
  orders.forEach((order, index) => { const day = monthOffset === 0 ? ((index * 5 + 19) % days) + 1 : monthOffset < 0 ? ((index * 4 + 27) % days) + 1 : ((index * 4 + 3) % days) + 1; events[day] = [...(events[day] ?? []), order]; });
  const cells = Array.from({ length: dayOffset + days }, (_, index) => index < dayOffset ? null : index - dayOffset + 1);
  return <div className="page-stack"><PageHeader eyebrow="Delivery planning" title="Production calendar" description="Forecast completions, milestones and supplier commitments." /><div className="calendar-toolbar"><div>{viewButtons("calendar", navigate)}</div><div className="month-switcher"><button className="icon-button" onClick={() => setMonthOffset(Math.max(-1, monthOffset - 1))}><ArrowLeft size={16} /></button><strong>{label}</strong><button className="icon-button" onClick={() => setMonthOffset(Math.min(1, monthOffset + 1))}><ArrowRight size={16} /></button></div></div><Panel className="calendar-panel"><div className="calendar-weekdays">{["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => <span key={day}>{day}</span>)}</div><div className="calendar-grid">{cells.map((day, index) => <div key={index} className={!day ? "calendar-empty" : "calendar-day"}>{day && <><span>{day}</span>{(events[day] ?? []).map((order) => <button key={order.code} className={`calendar-event event-${statusTone(order.status)}`} onClick={() => navigate(`/production-orders/${order.code}`)}><strong>{order.product}</strong><small>{order.status}</small></button>)}</>}</div>)}</div></Panel></div>;
}

export function ProductionTimelinePage({ navigate, orders }: { navigate: Navigate; orders: ProductionOrder[] }) {
  return <div className="page-stack"><PageHeader eyebrow="Portfolio schedule" title="Production timeline" description="Cross-order view of progress, forecast shifts and delivery exposure." actions={<button className="button secondary" onClick={() => navigate("/production-calendar")}><CalendarDays size={16} /> Calendar</button>} /><Panel><div className="gantt-header"><span>Order / product</span>{["02 Aug", "09 Aug", "16 Aug", "23 Aug", "30 Aug", "06 Sep"].map((date) => <span key={date}>{date}</span>)}</div><div className="gantt-body">{orders.map((order, index) => <button key={order.code} className="gantt-row" onClick={() => navigate(`/production-orders/${order.code}`)}><span><strong>{order.product}</strong><small>{order.code}</small></span><span className="gantt-track"><i className={`gantt-bar gantt-${statusTone(order.status)}`} style={{ left: `${Math.min(28, index * 4)}%`, width: `${Math.max(18, order.progress * 0.58)}%` }}><em>{order.progress}%</em></i><b className="gantt-today" /></span><Badge>{order.status}</Badge></button>)}</div></Panel></div>;
}
