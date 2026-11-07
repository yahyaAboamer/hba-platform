/**
 * What `GET /api/staff` answers (Batch 2.4 contract §3), with the permissions
 * copied from `app/core/permissions.py` `ROLES` as of this batch - note that
 * `content_manager` holds `invitations.send` (ADR 0073).
 */
export const ALL = [
  "affiliates.view", "affiliates.manage", "affiliates.erase", "compensation.manage",
  "targets.record", "targets.manage", "targets.verify", "payroll.approve", "payroll.reopen",
  "payments.record", "payroll.bonus", "invitations.send", "audit.view", "settings.manage",
  "order_ops.view", "inbox.use", "khazenly.use",
  "production.view", "production.edit", "production.qc", "production.suppliers", "production.payments",
];

export const ROLE_PERMISSIONS: Record<string, string[]> = {
  admin: ALL,
  affiliate_manager: [
    "affiliates.view", "affiliates.manage", "compensation.manage", "targets.manage", "targets.verify",
    "targets.record", "payroll.approve", "payroll.bonus", "invitations.send", "audit.view",
  ],
  content_manager: [
    "affiliates.view", "affiliates.manage", "compensation.manage", "targets.record", "targets.manage",
    "targets.verify", "invitations.send", "audit.view",
  ],
  operations_manager: ["order_ops.view", "khazenly.use"],
  customer_service: ["inbox.use", "khazenly.use"],
  production_viewer: ["production.view"],
  production_staff: ["production.view", "production.edit", "production.qc"],
  production_manager: ["production.view", "production.edit", "production.qc", "production.suppliers"],
};

export const ROLE_WORDS: Record<string, string> = {
  admin: "Owner",
  operations_manager: "Operations manager",
  customer_service: "Inbox staff",
  affiliate_manager: "Affiliates manager",
  content_manager: "Affiliates staff",
  production_manager: "Production manager",
  production_staff: "Production staff",
  production_viewer: "Production viewer",
};

const level = (name: string, role: string | null, offered: boolean) => ({ level: name, role, offered });

export const DEPARTMENTS = [
  { key: "inbox", name: "Inbox", levels: [
    level("none", null, true), level("viewer", null, false), level("staff", "customer_service", true), level("manager", null, false)] },
  { key: "operations", name: "Operations", levels: [
    level("none", null, true), level("viewer", null, false), level("staff", null, false), level("manager", "operations_manager", true)] },
  { key: "affiliates", name: "Affiliates", levels: [
    level("none", null, true), level("viewer", null, false), level("staff", "content_manager", true), level("manager", "affiliate_manager", true)] },
  { key: "production", name: "Production", levels: [
    level("none", null, true), level("viewer", "production_viewer", true),
    level("staff", "production_staff", true), level("manager", "production_manager", true)] },
];

export function person(id: number, name: string, roles: string[], access: Record<string, string>, extra: object = {}) {
  return {
    id, email: `${name.toLowerCase()}@hbawear.store`, display_name: name, roles, status: "active",
    two_step_enabled: false, two_step_method: null, last_login_at: null,
    created_at: "2026-09-03T10:00:00Z", joined_at: "2026-09-03T10:00:00Z",
    owner: roles.includes("admin"), access,
    access_words: roles.map((role) => ROLE_WORDS[role]).join(" · ") || "No access",
    ...extra,
  };
}

export const NONE = { inbox: "none", operations: "none", affiliates: "none", production: "none" };

export function roster(overrides: object = {}) {
  return {
    staff: [
      person(1, "Yahya", ["admin"], NONE, { two_step_enabled: true, two_step_method: "authenticator" }),
      person(2, "Mona", ["customer_service"], { ...NONE, inbox: "staff" }),
      person(3, "Dina", ["affiliate_manager", "customer_service"], { ...NONE, inbox: "staff", affiliates: "manager" },
        { two_step_enabled: true, two_step_method: "email" }),
    ],
    invitations: [
      { id: 11, email: "hassan@hbawear.store", role: "customer_service", access_words: "Inbox staff",
        sent_at: new Date().toISOString(), created_at: new Date().toISOString(),
        expires_at: "2099-01-01T00:00:00Z", expired: false },
    ],
    assignable_roles: Object.keys(ROLE_PERMISSIONS),
    invitable_roles: Object.keys(ROLE_PERMISSIONS),
    role_permissions: ROLE_PERMISSIONS,
    role_words: ROLE_WORDS,
    departments: DEPARTMENTS,
    ...overrides,
  };
}
