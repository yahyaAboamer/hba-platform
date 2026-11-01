import { can } from "../lib/api";
import type { Session } from "../lib/api";
import { affiliates } from "./affiliates/department";
import { inbox } from "./inbox/department";
import { operations } from "./operations/department";
import type { Department } from "./types";

/**
 * Every department, in the order the sidebar draws them (Today sits above
 * them for anyone holding two or more). A person's departments are the ones whose `holds` they hold.
 */
export const DEPARTMENTS: readonly Department[] = [inbox, operations, affiliates];

/**
 * The departments a person sees: whole when they hold the department's
 * permission; otherwise with just the sections whose own permission they
 * hold, marked `partial` (ADR 0072); otherwise not at all.
 */
export function departmentsFor(session: Session): Department[] {
  return DEPARTMENTS.flatMap((department) => {
    if (can(session, department.holds)) return [department];
    const sections = department.sections.filter((section) => section.holds && can(session, section.holds));
    return sections.length ? [{ ...department, sections, partial: true }] : [];
  });
}

/** Whether a section of a department is this person's to see. */
export function seesSection(session: Session, department: Department, slug: string): boolean {
  return (departmentsFor(session).find((held) => held.key === department.key)?.sections ?? []).some(
    (section) => section.slug === slug,
  );
}

/** Who starts where when they hold just one department, widest first. */
const START_ORDER: readonly Department["key"][] = ["affiliates", "operations", "inbox"];

/**
 * The address a person starts on: Today when they hold two or more
 * departments, otherwise their one department's first section.
 */
export function startFor(session: Session): string {
  const held = departmentsFor(session);
  // A department seen only in part does not count towards Today (ADR 0072).
  if (held.filter((department) => !department.partial).length >= 2) return "/today";
  for (const partial of [false, true]) {
    for (const key of START_ORDER) {
      const found = held.find((department) => department.key === key && !!department.partial === partial);
      if (found) return found.sections[0].to;
    }
  }
  return "/";
}
