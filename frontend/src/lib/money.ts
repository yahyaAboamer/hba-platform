/**
 * Rendering money, and saying whether it is real.
 *
 * ADR 0002: money is integer piastres everywhere, never a float. That holds on
 * this side of the wire too — a figure arrives as an integer and is formatted
 * for display only. Nothing here is ever used to calculate anything.
 *
 * ADR 0027: the typeface says whether a figure is an obligation. That decision
 * lives in `moneyClass` rather than in each screen, so twenty screens cannot
 * drift apart on the one distinction the platform is built around.
 */

const PIASTRES_PER_POUND = 100;

/**
 * `E£1,062.00`.
 *
 * Always two decimals, even on a whole figure. A column where some rows show
 * pounds and others show pounds-and-piastres is a column nobody can scan, and
 * scanning is what this screen is for.
 */
export function formatEgp(piastres: number): string {
  const negative = piastres < 0;
  const whole = Math.trunc(Math.abs(piastres) / PIASTRES_PER_POUND);
  const fraction = Math.abs(piastres) % PIASTRES_PER_POUND;
  const grouped = whole.toLocaleString("en-GB");
  return `${negative ? "−" : ""}E£${grouped}.${String(fraction).padStart(2, "0")}`;
}

/** What a figure is, which decides how it is set. */
export type MoneyKind =
  /** Calculated now, and free to change. Set in the prose face. */
  | "provisional"
  /** Frozen in an approved snapshot. Set in the mono face. */
  | "agreed"
  /** Cannot be approved yet, so it is not owed. */
  | "blocked";

export type MoneyTone = "neutral" | "owed" | "settled";

/**
 * The class list for a figure. ADR 0027.
 *
 * A face change is categorical where colour or weight is a matter of degree.
 * Somebody scanning twenty rows at month end is asking a yes-or-no question —
 * *can I pay this?* — and the answer should arrive before they read the digits.
 */
export function moneyClass(
  kind: MoneyKind,
  tone: MoneyTone = "neutral",
  piastres?: number,
): string {
  const classes = ["money"];
  if (kind === "agreed") classes.push("money--agreed");
  if (kind === "blocked") classes.push("money--blocked");
  if (tone === "owed") classes.push("money--owed");
  if (tone === "settled") classes.push("money--settled");
  // Nothing owed is not the same as a small amount owed, and it should not
  // draw the eye at all.
  if (piastres === 0) classes.push("money--zero");
  return classes.join(" ");
}

/**
 * A blocker key turned into something a person can act on.
 *
 * The platform's own messages are already written for people, but these arrive
 * as identifiers in a list. Each one says **what is missing**, because §11.3
 * blocks on missing information and never on poor performance — and a person
 * reading "blocked" with no reason will assume the worse of the two.
 */
const BLOCKER_TEXT: Record<string, string> = {
  no_compensation_terms_for_this_month: "No pay terms for this month",
  no_target_recorded_for_this_month: "No target recorded",
  targets_achieved_but_not_verified: "Targets met, not yet verified",
  orders_held_for_multi_code_review: "An order two models both claim",
  house_accounts_are_never_owed: "House account — never owed",
  month_predates_the_platform: "Settled before the platform",
  month_is_already_approved: "Already approved",
  go_live_month_is_not_configured: "Go-live month is not set",
};

export function describeBlocker(key: string): string {
  return BLOCKER_TEXT[key] ?? key.replace(/_/g, " ");
}

/**
 * `2026-08` → `August 2026`.
 *
 * Months are stored and sent as `YYYY-MM` (ADR 0005, derived in Cairo). They
 * are written out in full wherever there is room, because "2026-08" and
 * "2026-09" differ by one character at a glance and they are different
 * payrolls.
 */
const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

export function formatMonth(month: string): string {
  const [year, index] = month.split("-");
  const name = MONTH_NAMES[Number(index) - 1];
  return name ? `${name} ${year}` : month;
}

export function shortMonth(month: string): string {
  const [, index] = month.split("-");
  return MONTH_NAMES[Number(index) - 1]?.slice(0, 3) ?? month;
}

/** The month before this one, staying inside `YYYY-MM`. */
export function monthAdd(month: string, delta: number): string {
  const [year, index] = month.split("-").map(Number);
  const zeroBased = year * 12 + (index - 1) + delta;
  return `${Math.floor(zeroBased / 12)}-${String((zeroBased % 12) + 1).padStart(2, "0")}`;
}

/** Today's business month, in Cairo. The month decides which payroll an order belongs to. */
export function currentMonth(): string {
  const cairo = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Africa/Cairo",
    year: "numeric",
    month: "2-digit",
  }).format(new Date());
  return cairo.slice(0, 7);
}
