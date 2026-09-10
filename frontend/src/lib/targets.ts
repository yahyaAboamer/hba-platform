import type { MonthTargets } from "./portal";

/**
 * What a model is told about one month of targets.
 *
 * Pure functions, in `lib/` and not inside the screen, because the rules they
 * encode are the kind that get quietly re-decided by whoever next edits the
 * markup — and two of them are the difference between telling somebody she
 * missed her targets and telling her nobody has counted them yet.
 *
 * Every one of them is exhaustively tested in `__tests__/targets.test.ts`.
 */

/**
 * The chip beside a month, if anything needs saying.
 *
 * One at most, and only where the numbers beside it do not already say it. A
 * model who met her targets can see so from the figures; what she cannot see
 * is whether anybody has confirmed them.
 *
 * **`achieved === null` is "not recorded", never "short".** §11.3: it is the
 * state that blocks a guaranteed minimum, and calling it a miss tells her the
 * month is lost when it is merely waiting.
 */
export function targetChip(
  target: Pick<MonthTargets, "achieved" | "verified" | "determines_pay">,
): { text: string; className: string } | null {
  if (target.achieved === null) {
    return { text: "Not recorded yet", className: "chip chip--quiet" };
  }
  if (!target.achieved) {
    return { text: "Short this month", className: "chip chip--quiet" };
  }
  if (target.determines_pay && !target.verified) {
    return { text: "Waiting to be confirmed", className: "chip" };
  }
  return { text: "Met", className: "chip chip--ok" };
}

/**
 * The two figures for a past month, or an honest gap.
 *
 * `not kept` where the month predates the platform (ADR 0036) and `—` where
 * nothing has been counted. Neither is a zero: a zero is a claim about her
 * work, and in the first case it would be a fabricated one.
 */
export function targetCounts(
  row: Pick<
    MonthTargets,
    | "numbers_kept"
    | "actual_videos"
    | "actual_stories"
    | "required_videos"
    | "required_stories"
  >,
): string {
  if (row.numbers_kept === false) return "not kept";
  if (row.actual_videos === null && row.actual_stories === null) return "—";
  const asked = (n: number | null) => (n ? ` of ${n}` : "");
  return (
    `${row.actual_videos ?? 0}${asked(row.required_videos)} video, ` +
    `${row.actual_stories ?? 0}${asked(row.required_stories)} story`
  );
}

/**
 * How a past month ended, in three words at most.
 *
 * *not recorded* rather than *short* where nobody counted, and the unconfirmed
 * case is worth a word only where it holds money up — on commission, whether
 * HBA has countersigned a number is their paperwork and not her business.
 */
export function targetOutcome(
  row: Pick<MonthTargets, "achieved" | "verified" | "determines_pay">,
): string {
  if (row.achieved === null) return "not recorded";
  if (!row.achieved) return "short";
  if (row.determines_pay && !row.verified) return "met — to confirm";
  return "met";
}

/**
 * What this month's targets do to her pay.
 *
 * §15 splits on one thing: a target decides money **only** on a guaranteed
 * minimum. On commission or salary-plus-commission it is a record, and a model
 * who reads a missed target as money gone has been told something untrue by a
 * screen that could not tell the two apart.
 *
 * Where it does decide money, the missed case is the one to be careful with.
 * It costs her the guarantee and nothing else — she is paid her commission,
 * promptly, and the month closes (§11.3). Any wording that makes that sound
 * like a penalty is wrong about the rule as well as unkind.
 *
 * The three guarantee sentences are the ones already on the month card and
 * already approved; the fourth — the informational one — is new because the
 * month card never reaches it. It says *this month* rather than *ever*: she
 * may have been on a guarantee last year, and the history under it may show a
 * month where these same numbers did decide her pay.
 */
export function describeTargetPay(
  row: Pick<MonthTargets, "achieved" | "verified" | "determines_pay">,
): string {
  if (!row.determines_pay) {
    return "A record of what HBA asked for. It does not change what you are paid for this month.";
  }
  if (row.achieved === null) {
    return "Nobody has recorded what you posted yet, so it is not settled whether your guaranteed minimum applies.";
  }
  if (!row.achieved) {
    return "Short this month, so your guaranteed minimum does not apply and you are paid your commission.";
  }
  if (!row.verified) {
    return "Met. Your guaranteed minimum applies as soon as HBA confirms the numbers.";
  }
  return "Met and confirmed, so your guaranteed minimum applies.";
}
