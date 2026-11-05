/**
 * Team and access, the parts that are words and arithmetic rather than
 * screens (Batch 2.4 contract §3 and §5). Kept apart so a test can walk every
 * permission the server knows and see that each has a phrase.
 */
import { roleWords } from "../../lib/api";

export type Level = "none" | "viewer" | "staff" | "manager";

export const LEVEL_WORDS: Record<Level, string> = {
  none: "No access",
  viewer: "Viewer",
  staff: "Staff",
  manager: "Manager",
};

export const LEVELS: Level[] = ["none", "viewer", "staff", "manager"];

export type DepartmentLevel = { level: Level; role: string | null; offered: boolean };
export type Department = { key: string; name: string; levels: DepartmentLevel[] };

/** One phrase per permission the server can grant (`app/core/permissions.py`). */
export const PERMISSION_PHRASE: Record<string, string> = {
  "affiliates.view": "looking up models by name or code",
  "affiliates.manage": "adding and editing models",
  "affiliates.erase": "erasing a model outright",
  "compensation.manage": "setting models' pay terms",
  "targets.record": "recording what was published",
  "targets.manage": "setting content targets",
  "targets.verify": "confirming targets were met",
  "payroll.approve": "approving a month's pay",
  "payroll.reopen": "reopening approved months",
  "payments.record": "recording payments",
  "payroll.bonus": "adding and withdrawing bonuses",
  "invitations.send": "inviting models",
  "audit.view": "reading the activity log",
  "settings.manage": "changing settings and everyone's access",
  "order_ops.view": "seeing the Operations dashboard",
  "inbox.use": "reading and replying to customers",
  "khazenly.use": "building the Khazenly confirmation file",
};

/** What a person is told they do *not* get; each is said only when none of its permissions is held. */
export const NOT_GIVEN: [string, string[]][] = [
  ["no Operations dashboard", ["order_ops.view"]],
  ["no pay figures", ["compensation.manage"]],
  ["no payroll or payments", ["payroll.approve", "payments.record"]],
  ["no way to change a model", ["affiliates.manage"]],
  ["no access to Settings", ["settings.manage"]],
];

/** Everything a set of roles grants together, as the server reads it. */
export function grantedBy(roles: string[], rolePermissions: Record<string, string[]> | undefined): string[] {
  return [...new Set(roles.flatMap((role) => rolePermissions?.[role] ?? []))];
}

function joinWords(parts: string[]): string {
  if (parts.length <= 1) return parts[0] ?? "";
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

/**
 * *What this gives {first name}*: the permissions their roles grant together,
 * one phrase each, then what they do not get. Frame 5's sentence.
 */
export function givesSentence(
  first: string,
  roles: string[],
  rolePermissions: Record<string, string[]> | undefined,
): string {
  if (roles.includes("admin")) return `${first} is the owner: every department, Settings and money.`;
  const held = grantedBy(roles, rolePermissions);
  const phrases = Object.keys(PERMISSION_PHRASE).filter((permission) => held.includes(permission))
    .map((permission) => PERMISSION_PHRASE[permission]);
  if (phrases.length === 0) return `${first} has no access to any department.`;
  const no = NOT_GIVEN.filter(([, permissions]) => !permissions.some((permission) => held.includes(permission)))
    .map(([words]) => words);
  const said = joinWords(no);
  const refused = said ? ` ${said.charAt(0).toUpperCase()}${said.slice(1)}.` : "";
  return `${joinWords(phrases)}.${refused}`;
}

/**
 * Lines a role earns, for the confirmation: a line is held when every
 * permission it names is held (read from the server's own role list).
 */
export const ACCESS_LINES: [string, string[]][] = [
  ["See and edit models, and set their pay terms", ["affiliates.manage", "compensation.manage"]],
  ["Set, record and confirm content targets", ["targets.manage", "targets.record", "targets.verify"]],
  ["Read the activity log", ["audit.view"]],
  ["Approve a month's pay", ["payroll.approve"]],
  ["See the operations dashboard", ["order_ops.view"]],
  ["Read and answer customers in the inbox", ["inbox.use"]],
  ["Build the Khazenly confirmation file", ["khazenly.use"]],
  ["Invite models", ["invitations.send"]],
  ["Record payments and reopen approved months", ["payments.record", "payroll.reopen"]],
  ["Invite staff and change anyone's access, Shopify and the pay policy; erase a model", ["settings.manage", "affiliates.erase"]],
];

export function holds(permissions: string[] | undefined, line: string[]) {
  return !!permissions && line.every((permission) => permissions.includes(permission));
}

/** The short line beside a department's level, as frame 5 has it. */
export const ROLE_BLURB: Record<string, string> = {
  customer_service: "Reads and replies to customers",
  operations_manager: "Sees the Operations dashboard",
  content_manager: "Looks up models, records targets and sets pay terms",
  affiliate_manager: "Runs models and targets, and approves pay",
};

/** *Inbox staff · Affiliates manager*, from the roles when the server sent no words. */
export function accessWordsOf(roles: string[]): string {
  if (roles.includes("admin")) return "Owner";
  return roles.map(roleWords).join(" · ") || "No access";
}

/** The level a person holds in a department: the highest whose role they hold. */
export function levelIn(department: Department, roles: string[]): Level {
  for (const level of ["manager", "staff", "viewer"] as Level[]) {
    const entry = department.levels.find((candidate) => candidate.level === level);
    if (entry?.role && roles.includes(entry.role)) return level;
  }
  return "none";
}

export function roleOf(department: Department, level: Level): string | null {
  return department.levels.find((candidate) => candidate.level === level)?.role ?? null;
}

export function rolesOfDepartment(department: Department): string[] {
  return department.levels.flatMap((entry) => (entry.role ? [entry.role] : []));
}

/** Several roles in words: *Inbox staff and Affiliates manager*. */
export function rolesWords(roles: string[], words: (role: string) => string = roleWords): string {
  return joinWords(roles.map(words));
}
