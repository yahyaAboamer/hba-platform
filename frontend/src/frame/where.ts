import type { Department, DepartmentSection } from "../departments/types";
import { can } from "../lib/api";
import type { Session } from "../lib/api";

/**
 * Settings is not a department: a link at the foot of the sidebar, for every
 * member of staff (Batch 2.3). The glossary stays, inside the frame, and
 * counts as Settings for "where am I".
 */
export const SETTINGS_BASES = ["/settings", "/glossary"] as const;

/** Today's address: a page of its own, for anyone who holds two or more departments. */
export const TODAY = "/today";

/** Whether Today exists for this person: they hold two or more departments. */
export function holdsToday(departments: readonly Department[]): boolean {
  // A department seen only in part (one section, ADR 0072) does not count.
  return departments.filter((department) => !department.partial).length >= 2;
}

/** Every member of staff has *Me*; a model, who holds no permission, has no Settings. */
export function canOpenSettings(session: Session | null): boolean {
  return (session?.permissions.length ?? 0) > 0;
}

/** The owner's: whoever holds `settings.manage`. */
export function isOwner(session: Session | null): boolean {
  return can(session, "settings.manage");
}

/** The Settings pages only the owner opens; everything else under Settings is for any member of staff. */
export const OWNER_SETTINGS = ["/settings/team", "/settings/integrations", "/settings/company"] as const;

/** Settings' sections as the sidebar draws them: *Me* for everyone, the rest the owner's. */
export const SETTINGS_SECTIONS = [
  { label: "Me", to: "/settings/me", owner: false },
  { label: "Team and access", to: "/settings/team", owner: true },
  { label: "Integrations", to: "/settings/integrations", owner: true },
  { label: "Company", to: "/settings/company", owner: true },
] as const;

/**
 * Pages in Affiliates that are off the sidebar and held by a permission of
 * their own, not the department's (Batch 2.3). `Elsewhere` says so rather
 * than "Nothing here" to somebody who holds Affiliates but not the page.
 */
export const AFFILIATES_PAGES = [
  { to: "/affiliates/brand-codes", holds: "affiliates.view" },
  { to: "/affiliates/historical", holds: "compensation.manage" },
  { to: "/affiliates/activity", holds: "audit.view" },
] as const;

/** Whether an address is `base` or somewhere under it. */
export function within(pathname: string, base: string): boolean {
  return pathname === base || pathname.startsWith(`${base}/`);
}

export type Where = {
  department: Department | null;
  section: DepartmentSection | null;
  settings: boolean;
  /** On Today, which belongs to no department. */
  today: boolean;
};

/**
 * Where a person is standing, from the address alone: the department whose
 * base holds it, the section it shows as current (a page off the sidebar
 * shows its parent), or Settings.
 */
export function whereAmI(pathname: string, departments: readonly Department[]): Where {
  if (SETTINGS_BASES.some((base) => within(pathname, base))) {
    return { department: null, section: null, settings: true, today: false };
  }
  if (within(pathname, TODAY)) return { department: null, section: null, settings: false, today: true };
  const department = departments.find((candidate) => within(pathname, candidate.base)) ?? null;
  const section =
    department?.sections.find(
      (candidate) =>
        within(pathname, candidate.to) || candidate.also?.some((also) => within(pathname, also)),
    ) ?? null;
  return { department, section, settings: false, today: false };
}
