import type { Department, DepartmentSection } from "../departments/types";
import { can } from "../lib/api";
import type { Session } from "../lib/api";

/**
 * Settings is not a department in Batch 2.1: a link at the foot of the
 * sidebar, for whoever can open it today (whoever holds `affiliates.view`).
 * The glossary stays, inside the frame, and counts as Settings for "where am
 * I".
 */
export const SETTINGS_BASES = ["/settings", "/glossary"] as const;

export function canOpenSettings(session: Session | null): boolean {
  return can(session, "affiliates.view");
}

/** Whether an address is `base` or somewhere under it. */
export function within(pathname: string, base: string): boolean {
  return pathname === base || pathname.startsWith(`${base}/`);
}

export type Where = {
  department: Department | null;
  section: DepartmentSection | null;
  settings: boolean;
};

/**
 * Where a person is standing, from the address alone: the department whose
 * base holds it, the section it shows as current (a page off the sidebar
 * shows its parent), or Settings.
 */
export function whereAmI(pathname: string, departments: readonly Department[]): Where {
  if (SETTINGS_BASES.some((base) => within(pathname, base))) {
    return { department: null, section: null, settings: true };
  }
  const department = departments.find((candidate) => within(pathname, candidate.base)) ?? null;
  const section =
    department?.sections.find(
      (candidate) =>
        within(pathname, candidate.to) || candidate.also?.some((also) => within(pathname, also)),
    ) ?? null;
  return { department, section, settings: false };
}
