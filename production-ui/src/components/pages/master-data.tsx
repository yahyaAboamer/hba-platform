"use client";

import { useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Building2,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDollarSign,
  Copy,
  Download,
  Factory,
  FileSpreadsheet,
  FileText,
  Gauge,
  PackagePlus,
  Phone,
  Plus,
  Search,
  Star,
  Upload,
} from "lucide-react";
import {
  bomItems,
  materials,
  products,
  routeTemplates,
  sampleRecords,
  suppliers,
  type ProductionOrder,
  type Supplier,
} from "@/lib/demo-data";
import { formatCurrency } from "@/lib/business-logic";
import { Badge, Metric, Panel, PageHeader, ProgressBar, StatCard, TableWrap } from "@/components/ui";

type ProductCatalog = typeof products;

type Navigate = (path: string) => void;
type Notify = (message: string, tone?: "success" | "warning" | "info") => void;

function ImportButton({ notify, label = "Import" }: { notify: Notify; label?: string }) {
  const inputRef = useRef<HTMLInputElement>(null);
  return <><button className="button secondary" onClick={() => inputRef.current?.click()}><Upload size={16} /> {label}</button><input ref={inputRef} className="sr-only" type="file" accept=".csv,.xlsx" onChange={(event) => event.target.files?.[0] && notify(`${event.target.files[0].name} validated and ready to preview`, "success")} /></>;
}

export function SuppliersPage({ navigate, onNewSupplier, onExport, notify, supplierData }: { navigate: Navigate; onNewSupplier: () => void; onExport: () => void; notify: Notify; supplierData: Supplier[] }) {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All categories");
  const filtered = useMemo(() => supplierData.filter((supplier) => (category === "All categories" || supplier.category === category) && `${supplier.name} ${supplier.code} ${supplier.contact}`.toLowerCase().includes(search.toLowerCase())), [supplierData, search, category]);
  const averageOnTime = supplierData.length ? supplierData.reduce((sum, supplier) => sum + supplier.onTime, 0) / supplierData.length : 0;
  return <div className="page-stack"><PageHeader eyebrow="Supplier network" title="Suppliers" description="Qualified partners, current workload and performance history in one shared place." actions={<><ImportButton notify={notify} /><button className="button secondary" onClick={onExport}><Download size={16} /> Export</button><button className="button primary" onClick={onNewSupplier}><Plus size={16} /> New supplier</button></>} /><div className="stats-grid stats-grid-four"><StatCard label="Active suppliers" value={String(supplierData.filter((supplier) => supplier.status === "Active").length)} detail={`across ${new Set(supplierData.map((supplier) => supplier.category)).size} service groups`} icon={<Building2 size={17} />} /><StatCard label="Supplier records" value={String(supplierData.length)} detail="shared with the full team" icon={<Gauge size={17} />} /><StatCard label="Average on-time" value={`${averageOnTime.toFixed(1)}%`} trend="Live" trendDirection="up" detail="shared supplier data" icon={<CheckCircle2 size={17} />} emphasis="green" /><StatCard label="Open supplier orders" value={String(supplierData.reduce((sum, supplier) => sum + supplier.activeOrders, 0))} detail="current production workload" icon={<Factory size={17} />} /></div><Panel className="table-panel"><div className="table-toolbar"><div className="search-field"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search supplier, code or contact" /></div><select value={category} onChange={(event) => setCategory(event.target.value)}><option>All categories</option>{Array.from(new Set(supplierData.map((supplier) => supplier.category))).map((item) => <option key={item}>{item}</option>)}</select><span className="toolbar-spacer" /><span className="result-count">{filtered.length} suppliers</span></div><TableWrap><table><thead><tr><th>Supplier</th><th>Category</th><th>Contact</th><th>Current workload</th><th>On-time</th><th>Defect rate</th><th>Rating</th><th>Status</th></tr></thead><tbody>{filtered.map((supplier) => <tr key={supplier.code} className="clickable-row" onClick={() => navigate(`/suppliers/${supplier.code}`)}><td><strong>{supplier.name}</strong><small className="mono-cell">{supplier.code}</small></td><td>{supplier.category}<small>{supplier.city}</small></td><td>{supplier.contact}<small>{supplier.phone}</small></td><td><strong>{supplier.activeOrders} orders</strong><small>{supplier.capacity}</small></td><td><div className="score-cell"><ProgressBar value={supplier.onTime} tone={supplier.onTime < 85 ? "yellow" : "green"} /><span>{supplier.onTime}%</span></div></td><td className={supplier.defectRate > 3 ? "danger-text" : ""}>{supplier.defectRate}%</td><td><span className="rating"><Star size={14} fill="currentColor" /> {supplier.rating}</span></td><td><Badge>{supplier.status}</Badge></td></tr>)}</tbody></table></TableWrap></Panel></div>;
}

