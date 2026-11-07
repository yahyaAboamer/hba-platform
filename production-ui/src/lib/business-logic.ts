import { differenceInCalendarDays, parseISO, startOfDay } from "date-fns";

export type QuantityBreakdown = Record<string, number>;

export type StageProgressInput = {
  progress: number;
  weight?: number;
};

export function sumBreakdown(breakdown: QuantityBreakdown): number {
  return Object.values(breakdown).reduce((total, quantity) => total + quantity, 0);
}

export function isBreakdownValid(
  breakdown: QuantityBreakdown,
  totalQuantity: number,
): boolean {
  return (
    totalQuantity >= 0 &&
    Object.values(breakdown).every((quantity) => Number.isInteger(quantity) && quantity >= 0) &&
    sumBreakdown(breakdown) === totalQuantity
  );
}

export function calculateRequiredMaterial(
  productionQuantity: number,
  consumptionPerUnit: number,
  wastagePercentage: number,
): number {
  if (productionQuantity < 0 || consumptionPerUnit < 0 || wastagePercentage < 0) {
    throw new Error("Material inputs cannot be negative");
  }

  return productionQuantity * consumptionPerUnit * (1 + wastagePercentage / 100);
}

export function calculateDelayDays(
  forecastFinish: string,
  plannedFinish: string,
): number {
  const forecast = startOfDay(parseISO(forecastFinish));
  const planned = startOfDay(parseISO(plannedFinish));
  return Math.max(0, differenceInCalendarDays(forecast, planned));
}

export function calculateProgress(stages: StageProgressInput[]): number {
  if (stages.length === 0) return 0;

  const totalWeight = stages.reduce((sum, stage) => sum + (stage.weight ?? 1), 0);
  if (totalWeight === 0) return 0;

  const weightedProgress = stages.reduce(
    (sum, stage) => sum + Math.min(100, Math.max(0, stage.progress)) * (stage.weight ?? 1),
    0,
  );

  return Math.round(weightedProgress / totalWeight);
}

export function calculateActualUnitCost(
  actualProductionCost: number,
  finalAcceptedQuantity: number,
): number {
  if (finalAcceptedQuantity <= 0) return 0;
  return actualProductionCost / finalAcceptedQuantity;
}

export function calculateDefectRate(
  rejectedQuantity: number,
  inspectedQuantity: number,
): number {
  if (inspectedQuantity <= 0) return 0;
  return (rejectedQuantity / inspectedQuantity) * 100;
}

export function calculateReworkPercentage(
  reworkQuantity: number,
  inspectedQuantity: number,
): number {
  if (inspectedQuantity <= 0) return 0;
  return (reworkQuantity / inspectedQuantity) * 100;
}

export function calculateRemainingQuantity(
  inputQuantity: number,
  completedQuantity: number,
): number {
  return Math.max(0, inputQuantity - completedQuantity);
}

export function formatCurrency(amount: number, currency = "EGP"): string {
  return new Intl.NumberFormat("en-EG", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(amount);
}

export function generateDailyCode(
  prefix: string,
  sequence: number,
  date = new Date(),
): string {
  const year = String(date.getFullYear()).slice(-2);
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${prefix}-${year}${month}${day}-${String(sequence).padStart(3, "0")}`;
}

export function canTransitionOrderStatus(from: string, to: string): boolean {
  const transitions: Record<string, string[]> = {
    Draft: ["Pending Approval", "Cancelled"],
    "Pending Approval": ["Approved", "Draft", "Cancelled"],
    Approved: ["Not Started", "In Progress", "Cancelled"],
    "Not Started": ["Waiting", "In Progress", "Blocked", "Cancelled"],
    Waiting: ["Not Started", "In Progress", "Blocked", "Cancelled"],
    "In Progress": ["At Risk", "Delayed", "Blocked", "Waiting for QC", "Partially Completed"],
    "At Risk": ["In Progress", "Delayed", "Blocked", "Waiting for QC"],
    Delayed: ["In Progress", "Blocked", "Waiting for QC"],
    Blocked: ["In Progress", "Cancelled"],
    "Waiting for QC": ["Rework", "Completed"],
    Rework: ["In Progress", "Waiting for QC"],
    "Partially Completed": ["In Progress", "Waiting for QC", "Completed"],
    Completed: ["Warehouse Received"],
    "Warehouse Received": [],
    Cancelled: [],
  };

  return transitions[from]?.includes(to) ?? false;
}
