import { can } from "../lib/api";
import type { Session } from "../lib/api";
import { affiliates } from "./affiliates/department";
import { inbox } from "./inbox/department";
import { operations } from "./operations/department";
import type { Department } from "./types";

/**
 * Every department, in the order the sidebar draws them (Today joins first in
 * Batch 2.2). A person's departments are the ones whose `holds` they hold.
 */
export const DEPARTMENTS: readonly Department[] = [inbox, operations, affiliates];

export function departmentsFor(session: Session): Department[] {
  return DEPARTMENTS.filter((department) => can(session, department.holds));
}

/** Who gets which start first, until Today replaces this (Batch 2.2). */
const START_ORDER: readonly Department["key"][] = ["affiliates", "operations", "inbox"];

/** The address a person starts on: their widest department's first section. */
export function startFor(session: Session): string {
  for (const key of START_ORDER) {
    const found = DEPARTMENTS.find((department) => department.key === key);
    if (found && can(session, found.holds)) return found.sections[0].to;
  }
  return "/";
}