export function SupplierDetailPage({ code, navigate, notify, supplierData, orders }: { code: string; navigate: Navigate; notify: Notify; supplierData: Supplier[]; orders: ProductionOrder[] }) {
  const supplier = supplierData.find((item) => item.code === code) ?? supplierData[0] ?? suppliers[0];
  const assigned = orders.filter((order) => order.supplier === supplier.name || order.stages.some((stage) => stage.supplier.includes(supplier.name.split(" ")[0])));
  const completed = assigned.filter((order) => order.status === "Completed");
  return <div className="page-stack">
    <button className="back-link" onClick={() => navigate("/suppliers")}><ArrowLeft size={15} /> Suppliers</button>
    <div className="supplier-hero"><span className="supplier-monogram">{supplier.name.split(" ").map((part) => part[0]).join("").slice(0, 2)}</span><div><div className="order-kicker"><span className="mono-cell">{supplier.code}</span><Badge>{supplier.status}</Badge></div><h1>{supplier.name}</h1><p>{supplier.category} · {supplier.city}, Egypt</p></div><div className="supplier-hero-actions"><button className="button secondary" onClick={() => notify(supplier.phone === "—" ? "Contact details have not been recorded" : `Calling ${supplier.contact} at ${supplier.phone}`, "info")}><Phone size={16} /> Contact</button><button className="button primary" onClick={() => notify("Supplier review form opened", "info")}><Star size={16} /> Add review</button></div></div>
    <div className="scorecard-grid"><div><span>Overall score</span><strong>{supplier.rating ? <>{supplier.rating}<small>/5</small></> : "Not rated"}</strong><div className="stars">{supplier.rating ? "★★★★★" : "—"}</div></div>{[{ label: "On-time delivery", value: supplier.onTime }, { label: "Quality score", value: supplier.rating ? Math.round(100 - supplier.defectRate) : 0 }, { label: "Communication", value: 0 }, { label: "Price competitiveness", value: 0 }].map((score) => <div key={score.label}><span>{score.label}</span><strong>{score.value ? `${score.value}%` : "Not rated"}</strong><ProgressBar value={score.value} tone={score.value && score.value < 85 ? "yellow" : "green"} /></div>)}</div>
    <div className="detail-grid supplier-detail-grid"><Panel title="Supplier profile"><div className="definition-grid"><Metric label="Primary contact" value={supplier.contact} /><Metric label="Phone / WhatsApp" value={supplier.phone} /><Metric label="Location" value={supplier.city} /><Metric label="Payment terms" value={supplier.paymentTerms} /><Metric label="Normal lead time" value={supplier.leadTime} /><Metric label="Maximum capacity" value={supplier.capacity} /><Metric label="Currency" value="EGP" /><Metric label="Tax registration" value="Not recorded" /></div></Panel><Panel title="Performance snapshot"><div className="performance-kpis"><Metric label="Assigned orders" value={String(assigned.length)} /><Metric label="Completed orders" value={String(completed.length)} /><Metric label="Completed units" value={String(completed.reduce((sum, order) => sum + order.quantity, 0))} /><Metric label="Average defect rate" value={supplier.rating ? `${supplier.defectRate}%` : "Not rated"} /></div><div className="note-box"><strong>Production Manager note</strong><p>{supplier.status === "Review" ? "This supplier has an open follow-up or qualification action." : "Add capacity, lead time, commercial terms and a rating after the next confirmed order."}</p></div></Panel></div>
    <Panel title="Assigned production" description={`${assigned.length} current orders`}><TableWrap><table><thead><tr><th>Order</th><th>Product</th><th>Stage</th><th>Forecast</th><th>Progress</th><th>Status</th></tr></thead><tbody>{assigned.length ? assigned.map((order) => <tr key={order.code} className="clickable-row" onClick={() => navigate(`/production-orders/${order.code}`)}><td><strong className="mono-cell">{order.code}</strong></td><td>{order.product}</td><td>{order.currentStage}</td><td>{order.forecastDelivery}</td><td>{order.progress}%</td><td><Badge>{order.status}</Badge></td></tr>) : <tr><td colSpan={6}><small>No manufacturing orders are assigned to this supplier yet.</small></td></tr>}</tbody></table></TableWrap></Panel>
  </div>;
}

