export type HealthStatus =
  | "Completed"
  | "On Track"
  | "At Risk"
  | "Delayed"
  | "Blocked"
  | "Pending Approval"
  | "Not Started"
  | "Waiting"
  | "In Progress"
  | "Waiting for QC"
  | "Rework"
  | "Warehouse Received";

export type ProductionStage = {
  id: string;
  name: string;
  shortName: string;
  status: HealthStatus;
  supplier: string;
  planned: string;
  forecast: string;
  actual?: string;
  quantity: number;
  accepted: number;
  rejected: number;
  progress: number;
  notes: string;
};

export type DropPhase = {id:string; name:string};

export type ProductionOrder = {
  trackerOrderNumber?: number;
  trackerModel?: string;
  fabric?: string;
  fabricKg?: number | null;
  legacyCode?: string;
  phaseId?: string;
  phaseName?: string;
  id: string;
  code: string;
  product: string;
  style: string;
  collection: string;
  color: string;
  quantity: number;
  accepted: number;
  rejected: number;
  progress: number;
  currentStage: string;
  status: HealthStatus;
  manager: string;
  supplier: string;
  startDate: string;
  startDateISO?: string;
  plannedDelivery: string;
  plannedDeliveryISO?: string;
  forecastDelivery: string;
  forecastDeliveryISO?: string;
  delayDays: number;
  priority: "Critical" | "High" | "Normal" | "Low";
  targetCost: number;
  actualCost: number;
  notes?: string;
  sizeBreakdown: Record<string, number>;
  stages: ProductionStage[];
};

export type Supplier = {
  code: string;
  name: string;
  category: string;
  contact: string;
  city: string;
  phone: string;
  activeOrders: number;
  onTime: number;
  defectRate: number;
  rating: number;
  capacity: string;
  leadTime: string;
  paymentTerms: string;
  status: "Active" | "Review" | "Inactive";
};

export type ProductionTask = {
  confirmed?: boolean;
  confirmedAt?: string;
  confirmedBy?: string;
  id: string;
  name: string;
  supplier: string;
  supplierType: string;
  stage: string;
  nextAction: string;
  owner: string;
  actionDate: string;
  deadline: string;
  progress: number;
  priority: "Critical" | "High" | "Normal" | "Low";
};

export type SampleRecord = {
  photoCount?: number;
  photoUrl?: string;
  id: string;
  name: string;
  material?: string;
  priority: "Critical" | "Urgent" | "High" | "Normal" | "Low";
  progress: number;
  updates: number;
  stage: "Done" | "Approved" | "In Progress" | "Revision Requested" | "On Hold" | "Rejected";
  latestProgress: string;
  updatedAt: string;
  nextStep: string;
  deadline: string;
  owner: string;
  supplier: string;
  approvedBy?: string;
  approvalDate?: string;
  manufacturingNotes?: string;
};

export type ProductionProblem = {
  id: string;
  name: string;
  category: string;
  supplier: string;
  description: string;
  severity: "Critical" | "High" | "Medium" | "Low";
  owner: string;
  nextReview: string;
  immediateControl: string;
  solutions: string[];
  dueDate: string;
  status: "Open" | "Action Required" | "In Progress" | "Monitoring" | "Resolved";
};

// ── The fixed content (ADR 0076, decision 3) ─────────────────────────────────
//
// These lists used to be written out here, and some of them name people. They
// now live in the database (`production_fixture`) and are poured into these
// same arrays by `applyFixtures`, which `src/main.tsx` runs before the first
// screen draws - so every screen reads them exactly as it always did, and no
// name is committed to the repository.

export type CatalogProduct = { style: string; name: string; category: string; collection: string; variants: number; gsm: number; targetCost: number; status: string };
export type Material = { code: string; name: string; category: string; supplier: string; uom: string; stock: number; reserved: number; reorder: number; unitCost: number; status: string };
export type QcInspection = { number: string; order: string; type: string; supplier: string; inspected: number; accepted: number; rejected: number; defectRate: number; result: string; inspector: string; date: string };
export type NotificationItem = { id: string; title: string; detail: string; time: string; severity: string; read: boolean };
export type ActivityItem = { user: string; action: string; module: string; record: string; old: string; next: string; time: string };
export type RouteTemplate = { name: string; products: number; stages: number; leadTime: number; updated: string; status: string };

export const washedPantsStages: ProductionStage[] = [];
export const productionOrders: ProductionOrder[] = [];
export const suppliers: Supplier[] = [];
export const products: CatalogProduct[] = [];
export const productionTasks: ProductionTask[] = [];
export const sampleRecords: SampleRecord[] = [];
export const productionProblems: ProductionProblem[] = [];
export const materials: Material[] = [];
export const bomItems: Array<{ material: string; supplier: string; consumption: number; uom: string; wastage: number; required: number; unitCost: number; total: number }> = [];
export const qcInspections: QcInspection[] = [];
export const costLines: Array<{ category: string; supplier: string; planned: number; actual: number; variance: number; status: string }> = [];
export const payments: Array<{ invoice: string; supplier: string; order: string; amount: number; paid: number; due: string; status: string; approval: string }> = [];
export const notifications: NotificationItem[] = [];
export const activityLog: ActivityItem[] = [];
export const chartProductionByWeek: Array<{ week: string; planned: number; completed: number }> = [];
export const chartSupplierPerformance: Array<{ name: string; onTime: number; quality: number }> = [];
export const routeTemplates: RouteTemplate[] = [];
export const documents: Array<{ name: string; type: string; related: string; owner: string; updated: string; size: string }> = [];

const lists: Record<string, unknown[]> = {
  washedPantsStages, productionOrders, suppliers, products, productionTasks, sampleRecords,
  productionProblems, materials, bomItems, qcInspections, costLines, payments, notifications,
  activityLog, chartProductionByWeek, chartSupplierPerformance, routeTemplates, documents,
};

/** The names of the lists, for the server's import and its tests. */
export const fixtureListNames = Object.keys(lists);

/** Fills each list in place from the fixed content the server sends. */
export function applyFixtures(data: Record<string, unknown>) {
  for (const [name, target] of Object.entries(lists)) {
    const source = data[name];
    target.splice(0, target.length, ...(Array.isArray(source) ? source : []));
  }
}
