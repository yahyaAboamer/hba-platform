/**
 * Turning a strip of months into the periods that get written, and back.
 *
 * ADR 0036, task #17. Kept apart from the screen because **this is the part
 * that decides what is recorded**: which months collapse into one arrangement,
 * which target outcomes travel with them, and what a typed percentage becomes.
 * A component cannot be tested without a DOM; this can, and it is the half
 * worth testing.
 */

export type Kind = "commission" | "fixed_plus_commission" | "base_guarantee";

export type Terms = {
  start_month: string;
  end_month: string | null;
  compensation_type: Kind;
  commission_rate_bp: number;
  fixed_amount_piastres: number | null;
  base_amount_piastres: number | null;
  expected_customer_discount_bp: number | null;
};

export type MonthRow = {
  month: string;
  /** She sold in it. Months before her first sale are not hers to arrange. */
  has_orders: boolean;
  /** Approved, so what it was calculated from may not move (§11.1). */
  approved: boolean;
  /** Before go-live: a guaranteed minimum here records an outcome (ADR 0036). */
  settled_outside: boolean;
  terms: Terms | null;
  outcome: "met" | "missed" | null;
};

export type PayHistory = {
  affiliate_id: number;
  name: string;
  working_month: string;
  go_live_month: string | null;
  /** Her first month with an order. `null` for a model who has never sold. */
  joined_month: string | null;
  months: MonthRow[];
  periods: Terms[];
};

/** What is set for one month while the screen is being used. */
export type Arrangement = {
  kind: Kind;
  rateBp: number;
  amountPiastres: number;
  /** Only on a guaranteed minimum before go-live. `null` everywhere else. */
  met: boolean | null;
};

export type Run = Arrangement & { from: string; to: string };

/** What the server already has, in the shape the screen holds it. */
export function fromServer(body: PayHistory): Record<string, Arrangement> {
  const set: Record<string, Arrangement> = {};
  for (const row of body.months) {
    if (!row.terms) continue;
    set[row.month] = {
      kind: row.terms.compensation_type,
      amountPiastres:
        row.terms.fixed_amount_piastres ?? row.terms.base_amount_piastres ?? 0,
      rateBp: row.terms.commission_rate_bp,
      met:
        row.terms.compensation_type === "base_guarantee" && row.settled_outside
          ? row.outcome === null
            ? null
            : row.outcome === "met"
          : null,
    };
  }
  return set;
}

/**
 * Consecutive months on an identical arrangement, as one run.
 *
 * **Because that is what actually gets written.** `set_terms` records a run,
 * not a month, and showing nine rows for one decision would misrepresent the
 * record somebody is about to agree to.
 *
 * A gap breaks a run even when the arrangement on either side matches: two
 * separated stretches on 10% are two periods, and joining them would claim she
 * was on terms during a month nobody set any for.
 *
 * A differing target outcome breaks a run **for the table only**. See
 * `periodsToWrite`: the arrangement is identical either way, and splitting the
 * record on it would write two rows where the business made one decision.
 */
export function runs(
  months: MonthRow[],
  set: Record<string, Arrangement>,
): Run[] {
  return collapse(months, set, true);
}

/**
 * The periods that are actually written. ADR 0036.
 *
 * **Not the table's rows**, and the difference is a real one that showed up
 * only on the built screen. June on a guaranteed minimum with the target met
 * and July on the same guarantee with it missed are *one* arrangement — the
 * rate and the floor are identical, and the outcome lives on the target, not
 * on the pay terms. The table splits them because a single row could not say
 * which month was paid the floor. Writing them split would put two
 * compensation periods on record where the business made one decision, and
 * the save note would promise four arrangements while meaning three.
 */
export function periodsToWrite(
  months: MonthRow[],
  set: Record<string, Arrangement>,
): Run[] {
  return collapse(months, set, false);
}

function collapse(
  months: MonthRow[],
  set: Record<string, Arrangement>,
  splitOnOutcome: boolean,
): Run[] {
  const out: Run[] = [];
  let previous: string | null = null;

  for (const row of months) {
    const arrangement = set[row.month];
    if (!arrangement) {
      previous = null;
      continue;
    }
    const last = out[out.length - 1];
    const continues =
      last !== undefined &&
      previous === last.to &&
      last.kind === arrangement.kind &&
      last.rateBp === arrangement.rateBp &&
      last.amountPiastres === arrangement.amountPiastres &&
      (!splitOnOutcome || last.met === arrangement.met);

    if (continues) last.to = row.month;
    else out.push({ ...arrangement, from: row.month, to: row.month });
    previous = row.month;
  }
  return out;
}

/**
 * The met/missed answers, for the months entitled to have one.
 *
 * Only a guaranteed minimum, and only before go-live. A month the platform
 * pays for records what was produced, on the Targets screen, and is counted
 * rather than asserted — the server refuses an outcome for one, and sending
 * it would fail the whole save (ADR 0036).
 */
export function outcomesFrom(
  months: MonthRow[],
  set: Record<string, Arrangement>,
): Record<string, "met" | "missed"> {
  const outcomes: Record<string, "met" | "missed"> = {};
  for (const row of months) {
    const arrangement = set[row.month];
    if (!row.settled_outside) continue;
    if (arrangement?.kind !== "base_guarantee") continue;
    if (arrangement.met === null) continue;
    outcomes[row.month] = arrangement.met ? "met" : "missed";
  }
  return outcomes;
}

/**
 * A percentage as basis points, never as a float.
 *
 * 10% is 1000 and 12.5% is 1250 — the multiply happens on a string, so a rate
 * can never arrive as 1249.9999 (ADR 0002).
 */
export function toBasisPoints(text: string): number | null {
  const cleaned = text.trim().replace(/%$/, "").trim();
  if (!/^\d*(\.\d{1,2})?$/.test(cleaned) || cleaned === "" || cleaned === ".") {
    return null;
  }
  const [whole = "0", fraction = ""] = cleaned.split(".");
  return Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
}