export function ProductsPage({ catalog:products, navigate, notify, onExport }: { catalog:ProductCatalog; navigate: Navigate; notify: Notify; onExport: () => void }) {
  const [search, setSearch] = useState("");
  const filtered = products.filter((product) => `${product.name} ${product.style} ${product.collection}`.toLowerCase().includes(search.toLowerCase()));
  return <div className="page-stack"><PageHeader eyebrow="Product master" title="Products & SKUs" description="Shared product codes used by production orders." actions={<><ImportButton notify={notify} /><button className="button secondary" onClick={onExport}><Download size={16} /> Export</button><button className="button primary" onClick={() => notify("New product form opened", "info")}><PackagePlus size={16} /> New product</button></>} /><div className="stats-grid stats-grid-four compact-stats"><Metric label="Product records" value={String(products.length)} /><Metric label="Selected drafts" value={String(products.filter((product) => product.collection === "Selected Drafts").length)} /><Metric label="Approved samples" value={String(sampleRecords.filter((sample) => sample.stage === "Approved").length)} /><Metric label="Samples in progress" value={String(sampleRecords.filter((sample) => sample.stage !== "Approved").length)} /></div><Panel className="table-panel"><div className="table-toolbar"><div className="search-field"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search product, style or collection" /></div><span className="toolbar-spacer" /><span className="result-count">{filtered.length} styles</span></div><TableWrap><table><thead><tr><th>Product SKU / style</th><th>Product</th><th>Category</th><th>Collection</th><th>Variants</th><th>Fabric</th><th>Target cost</th><th>Status</th></tr></thead><tbody>{filtered.map((product) => <tr key={product.style} className="clickable-row" onClick={() => navigate(`/products/${product.style}`)}><td><strong className="mono-cell">{product.style}</strong></td><td><strong>{product.name}</strong></td><td>{product.category}</td><td>{product.collection}</td><td>{product.variants ? `${product.variants} SKUs` : "Not entered"}</td><td>{product.gsm ? `${product.gsm} GSM` : "Not entered"}</td><td>{product.targetCost ? formatCurrency(product.targetCost) : "Not entered"}</td><td><Badge>{product.status}</Badge></td></tr>)}</tbody></table></TableWrap></Panel></div>;
}

export function ProductDetailPage({ catalog:products, style, navigate, notify }: { catalog:ProductCatalog; style: string; navigate: Navigate; notify: Notify }) {
  const product = products.find((item) => item.style === style) ?? products[0];
  const isSelectedDraft = product.collection === "Selected Drafts";
  return <div className="page-stack">
    <button className="back-link" onClick={() => navigate("/products")}><ArrowLeft size={15} /> Products</button>
    <div className="product-hero"><div className="product-placeholder"><span>HBA</span><small>{product.category}</small></div><div className="product-hero-copy"><div className="order-kicker"><span className="mono-cell">{product.style}</span><Badge>{product.status}</Badge></div><h1>{product.name}</h1><p>{product.collection}</p><div className="product-actions"><button className="button secondary" onClick={() => notify("No tech pack has been uploaded for this product", "info")}><FileText size={16} /> Documents</button><button className="button primary" onClick={() => notify("Product editor opened", "info")}>Edit specification</button></div></div></div>
    <div className="detail-grid"><Panel title="Product record"><div className="definition-grid"><Metric label="Category" value={product.category} /><Metric label="Collection" value={product.collection} /><Metric label="Status" value={product.status} /><Metric label="SKU variants" value={product.variants ? String(product.variants) : "Not entered"} /><Metric label="Fabric weight" value={product.gsm ? `${product.gsm} GSM` : "Not entered"} /><Metric label="Target unit cost" value={product.targetCost ? formatCurrency(product.targetCost) : "Not entered"} /></div></Panel><Panel title="Source note"><div className="note-box"><strong>{isSelectedDraft ? "Selected product" : "Manufacturing tracker product"}</strong><p>{isSelectedDraft ? "This product was marked with a green indicator in the supplied draft-product screenshot." : "This product was imported from the HBA manufacturing progress tracker."}</p></div></Panel></div>
    <Panel title="Specification status" description="No measurements or commercial assumptions were invented"><div className="note-box"><strong>Information still required</strong><p>Tech pack, fabric composition, GSM, colourways, size chart, sample approval, supplier cost and packaging requirements.</p></div></Panel>
  </div>;
}

