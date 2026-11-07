"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { announcePath, appAsset, appPath, appUrl } from "@/lib/base-path";
import * as XLSX from "xlsx";
import {
  Activity,
  AlertTriangle,
  Bell,
  Boxes,
  CalendarDays,
  Check,
  ChevronDown,
  CircleDollarSign,
  ClipboardCheck,
  Command,
  FileBarChart,
  Files,
  FlaskConical,
  Gauge,
  LayoutDashboard,
  Layers3,
  ListTodo,
  Menu,
  PackageCheck,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Route,
  Search,
  Settings2,
  ShieldCheck,
  Shirt,
  Truck,
  UserCog,
  Users,
  Warehouse,
  WalletCards,
  X,
} from "lucide-react";
import {
  activityLog,
  materials,
  products,
  productionOrders,
  productionTasks,
  suppliers,
  type DropPhase,
  type ProductionOrder,
  type ProductionTask,
  type Supplier,
} from "@/lib/demo-data";
import { Avatar, Badge, ProgressBar } from "@/components/ui";
import { TeamLogin, OrderQcPage } from "@/components/pages/team-workspace";
import type { TeamUser, QcCheck } from "@/lib/qc-checklist";
import { sampleRecords, type SampleRecord } from "@/lib/demo-data";
import { DashboardPage } from "@/components/pages/dashboard";
import {
  ProductionCalendarPage,
  ProductionKanbanPage,
  ProductionOrderDetailPage,
  ProductionOrdersPage,
  ProductionTimelinePage,
} from "@/components/pages/production";
import {
  BomPage,
  MaterialsPage,
  ProductDetailPage,
  ProductsPage,
  RouteTemplatesPage,
  SupplierDetailPage,
  SuppliersPage,
} from "@/components/pages/master-data";
import {
  AuditLogsPage,
  CostingPage,
  DocumentsPage,
  NotificationsPage,
  PaymentsPage,
  QualityControlPage,
  ReportsPage,
  SettingsPage,
  SupplierPortalPage,
  WarehousePage,
} from "@/components/pages/operations";
import { ProblemsPage, ProductionTasksPage, SamplesPage } from "@/components/pages/control-data";
import { fixtureList } from "@/lib/fixtures";

type IconType = typeof LayoutDashboard;

const navigation: { label: string; items: { label: string; path: string; icon: IconType; badge?: string }[] }[] = [
  { label: "Command", items: [
    { label: "Dashboard", path: "/", icon: LayoutDashboard },
    { label: "Production orders", path: "/production-orders", icon: Boxes, badge: "15" },
    { label: "Drop phases", path: "/drop-phases", icon: Layers3 },
    { label: "Production tasks", path: "/production-tasks", icon: ListTodo, badge: "16" },
    { label: "Samples", path: "/samples", icon: FlaskConical, badge: "15" },
    { label: "Problems", path: "/problems", icon: AlertTriangle, badge: "1" },
    { label: "Timeline", path: "/production-timeline", icon: Gauge },
    { label: "Calendar", path: "/production-calendar", icon: CalendarDays },
  ] },
  { label: "Master data", items: [
    { label: "Suppliers", path: "/suppliers", icon: Users },
    { label: "Products & SKUs", path: "/products", icon: Shirt },
    { label: "Materials", path: "/materials", icon: PackageCheck },
    { label: "Bill of materials", path: "/bom", icon: ClipboardCheck },
    { label: "Route templates", path: "/route-templates", icon: Route },
  ] },
  { label: "Operations", items: [
    { label: "Quality control", path: "/quality-control", icon: ShieldCheck, badge: "2" },
    { label: "Costing", path: "/costs", icon: CircleDollarSign },
    { label: "Payments", path: "/payments", icon: WalletCards, badge: "1" },
    { label: "Warehouse", path: "/warehouse-receiving", icon: Warehouse },
    { label: "Documents", path: "/documents", icon: Files },
    { label: "Reports", path: "/reports", icon: FileBarChart },
  ] },
  { label: "Governance", items: [
    { label: "Users & roles", path: "/users", icon: UserCog },
    { label: "Audit logs", path: "/audit-logs", icon: Activity },
    { label: "Settings", path: "/settings", icon: Settings2 },
  ] },
];

