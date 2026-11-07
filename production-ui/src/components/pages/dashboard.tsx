"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Banknote,
  Boxes,
  CalendarClock,
  CheckCircle2,
  Clock3,
  PackageCheck,
  ShieldAlert,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  chartProductionByWeek,
  chartSupplierPerformance,
  notifications,
  productionProblems,
  type ProductionOrder,
  type SampleRecord,
  qcInspections,

  type ProductionTask,
} from "@/lib/demo-data";
import { formatCurrency } from "@/lib/business-logic";
import { Badge, Panel, PageHeader, ProgressBar, StatCard, TableWrap } from "@/components/ui";
import { fixtureText } from "@/lib/fixtures";

const tooltipStyle = {
  background: "#151815",
  border: "1px solid #303630",
  borderRadius: "12px",
  color: "#f6f8f3",
  fontSize: "12px",
};

export function DashboardPage({ navigate, tasks: allTasks, orders: productionOrders, samples: sampleRecords }: { navigate: (path: string) => void; tasks: ProductionTask[]; orders: ProductionOrder[]; samples: SampleRecord[] }) {
  const tasks=allTasks.filter(task=>!task.confirmed && task.progress<100 && !["Done","Completed"].includes(task.stage));
  const [range, setRange] = useState("30 days");
  const [collection, setCollection] = useState("All collections");
  const visibleOrders = useMemo(
    () =>
      collection === "All collections"
        ? productionOrders
        : productionOrders.filter((order) => order.collection === collection),
    [collection, productionOrders],
  );
  const activeOrders = visibleOrders.filter((order) => !["Warehouse Received", "Completed"].includes(order.status));
  const units = visibleOrders.reduce((sum, order) => sum + order.quantity, 0);
  const accepted = visibleOrders.reduce((sum, order) => sum + order.accepted, 0);
  const rejected = visibleOrders.reduce((sum, order) => sum + order.rejected, 0);
  const priorityTask = tasks.find((task) => task.priority === "Critical") ?? tasks[0];

  return (
    <div className="page-stack dashboard-page">
      <PageHeader
        eyebrow="Executive control room"
        title="Production overview"
        description="A live view of what is moving, what needs a decision, and what could miss the drop."
        actions={
          <div className="filter-row">
            <select value={collection} onChange={(event) => setCollection(event.target.value)} aria-label="Filter collection">
              <option>All collections</option>
              {Array.from(new Set(productionOrders.map((order) => order.collection))).map((item) => <option key={item}>{item}</option>)}
            </select>
            <div className="segmented compact-segmented" aria-label="Date range">
              {["7 days", "30 days", "Quarter"].map((item) => (
                <button key={item} className={range === item ? "active" : ""} onClick={() => setRange(item)}>
                  {item}
                </button>
              ))}
            </div>
          </div>
        }
      />

      <div className="stats-grid stats-grid-six">
        <StatCard label="Active orders" value={String(activeOrders.length)} trend={`${visibleOrders.length} tracked`} trendDirection="up" detail={range} icon={<Boxes size={17} />} />
        <StatCard label="Total order quantity" value={units.toLocaleString()} detail="Imported manufacturing tracker" icon={<PackageCheck size={17} />} />
        <StatCard label="Units completed" value={accepted.toLocaleString()} trend={`${Math.round((accepted / Math.max(1, units)) * 100)}%`} trendDirection="up" detail="yield to date" icon={<CheckCircle2 size={17} />} emphasis="green" />
        <StatCard label="Open / waiting" value={String(activeOrders.length)} detail="Orders still open" icon={<AlertTriangle size={17} />} emphasis="yellow" />
        <StatCard label="Rejected units" value={String(rejected)} detail="No rejected quantity recorded" icon={<ShieldAlert size={17} />} emphasis="red" />
        <StatCard label="Costs recorded" value={formatCurrency(activeOrders.reduce((sum, order) => sum + order.targetCost, 0))} detail="Add supplier costs when confirmed" icon={<Banknote size={17} />} />
      </div>

      <div className="dashboard-main-grid">
        <Panel
          className="chart-panel"
          title="Production flow"
          description="Planned versus completed units by week"
          action={<button className="text-button" onClick={() => navigate("/reports")}>Full report <ArrowRight size={14} /></button>}
        >
          <div className="chart-legend"><span><i className="legend-mint" />Completed</span><span><i className="legend-grey" />Planned</span></div>
          <div className="chart-area">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartProductionByWeek} margin={{ top: 12, right: 8, bottom: 0, left: -18 }}>
                <defs>
                  <linearGradient id="completedGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#a8ff60" stopOpacity={0.28} />
                    <stop offset="100%" stopColor="#a8ff60" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#242824" strokeDasharray="3 5" vertical={false} />
                <XAxis dataKey="week" axisLine={false} tickLine={false} tick={{ fill: "#7f887d", fontSize: 11 }} />
                <YAxis axisLine={false} tickLine={false} tick={{ fill: "#7f887d", fontSize: 11 }} />
                <Tooltip contentStyle={tooltipStyle} cursor={{ stroke: "#414841" }} />
                <Area type="monotone" dataKey="planned" stroke="#555d55" strokeWidth={2} fill="transparent" />
                <Area type="monotone" dataKey="completed" stroke="#a8ff60" strokeWidth={2.5} fill="url(#completedGradient)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title="Attention queue" description="Prioritised by operational impact" className="attention-panel">
          <div className="attention-list">
            <button onClick={() => navigate("/problems")}>
              <span className="attention-icon red"><Clock3 size={17} /></span>
              <span><strong>{productionProblems[0].name}</strong><small>{fixtureText("dashboardProblemDetail")}</small></span>
              <Badge tone="red">High</Badge>
            </button>
            <button onClick={() => navigate("/samples")}>
              <span className="attention-icon yellow"><CalendarClock size={17} /></span>
              <span><strong>Samples needing attention</strong><small>{sampleRecords.filter((sample) => !["Done", "Approved"].includes(sample.stage)).length} samples are still in progress</small></span>
              <Badge tone="yellow">Review</Badge>
            </button>
            <button onClick={() => navigate("/production-tasks")}>
              <span className="attention-icon blue"><Banknote size={17} /></span>
              <span><strong>{priorityTask?.name ?? "No open production tasks"}</strong><small>{priorityTask?.nextAction ?? "The task list is clear."}</small></span>
              <Badge tone="blue">{tasks.length} open</Badge>
            </button>
            <button onClick={() => navigate("/production-orders/813")}>
              <span className="attention-icon red"><ShieldAlert size={17} /></span>
              <span><strong>Real Tree T-shirts</strong><small>184 units are waiting to start</small></span>
              <Badge tone="red">Waiting</Badge>
            </button>
          </div>
        </Panel>
      </div>

      <Panel
        title="Live production orders"
        description={`${visibleOrders.length} orders in the selected view`}
        action={<button className="text-button" onClick={() => navigate("/production-orders")}>View all orders <ArrowRight size={14} /></button>}
      >
        <TableWrap>
          <table>
            <thead>
              <tr><th>Order</th><th>Product</th><th>Current stage</th><th>Progress</th><th>Delivery</th><th>Status</th></tr>
            </thead>
            <tbody>
              {visibleOrders.slice(0, 5).map((order) => (
                <tr key={order.code} className="clickable-row" onClick={() => navigate(`/production-orders/${order.code}`)}>
                  <td><strong className="mono-cell">{order.code}</strong><small>{order.collection}</small></td>
                  <td><strong>{order.product}</strong><small>{order.color} · {order.quantity} units</small></td>
                  <td>{order.currentStage}<small>{order.supplier}</small></td>
                  <td className="progress-cell"><div><ProgressBar value={order.progress} tone={order.status === "Delayed" || order.status === "Blocked" ? "red" : order.status === "At Risk" ? "yellow" : "green"} /><span>{order.progress}%</span></div></td>
                  <td>{order.forecastDelivery}<small className={order.delayDays ? "danger-text" : "muted-text"}>{order.delayDays ? `${order.delayDays} days late` : "On schedule"}</small></td>
                  <td><Badge>{order.status}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      </Panel>

      <div className="dashboard-lower-grid">
        <Panel title="Supplier performance" description="On-time delivery and quality score">
          <div className="bar-chart-area">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartSupplierPerformance} margin={{ top: 8, right: 2, bottom: 0, left: -24 }}>
                <CartesianGrid stroke="#242824" strokeDasharray="3 5" vertical={false} />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: "#7f887d", fontSize: 11 }} />
                <YAxis domain={[0, 100]} axisLine={false} tickLine={false} tick={{ fill: "#7f887d", fontSize: 11 }} />
                <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "#1d211d" }} />
                <Bar dataKey="onTime" fill="#a8ff60" radius={[4, 4, 0, 0]} barSize={16} />
                <Bar dataKey="quality" fill="#596259" radius={[4, 4, 0, 0]} barSize={16} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
        <Panel title="Recent quality issues" description="Inspections requiring follow-up" action={<button className="text-button" onClick={() => navigate("/quality-control")}>Open QC <ArrowRight size={14} /></button>}>
          <div className="compact-list">
            {qcInspections.filter((inspection) => inspection.result !== "Pass").slice(0, 3).map((inspection) => (
              <button key={inspection.number} onClick={() => navigate("/quality-control")}>
                <span><strong>{inspection.order}</strong><small>{inspection.supplier} · {inspection.type}</small></span>
                <span className="list-value"><Badge>{inspection.result}</Badge><small>{inspection.defectRate}% defects</small></span>
              </button>
            ))}
          </div>
        </Panel>
        <Panel title="Recent updates" description="Latest activity from suppliers and HBA">
          <div className="feed-list">
            {notifications.slice(0, 3).map((item) => (
              <button key={item.id} onClick={() => navigate("/notifications")}>
                <i className={`feed-dot feed-${item.severity}`} />
                <span><strong>{item.title}</strong><small>{item.detail}</small></span>
                <time>{item.time}</time>
              </button>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