export function MaterialsPage({ notify, onExport }: { notify: Notify; onExport: () => void }) {
  const [search, setSearch] = useState("");
  const [stockFilter, setStockFilter] = useState("All stock levels");
  const filtered = materials.filter((material) => (stockFilter === "All stock levels" || material.status === stockFilter) && `${material.name} ${material.code} ${material.supplier}`.toLowerCase().includes(search.toLowerCase()));
  return <div className="page-stack">
    <PageHeader eyebrow="Materials control" title="Materials" description="Material names imported from the manufacturing tracker and compression problem." actions={<><ImportButton notify={notify} /><button className="button secondary" onClick={onExport}><Download size={16} /> Export</button><button className="button primary" onClick={() => notify("New material form opened", "info")}><Plus size={16} /> New material</button></>} />
    <div className="stats-grid stats-grid-four"><StatCard label="Material masters" value={String(materials.length)} detail="Imported material names" icon={<PackagePlus size={17} />} /><StatCard label="Inventory value" value="Not entered" detail="Add stock and costs when confirmed" icon={<CircleDollarSign size={17} />} /><StatCard label="Under review" value={String(materials.filter((material) => material.status === "Review").length)} detail="Compression fabric" icon={<Gauge size={17} />} emphasis="yellow" /><StatCard label="Critical stock" value="0" detail="No stock levels recorded" icon={<FileSpreadsheet size={17} />} emphasis="red" /></div>
    <Panel className="table-panel"><div className="table-toolbar"><div className="search-field"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search material, code or supplier" /></div><select value={stockFilter} onChange={(event) => setStockFilter(event.target.value)}><option>All stock levels</option><option>Not recorded</option><option>Review</option></select></div><TableWrap><table><thead><tr><th>Material</th><th>Category</th><th>Supplier</th><th>Available</th><th>Reserved</th><th>Reorder level</th><th>Unit cost</th><th>Status</th></tr></thead><tbody>{filtered.map((material) => <tr key={material.code} className="clickable-row" onClick={() => notify(`${material.name} stock card opened`, "info")}><td><strong>{material.name}</strong><small className="mono-cell">{material.code}</small></td><td>{material.category}</td><td>{material.supplier}</td><td>{material.stock ? `${material.stock} ${material.uom}` : "Not entered"}</td><td>{material.reserved ? `${material.reserved} ${material.uom}` : "Not entered"}</td><td>{material.reorder ? `${material.reorder} ${material.uom}` : "Not entered"}</td><td>{material.unitCost ? formatCurrency(material.unitCost) : "Not entered"}</td><td><Badge>{material.status}</Badge></td></tr>)}</tbody></table></TableWrap></Panel>
  </div>;
}

export function BomPage({ notify, onExport }: { notify: Notify; onExport: () => void }) {
  return <div className="page-stack"><PageHeader eyebrow="Material planning" title="Bill of materials" description="No demo BOM was retained. Create the real consumption and cost standard after materials are confirmed." actions={<><button className="button secondary" onClick={onExport}><Download size={16} /> Export BOM</button><button className="button primary" onClick={() => notify("New BOM form opened", "info")}><Plus size={16} /> Create BOM</button></>} /><Panel title="No approved BOM yet" description="Start with one product and add fabric, trims, consumption, wastage and cost."><div className="note-box"><strong>Current state</strong><p>{bomItems.length} BOM items are recorded. Product and sample data has been imported without inventing material consumption or supplier pricing.</p></div></Panel></div>;
}

export function RouteTemplatesPage({ notify }: { notify: Notify }) {
  const [expanded, setExpanded] = useState(0);
  const stages = ["Production request & approval", "Fabric & trims sourcing", "Pre-production sample", "Cutting", "Sewing", "Garment wash & puff print", "Final QC, packing & delivery"];
  return <div className="page-stack"><PageHeader eyebrow="Workflow design" title="Production route templates" description="Reusable stage sequences, lead times, dependencies and control gates." actions={<button className="button primary" onClick={() => notify("New route template builder opened", "info")}><Plus size={16} /> New route</button>} /><div className="route-grid">{routeTemplates.map((route, index) => <Panel key={route.name} className={`route-card ${expanded === index ? "expanded" : ""}`}><button className="route-card-header" onClick={() => setExpanded(expanded === index ? -1 : index)}><span className="route-icon"><Factory size={20} /></span><span><strong>{route.name}</strong><small>{route.products} products · {route.stages} stages · {route.leadTime} working days</small></span><Badge>{route.status}</Badge>{expanded === index ? <ChevronDown size={18} /> : <ChevronRight size={18} />}</button>{expanded === index && <div className="route-stages">{stages.slice(0, route.stages).map((stage, stageIndex) => <div key={stage}><span>{stageIndex + 1}</span><strong>{stage}</strong><small>{stageIndex === 0 ? "1 day · CPO approval" : stageIndex === 1 ? "7 days · Parallel trims allowed" : `${Math.max(2, Math.min(5, stageIndex))} days`}</small>{stageIndex > 0 && <i />}</div>)}<div className="route-card-actions"><button className="button subtle" onClick={() => notify(`${route.name} duplicated`, "success")}><Copy size={15} /> Duplicate</button><button className="button secondary" onClick={() => notify(`${route.name} editor opened`, "info")}>Edit route</button></div></div>}</Panel>)}</div></div>;
}