type Toast = { id: number; message: string; tone: "success" | "warning" | "info" };
type ActivityEntry = (typeof activityLog)[number];
type SharedStateResponse = {
  phases?: DropPhase[];
  samples?: SampleRecord[];
  products?: typeof products;
  user?: TeamUser;
  sampleStatuses?: Record<string, boolean>;
  qcChecks?: QcCheck[];
  orders?: ProductionOrder[];
  suppliers?: Supplier[];
  activity?: ActivityEntry[];
  tasks?: ProductionTask[];
  revision?: string;
};

export function HbaApp({ userName }: { userName: string; userEmail: string }) {
  const initialPathname = usePathname() || "/";
  const [pathname, setPathname] = useState(initialPathname);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [profileOpen, setProfileOpen] = useState(false);
  const [modal, setModal] = useState<"order" | "supplier" | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [ordersData, setOrdersData] = useState<ProductionOrder[]>(productionOrders);
  const [suppliersData, setSuppliersData] = useState<Supplier[]>(suppliers);
  const [activityData, setActivityData] = useState<ActivityEntry[]>(activityLog);
  const [tasksData, setTasksData] = useState<ProductionTask[]>(productionTasks);
  const [syncState, setSyncState] = useState<"syncing" | "live" | "offline">("syncing");
  const [lastSync, setLastSync] = useState("Connecting…");
  const lastRevision = useRef("");
  const [team,setTeam]=useState<TeamUser>({username:"",name:"Visitor",role:"viewer"});
  const [sampleRecordsData,setSampleRecordsData]=useState<SampleRecord[]>(sampleRecords);
  const [catalogData,setCatalogData]=useState(products);
  const [phases,setPhases]=useState<DropPhase[]>([]);
  const [sampleStatuses,setSampleStatuses]=useState<Record<string,boolean>>({});
  const [qcChecks,setQcChecks]=useState<QcCheck[]>([]);
  const samplesData=sampleRecordsData.map(sample=>({...sample,stage:sampleStatuses[sample.id]===true ? "Done" as const : sampleStatuses[sample.id]===false ? "In Progress" as const : sample.stage,progress:sampleStatuses[sample.id]===true ? 100 : sample.progress}));
  const currentRole = team.roleLabel ?? {admin:"Owner",production:"Production orders",qc:"QC Inspector",viewer:"View only"}[team.role];
  const canProduce=team.role==="production" || team.role==="admin";

  const notify = useCallback((message: string, tone: "success" | "warning" | "info" = "info") => {
    const id = Date.now();
    setToasts((items) => [...items, { id, message, tone }]);
    window.setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 3200);
  }, []);

  const refreshSharedData = useCallback(async (announce = false) => {
    setSyncState("syncing");
    try {
      const response = await fetch("/api/production/state", { cache: "no-store" });
      if (!response.ok) throw new Error("Shared state is unavailable");
      const shared = await response.json() as SharedStateResponse;
      if(shared.user) setTeam(shared.user);
      if(shared.phases) setPhases(shared.phases);
      if(shared.samples) setSampleRecordsData(shared.samples);
      if(shared.products) setCatalogData(shared.products);
      if(shared.sampleStatuses) setSampleStatuses(shared.sampleStatuses);
      if(shared.qcChecks) setQcChecks(shared.qcChecks);
      if (shared.orders) setOrdersData(shared.orders);
      if (shared.suppliers) setSuppliersData(shared.suppliers);
      if (shared.activity) setActivityData(shared.activity);
      if (shared.tasks) setTasksData(shared.tasks);
      if (announce && lastRevision.current && shared.revision && shared.revision !== lastRevision.current) {
        notify("A teammate's change was synced", "success");
      }
      if (shared.revision) lastRevision.current = shared.revision;
      setSyncState("live");
      setLastSync("Synced just now");
    } catch {
      setSyncState("offline");
      setLastSync("Reconnecting…");
    }
  }, [notify]);

  useEffect(() => {
    const syncPath = () => { const path = appPath(window.location.pathname); setPathname(path); announcePath(path); };
    window.addEventListener("popstate", syncPath);
    return () => window.removeEventListener("popstate", syncPath);
  }, []);

  useEffect(() => {
    const initial = window.setTimeout(() => void refreshSharedData(), 0);
    const interval = window.setInterval(() => void refreshSharedData(true), 5000);
    const refreshOnFocus = () => void refreshSharedData(true);
    window.addEventListener("focus", refreshOnFocus);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(interval);
      window.removeEventListener("focus", refreshOnFocus);
    };
  }, [refreshSharedData]);

  const navigate = (path: string) => {
    setMobileOpen(false);
    setCommandOpen(false);
    setSearch("");
    if (appPath(window.location.pathname) !== path) window.history.pushState({}, "", appUrl(path));
    announcePath(path);
    setPathname(path);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const globalResults = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return [];
    const results = [
      ...ordersData.map((order) => ({ label: order.product, detail: order.code, path: `/production-orders/${order.code}`, type: "Order" })),
      ...suppliersData.map((supplier) => ({ label: supplier.name, detail: supplier.code, path: `/suppliers/${supplier.code}`, type: "Supplier" })),
      ...products.map((product) => ({ label: product.name, detail: product.style, path: `/products/${product.style}`, type: "Product" })),
      ...materials.map((material) => ({ label: material.name, detail: material.code, path: "/materials", type: "Material" })),
    ];
    return results.filter((result) => `${result.label} ${result.detail}`.toLowerCase().includes(needle)).slice(0, 7);
  }, [ordersData, search, suppliersData]);

  const exportSheet = (name = "HBA-production-export") => {
    const source = pathname === '/production-tracker' ? ordersData.filter(order=>order.trackerOrderNumber != null).sort((a,b)=>(a.trackerOrderNumber ?? 0)-(b.trackerOrderNumber ?? 0)).map(order=>({
      'Order No':order.trackerOrderNumber,'Start Date':order.startDateISO || '',Model:order.trackerModel || order.product,'Product SKU / style':order.style,Supplier:order.supplier,Fabric:order.fabric || '',KG:order.fabricKg ?? '',Color:order.color,
      Status:order.status==='Completed'?'Completed':order.status==='Not Started'?'Waiting':order.status==='In Progress'?'In Production':order.status,Quantity:order.quantity,
      S:order.sizeBreakdown.S ?? 0,M:order.sizeBreakdown.M ?? 0,L:order.sizeBreakdown.L ?? 0,XL:order.sizeBreakdown.XL ?? 0,XXL:order.sizeBreakdown.XXL ?? 0,'Est. Completion':order.forecastDeliveryISO || '',
    })) : pathname.includes("supplier") ? suppliersData : pathname === "/products" || pathname.startsWith("/products/") ? catalogData : pathname.includes("material") || pathname.includes("bom") ? materials : ordersData;
    const worksheet = XLSX.utils.json_to_sheet(source);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, "HBA Data");
    XLSX.writeFile(workbook, `${name}.xlsx`);
    notify("Excel export downloaded", "success");
  };

  return (
    <div className={`app-frame ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <aside className={`sidebar ${mobileOpen ? "mobile-open" : ""}`}>
        <div className="brand-lockup">
          <button className="brand-mark" onClick={() => navigate("/")} aria-label="HBA dashboard"><Image unoptimized src={appAsset("/hba-logo.jpg")} alt="HBA" width="42" height="42" /></button>
          <div className="brand-copy"><strong>Production</strong><small>Operating System</small><a href={appAsset("/hba-logo.jpg")} download="HBA-logo.jpg">Download logo</a></div>
          <button className="sidebar-toggle" onClick={() => setSidebarCollapsed((value) => !value)} aria-label="Toggle sidebar">{sidebarCollapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}</button>
          <button className="mobile-close" onClick={() => setMobileOpen(false)} aria-label="Close navigation"><X size={19} /></button>
        </div>
        <nav className="sidebar-nav">
          {navigation.map((group) => (
            <div className="nav-group" key={group.label}>
              <span className="nav-label">{group.label}</span>
              {group.items.filter(item=>team.role==="admin" || !["/users","/settings"].includes(item.path)).map((item) => {
                const active = item.path === "/" ? pathname === "/" : pathname.startsWith(item.path);
                const Icon = item.icon;
                const badge = item.path === "/production-tasks" ? String(tasksData.filter(task=>!task.confirmed).length) : item.path === "/samples" ? String(samplesData.length) : item.path === "/production-orders" ? String(ordersData.length) : item.badge;
                return <button key={item.path} className={active ? "active" : ""} onClick={() => navigate(item.path)} title={sidebarCollapsed ? item.label : undefined}><Icon size={17} /><span>{item.label}</span>{badge && <em>{badge}</em>}</button>;
              })}
            </div>
          ))}
        </nav>
        <button className="supplier-portal-link" onClick={() => navigate("/supplier-portal")}><Truck size={17} /><span><strong>Supplier portal</strong><small>Assigned work view</small></span></button>
        <div className="sidebar-health"><div><span><i className={`sync-dot sync-${syncState}`} /> Shared workspace</span><small>{lastSync}</small></div><ProgressBar value={syncState === "live" ? 100 : syncState === "syncing" ? 72 : 28} tone={syncState === "offline" ? "yellow" : "green"} /></div>
      </aside>
      {mobileOpen && <button className="mobile-backdrop" onClick={() => setMobileOpen(false)} aria-label="Close navigation overlay" />}

      <div className="app-main">
        <header className="topbar">
          <button className="mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu size={20} /></button>
          <div className="global-search">
            <Search size={16} />
            <input value={search} onChange={(event) => setSearch(event.target.value)} onFocus={() => setCommandOpen(true)} placeholder="Search orders, suppliers, products…" aria-label="Global search" />
            <kbd><Command size={11} /> K</kbd>
            {commandOpen && search && (
              <div className="search-results">
                <div className="search-results-head"><span>Search results</span><small>{globalResults.length} found</small></div>
                {globalResults.length ? globalResults.map((result) => <button key={`${result.type}-${result.detail}`} onClick={() => navigate(result.path)}><span className="result-type">{result.type.slice(0, 1)}</span><span><strong>{result.label}</strong><small>{result.detail}</small></span><Badge tone="grey">{result.type}</Badge></button>) : <div className="no-results">No matching HBA records</div>}
              </div>
            )}
          </div>
          <span className="topbar-spacer" />
          <button className={`sync-pill sync-pill-${syncState}`} onClick={() => void refreshSharedData()} title="Refresh shared team data"><Activity size={15} /><span>{syncState === "live" ? "Team live" : syncState === "syncing" ? "Syncing" : "Reconnecting"}</span></button>
          {canProduce && <button className="quick-add" onClick={() => setModal("order")}><Plus size={16} /><span>Quick add</span></button>}
          <button className="topbar-icon" onClick={() => navigate("/notifications")} aria-label="Notifications"><Bell size={18} /><i /></button>
          <div className="profile-wrap">
            <button className="profile-button" onClick={() => setProfileOpen((value) => !value)}><Avatar name={team.name} small /><span><strong>{team.name}</strong><small>{currentRole}</small></span><ChevronDown size={14} /></button>
            {profileOpen && <div className="profile-menu"><div><strong>{team.name}</strong><small>{team.username || "View only"}</small></div><button onClick={()=>{navigate("/login");setProfileOpen(false);}}>Team account</button></div>}
          </div>
        </header>

        <main className="content-area" onClick={() => { if (commandOpen && !search) setCommandOpen(false); }}>
          
          {pathname==="/login" || team.mustChangePassword ? <TeamLogin user={team} refresh={()=>refreshSharedData()}/> : pathname==="/quality-control" ? <OrderQcPage orders={ordersData} checks={qcChecks} user={team} refresh={()=>refreshSharedData()}/> : <div className={team.role==="viewer" || team.role==="qc" ? "read-only-workspace" : ""}><RouteContent catalog={catalogData} phases={phases} canManageTasks={canProduce} pathname={pathname} navigate={navigate} notify={notify} onNewOrder={() => canProduce ? setModal("order") : notify("Sign in with the production account", "warning")} onNewSupplier={() => team.role==="admin" ? setModal("supplier") : notify("Owner access required", "warning")} onExport={exportSheet} orders={ordersData} supplierData={suppliersData} activityData={activityData} tasksData={tasksData} samplesData={samplesData} actorName={team.name} onSharedChange={() => refreshSharedData()} /></div>}

        </main>
      </div>

      {modal === "order" && <NewOrderModal phases={phases} catalog={catalogData} supplierData={suppliersData} onClose={() => setModal(null)} notify={notify} navigate={navigate} actorName={userName} onSharedChange={() => refreshSharedData()} />}
      {modal === "supplier" && <NewSupplierModal onClose={() => setModal(null)} notify={notify} actorName={userName} onSharedChange={() => refreshSharedData()} />}

      <div className="toast-stack" aria-live="polite">{toasts.map((toast) => <div className={`toast toast-${toast.tone}`} key={toast.id}><span>{toast.tone === "success" ? <Check size={15} /> : toast.tone === "warning" ? "!" : "i"}</span><strong>{toast.message}</strong><button onClick={() => setToasts((items) => items.filter((item) => item.id !== toast.id))}><X size={14} /></button></div>)}</div>
    </div>
  );
}

function RouteContent({ catalog, phases, canManageTasks, pathname, navigate, notify, onNewOrder, onNewSupplier, onExport, orders, supplierData, activityData, tasksData, samplesData, actorName, onSharedChange }: { catalog:typeof products; phases:DropPhase[]; canManageTasks: boolean; pathname: string; navigate: (path: string) => void; notify: (message: string, tone?: "success" | "warning" | "info") => void; onNewOrder: () => void; onNewSupplier: () => void; onExport: () => void; orders: ProductionOrder[]; supplierData: Supplier[]; activityData: ActivityEntry[]; tasksData: ProductionTask[]; samplesData: SampleRecord[]; actorName: string; onSharedChange: () => Promise<void> }) {
  const segments = pathname.split("/").filter(Boolean);
  if (pathname === "/" || pathname === "/dashboard") return <DashboardPage navigate={navigate} tasks={tasksData} orders={orders} samples={samplesData} />;
  if (segments[0] === "production-orders" && segments[1]) return <ProductionOrderDetailPage canUploadPhotos={canManageTasks} phases={phases} code={decodeURIComponent(segments[1])} navigate={navigate} notify={notify} orders={orders} supplierData={supplierData} actorName={actorName} onSharedChange={onSharedChange} />;
  if (pathname === "/production-orders" || pathname === "/drop-phases" || pathname === "/production-tracker") return <ProductionOrdersPage key={pathname} trackerView={pathname === "/production-tracker"} phaseView={pathname === "/drop-phases"} phases={phases} canManage={canManageTasks} notify={notify} onSharedChange={onSharedChange} navigate={navigate} onNewOrder={onNewOrder} onExport={onExport} orders={orders} />;
  if (pathname === "/production-tasks") return <ProductionTasksPage canManage={canManageTasks} notify={notify} tasks={tasksData} actorName={actorName} onSharedChange={onSharedChange} />;
  if (pathname === "/samples") return <SamplesPage canManage={canManageTasks} notify={notify} samples={samplesData} onSharedChange={onSharedChange} />;
  if (pathname === "/problems") return <ProblemsPage notify={notify} />;
  if (pathname === "/production-kanban") return <ProductionKanbanPage navigate={navigate} onNewOrder={onNewOrder} orders={orders} />;
  if (pathname === "/production-calendar") return <ProductionCalendarPage navigate={navigate} orders={orders} />;
  if (pathname === "/production-timeline") return <ProductionTimelinePage navigate={navigate} orders={orders} />;
  if (segments[0] === "suppliers" && segments[1]) return <SupplierDetailPage code={decodeURIComponent(segments[1])} navigate={navigate} notify={notify} supplierData={supplierData} orders={orders} />;
  if (pathname === "/suppliers") return <SuppliersPage navigate={navigate} onNewSupplier={onNewSupplier} onExport={onExport} notify={notify} supplierData={supplierData} />;
  if (segments[0] === "products" && segments[1]) return <ProductDetailPage catalog={catalog} style={decodeURIComponent(segments[1])} navigate={navigate} notify={notify} />;
  if (pathname === "/products") return <ProductsPage catalog={catalog} navigate={navigate} notify={notify} onExport={onExport} />;
  if (pathname === "/materials") return <MaterialsPage notify={notify} onExport={onExport} />;
  if (pathname === "/bom") return <BomPage notify={notify} onExport={onExport} />;
  if (pathname === "/route-templates") return <RouteTemplatesPage notify={notify} />;
  if (pathname === "/quality-control") return <QualityControlPage notify={notify} />;
  if (pathname === "/costs") return <CostingPage notify={notify} onExport={onExport} />;
  if (pathname === "/payments") return <PaymentsPage notify={notify} onExport={onExport} actorName={actorName} onSharedChange={onSharedChange} />;
  if (pathname === "/warehouse-receiving") return <WarehousePage notify={notify} onExport={onExport} />;
  if (pathname === "/reports") return <ReportsPage onExport={onExport} />;
  if (pathname === "/notifications") return <NotificationsPage notify={notify} />;
  if (pathname === "/documents") return <DocumentsPage notify={notify} />;
  if (pathname === "/users") return <div className="page-stack"><h1>Team accounts</h1>{fixtureList("teamAccountLines").map((line) => <p key={line}>{line}</p>)}<p>Team members sign in from the Account page with their own passwords.</p></div>;
  if (pathname === "/settings") return <SettingsPage notify={notify} />;
  if (pathname === "/audit-logs") return <AuditLogsPage onExport={onExport} activityData={activityData} />;
  if (pathname === "/supplier-portal") return <SupplierPortalPage notify={notify} navigate={navigate} actorName={actorName} onSharedChange={onSharedChange} />;
  return <div className="not-found"><span>404</span><h1>Page not found</h1><p>This route is not part of the HBA production workspace.</p><button className="button primary" onClick={() => navigate("/")}>Return to dashboard</button></div>;
}

function ModalShell({ title, description, children, onClose }: { title: string; description: string; children: React.ReactNode; onClose: () => void }) {
  return <div className="modal-backdrop" onClick={onClose}><section className="modal" onClick={(event) => event.stopPropagation()}><header><div><p className="eyebrow">Create record</p><h2>{title}</h2><p>{description}</p></div><button className="icon-button" onClick={onClose}><X size={18} /></button></header>{children}</section></div>;
}

function NewOrderModal({ phases, catalog, supplierData, onClose, notify, navigate, actorName, onSharedChange }: { phases:DropPhase[]; catalog: typeof products; supplierData: Supplier[]; onClose: () => void; notify: (message: string, tone?: "success" | "warning" | "info") => void; navigate: (path: string) => void; actorName: string; onSharedChange: () => Promise<void> }) {
  const [quantity, setQuantity] = useState(100);
  const [submitting, setSubmitting] = useState(false);
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch("/api/production/actions", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          action: "create_order",
          actorName,
          quantity,
          product: form.get("product"),
          collection: form.get("collection"),
          color: form.get("color"),
          targetDelivery: form.get("targetDelivery"),
          manufacturer: form.get("manufacturer"),
          phaseId: form.get("phaseId"),
        }),
      });
      const result = await response.json() as { error?: string; recordId?: string };
      if (!response.ok) throw new Error(result.error || "Could not create the order");
      await onSharedChange();
      onClose();
      notify(`Shared order ${result.recordId ?? "created"} is now visible to the team`, "success");
      navigate("/production-orders");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not save the order", "warning");
    } finally {
      setSubmitting(false);
    }
  };
  return <ModalShell title="New production order" description="This order will be saved to the shared team workspace." onClose={onClose}><form onSubmit={submit} className="modal-form"><div className="form-grid"><label>Product<select name="product">{catalog.map((product) => <option key={product.style}>{product.name}</option>)}</select></label><label>Drop phase<select name="phaseId"><option value="">Unassigned</option>{phases.map(phase=><option key={phase.id} value={phase.id}>{phase.name}</option>)}</select></label><label>Collection<select name="collection"><option>HBA October 2026</option><option>HBA Production 2026</option><option>Selected Drafts</option></select></label><label>Colour<select name="color"><option>Black</option><option>Realtree</option><option>Off-white</option><option>Grey</option><option>Brown</option><option>Army</option></select></label><label>Total quantity<input type="number" min="1" value={quantity} onChange={(event) => setQuantity(Number(event.target.value))} required /></label><label>Target delivery<input name="targetDelivery" type="date" defaultValue="2026-09-30" required /></label><label>Main manufacturer<select name="manufacturer">{supplierData.filter((supplier) => supplier.category.toLowerCase().includes("manufacturer") || fixtureList("orderModalSuppliers").includes(supplier.name)).map((supplier) => <option key={supplier.code}>{supplier.name}</option>)}</select></label></div><label>Production route<select name="route"><option>Pants — cut, sew and final QC</option><option>T-shirts — cut, sew and final QC</option><option>Sample — pattern, sample and approval</option></select></label><div className="modal-size-preview"><span>Suggested size split</span><div>{[["S", 0], ["M", 20], ["L", 20], ["XL", 40], ["XXL", 20]].map(([size, percent]) => <span key={size}><strong>{size}</strong><small>{Math.round(quantity * Number(percent) / 100)}</small></span>)}</div><small><Check size={13} /> Adjust the size split after creating the order</small></div><footer><button className="button subtle" type="button" onClick={onClose}>Cancel</button><button className="button primary" disabled={submitting} type="submit">{submitting ? "Saving for team…" : "Create shared order"}</button></footer></form></ModalShell>;
}

function NewSupplierModal({ onClose, notify, actorName, onSharedChange }: { onClose: () => void; notify: (message: string, tone?: "success" | "warning" | "info") => void; actorName: string; onSharedChange: () => Promise<void> }) {
  const [submitting, setSubmitting] = useState(false);
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch("/api/production/actions", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          action: "create_supplier",
          actorName,
          name: form.get("name"),
          category: form.get("category"),
          contact: form.get("contact"),
          phone: form.get("phone"),
          city: form.get("city"),
          paymentTerms: form.get("paymentTerms"),
          notes: form.get("notes"),
        }),
      });
      const result = await response.json() as { error?: string; recordId?: string };
      if (!response.ok) throw new Error(result.error || "Could not create the supplier");
      await onSharedChange();
      onClose();
      notify(`${result.recordId ?? "Supplier"} saved and shared with the team`, "success");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Could not save the supplier", "warning");
    } finally {
      setSubmitting(false);
    }
  };
  return <ModalShell title="New supplier" description="This supplier will be visible to everyone using the workspace." onClose={onClose}><form onSubmit={submit} className="modal-form"><div className="form-grid"><label>Supplier name<input name="name" required placeholder="e.g. Cairo Trim Works" /></label><label>Category<select name="category"><option>Fabric supplier</option><option>Full-package manufacturer</option><option>Screen printing</option><option>Packaging</option></select></label><label>Contact person<input name="contact" required placeholder="Full name" /></label><label>Phone / WhatsApp<input name="phone" required placeholder="+20 ..." /></label><label>City<input name="city" defaultValue="Cairo" /></label><label>Payment terms<select name="paymentTerms"><option>Net 15</option><option>Net 30</option><option>50% / 25% / 25%</option></select></label></div><label>Services and qualification notes<textarea name="notes" rows={3} placeholder="Capabilities, machines, capacity and sample requirements" /></label><footer><button className="button subtle" type="button" onClick={onClose}>Cancel</button><button className="button primary" disabled={submitting} type="submit">{submitting ? "Saving for team…" : "Create shared supplier"}</button></footer></form></ModalShell>;
}
