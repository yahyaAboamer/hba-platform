/**
 * What `/api/me/earnings/{month}` sends back.
 *
 * One shape, read by two screens - their month and their orders both come from the
 * same request, because the first thing anybody does with a payment figure is
 * try to reconcile it against what they think they sold, and splitting the two
 * across separate calls would let them disagree by a refresh.
 *
 * Transcribed from the server, never inferred. `app/services/portal.py` is
 * where the shape is decided.
 */

/** A line of the breakdown. The lines add up to the total; the server ensures it. */
/**
 * What was asked of a model in one month, and what was recorded against it.
 *
 * One definition, because two screens read it — the month card and the
 * Targets tab — and `TargetProgress` draws both from these fields. A second
 * copy would eventually disagree about a zero or about a month before the
 * platform, and those are the two the rules are subtle about.
 */
export type MonthTargets = {
  /**
   * All four are `null` on a month from before the platform (ADR 0036),
   * where the old dashboard kept whether the target was met and never what
   * was counted to decide it. `numbers_kept` says which kind this is.
   */
  required_videos: number | null;
  required_stories: number | null;
  actual_videos: number | null;
  actual_stories: number | null;
  /**
   * `false` on a month before the platform; `null` where nothing was ever set
   * for the month, which the history list can show and a single month cannot
   * (the month payload is `null` outright in that case).
   */
  numbers_kept: boolean | null;
  /** §15. `null` means nobody has recorded what they produced. */
  achieved: boolean | null;
  verified: boolean;
  /**
   * §15, and the clause that matters: targets decide money only on a
   * guaranteed minimum. On commission they are informational, and a model
   * who reads a missed target as money gone has been told something untrue.
   */
  determines_pay: boolean;
  recorded_at: string | null;
};

export type MakeupLine = {
  label: string;
  detail: string | null;
  piastres: number;
  amount: string;
};

export type OrderStatus = "delivered" | "pending" | "failed" | "cancelled" | "refunded";

/**
 * Net sales **and how it is known** (`net_sales_of`). `known` includes a real
 * `EGP 0.00`; `placed` is a cancelled order's recorded placed-at total;
 * `unavailable` is a zeroed void order with nothing recorded. Never inferred
 * from a value being zero.
 */
export type NetSales = {
  kind: "known" | "placed" | "unavailable";
  piastres: number | null;
  amount: string | null;
};

/** Which month an order counts in, decided by the server (`counts_towards`). */
export type CountsTowards = {
  decision: "counted" | "excluded" | "failed_after_approval" | "after_delivery";
  month: string;
};

export type MyOrder = {
  /**
   * What was in the order. **Empty means not recorded, not empty**: contents
   * are read only for orders that earned commission, and only from 07A
   * onwards, so an older order legitimately has none.
   */
  contents: {
    title: string;
    variant: string | null;
    quantity: number;
    /** What the customer paid for the line, after the discount. */
    price_piastres: number;
    price: string;
  }[];
  order_number: string;
  placed_at: string;
  base_piastres: number;
  base: string;
  /** §9.4. The counting state: `earned` and `pending` count (ADR 0040). */
  state: "earned" | "pending" | "void";
  /**
   * What happened to it. A void order is split by why - only a courier's
   * failure is `failed`; `cancelled` and `refunded` (while travelling) are not
   * failed deliveries and never read as one.
   */
  status: OrderStatus;
  /** `status` in the approved words: *Delivered*, *Pending*, *Failed delivery*. */
  state_text: string;
  /** The month's own rate, for *Commission is 10% of EGP X*. */
  rate_bp: number | null;
  /** Void, but counted by the month's agreement: it failed after approval. */
  failed_after_approval: boolean;
  net_sales: NetSales;
  counts_towards: CountsTowards;
  delivered_at: string | null;
  /** §11.4. Set only where a **different** month's payroll paid it. */
  paid_in_month: string | null;
  /**
   * What this one order was worth in commission, to the whole piastre.
   *
   * Every **counted** order has one - delivered and pending under the live
   * rule (ADR 0040), delivered only on a month agreed before it. `0` is a real
   * figure (an order the customer paid nothing for). `null` is no answer: a
   * void order (see `forgone`), an order its month did not count, or a month
   * with no rate set (`rate_missing`).
   *
   * **A worked example, not a ledger line.** ADR 0004 divides one numerator
   * once for the whole month, so these can miss the month's rounded total by
   * up to half a pound when summed. The screen says what the total is rather
   * than inviting an addition.
   */
  commission_piastres: number | null;
  commission: string | null;
  /** Whether it counts in this month's figure, under the month's own rule. */
  counted: boolean;
  /** Nobody set a rate for the month: *not available*, never a zero. */
  rate_missing: boolean;
  /**
   * What the order came to when it was placed, where the base no longer says.
   *
   * Shopify zeroes a cancelled order's totals — correct for commission, since
   * §9.3 pays on what the customer actually paid — so a cancelled row's
   * `base_piastres` is `0` and tells you nothing about what it was.
   *
   * `null` where the base already carries the figure, so no screen shows the
   * same money twice, and `null` on rows indexed before the platform asked
   * Shopify for it. That is *we never asked*, not *it was free*.
   */
  placed_piastres: number | null;
  placed: string | null;
  /**
   * What a void order **would** have earned, had it arrived.
   *
   * Struck through beside the value it would have earned it on, so a row that
   * earned nothing still shows the figure rather than only the words. `null`
   * on anything that has not lost something yet — an order still travelling
   * has not.
   *
   * **Never summed.** No total on any screen includes it.
   */
  forgone_piastres: number | null;
  forgone: string | null;
};

export type MyEarnings = {
  month: string;
  /**
   * §11.1, and the most important thing on the screen. `open` is a working
   * number that will move; `agreed` is what they are owed and cannot move;
   * `historical` predates the platform and has no commission figure at all
   * (ADR 0014).
   */
  state: "historical" | "open" | "agreed";
  /**
   * The counting rule behind the figure. `delivered_only` only on a month
   * agreed before ADR 0040, and described as it was agreed.
   */
  policy: "pending_inclusive" | "delivered_only";
  is_working_month: boolean;
  /**
   * The calendar has not reached this month yet. Distinct from "open with no
   * sales", which is the same figures and a completely different sentence -
   * and it is what a model invited before go-live sees first.
   */
  not_started: boolean;
  sales: {
    /**
     * **What the month is paid on** (F02): delivered and pending together,
     * never a failed delivery. This is *net sales counted* on her Home card,
     * and the figure the year chart plots.
     */
    counted_piastres: number;
    counted: string;
    counted_orders: number;
    /** The delivered half of that. */
    earned_piastres: number;
    earned: string;
    /** The half still travelling. */
    pending_piastres: number;
    pending: string;
    /** What did not arrive. Counted for nothing, and still worth saying. */
    failed_piastres: number;
    failed: string;
    /**
     * What a counted order was worth, on average. `null` at zero counted
     * orders - the difference between *your average order is worth nothing*
     * and *there is nothing to average yet*.
     */
    average_order_piastres: number | null;
    average_order: string | null;
  };
  /**
   * When the month opens, closes, and how far through it is.
   *
   * Facts, not words: the sentences are written in `MyMonth.tsx` beside
   * everything else this screen says. `days_left` is `null` once the month is
   * over, and an agreed month is finished by definition whatever the calendar
   * says - approval is what ends it.
   */
  window: {
    opens: string;
    closes: string;
    progress_pct: number;
    days_left: number | null;
  };
  orders: {
    earned: number;
    pending: number;
    void: number;
    /** Delivered plus pending: the orders the month is paid on. */
    counted: number;
    /**
     * How often her code was used (M01, D03). **Not the sum of the three
     * above**: those are commission states and this is a delivery outcome, so
     * a delivered order later refunded counts here and pays nothing, while a
     * parcel refused at the door counts nowhere.
     */
    uses: number;
  };
  /** `null` on a historical month, where no figure was ever calculated. */
  amount_piastres: number | null;
  amount: string | null;
  makeup: MakeupLine[];
  carried_in: {
    from_month: string;
    orders: number;
    base_piastres: number;
    base: string;
    commission_rate_bp: number;
    piastres: number;
    amount: string;
  }[];
  /** Orders they sold this month that a later payroll paid. Their side of §11.4. */
  carried_out: {
    to_month: string;
    orders: number;
    base_piastres: number;
    base: string;
  }[];
  guarantee_applied: boolean;
  /**
   * Their guaranteed minimum, on a `base_guarantee` arrangement only - and
   * present whether or not it applied. §9.5 pays whichever is larger, so a
   * month where the comparison could not be made still has to name the figure
   * they signed for, or the screen reads as having forgotten it.
   */
  guarantee: {
    piastres: number;
    amount: string;
    applied: boolean;
    /** §15. `null` means nobody has recorded what they produced. */
    targets_achieved: boolean | null;
    targets_verified: boolean;
  } | null;
  commission_rate_bp: number | null;
  /**
   * What was asked of them and what was recorded. `null` when nothing was ever
   * set for the month - a target that does not exist is not one they failed.
   */
  targets: MonthTargets | null;
  /** Translated, and carrying whose move it is. Today always HBA's. */
  waiting_on: { who: string; text: string }[];
  note: string | null;
  /**
   * §16, Phase 10 Batch C. Which rules this month was actually calculated
   * under - frozen at approval, never the current ones. `null` on a month
   * that is not agreed yet, or one approved before any policy existed.
   */
  policy_version: { id: number; effective_month: string } | null;
  /**
   * Set only when this month was agreed, reopened and agreed again at a
   * different figure. A settled month is meant to be final, so one that moved
   * has to say so rather than quietly becoming a different number.
   */
  recalculated: {
    was_piastres: number;
    now_piastres: number;
    at: string | null;
  } | null;
  /** Money landing on this month that was earned in an earlier one. */
  /**
   * An earlier month's overpayment being recovered out of this one.
   *
   * `text` is written by the server (05C) and rendered as it arrives. Under
   * D04 a carried overpayment can consume a whole month, so this sentence is
   * what stands between a model opening a month worth nothing and a support
   * message - and a sentence the browser assembles is one no backend test can
   * hold to account.
   */
  credited_from: { month: string; piastres: number; text: string }[];
  orders_detail: MyOrder[];
};

/** One month's settlement, derived from the ledger and never stored. */
export type PaymentMonth = {
  month: string;
  /**
   * §11.1. `not_approved` never reaches this screen — a month with no agreed
   * figure is not an unpaid bill, and saying "nothing outstanding" about one
   * that may have been paid against a superseded version is the most
   * misleading answer available.
   */
  state: "unpaid" | "partially_paid" | "settled" | "overpaid";
  obligation_piastres: number;
  obligation: string;
  paid_piastres: number;
  paid: string;
  /** Settled without a transfer - a write-off or a correction (§11.5). */
  adjusted_piastres: number;
  adjusted: string;
  /** An overpayment from an earlier month, applied to this one. */
  credited_piastres: number;
  credited: string;
  balance_piastres: number;
  balance: string;
};

export type Payment = {
  id: number;
  amount_piastres: number;
  amount: string;
  occurred_at: string;
  reference: string | null;
  /** Masked, and frozen at the moment it was paid (§6.4.4). */
  destination: Record<string, string | null> | null;
  /** §14 and ADR 0017. The screenshot, served only to them. */
  has_proof: boolean;
  /** Which months it covered. Empty is ordinary: money can arrive first. */
  settles: { month: string; piastres: number; amount: string }[];
};

/** §11.5. A credit they cannot see is a credit they cannot check. */
export type Adjustment = {
  kind: "credit" | "writeoff" | "correction" | "accepted" | "release";
  kind_text: string;
  amount_piastres: number;
  amount: string;
  /** As somebody wrote it at the time. §11.5 makes it mandatory. */
  reason: string;
  created_at: string;
  from_month: string | null;
  to_month: string | null;
};

export type MyPayments = {
  months: PaymentMonth[];
  payments: Payment[];
  adjustments: Adjustment[];
  outstanding_piastres: number;
  outstanding: string;
  /**
   * ADR 0036. `null` for a model with no month before go-live — she never
   * learns there was an old dashboard, because there is nothing about it she
   * needs to know.
   *
   * The only place in the portal that mentions it. Every other screen shows
   * those months in full, exactly like the rest of her year.
   */
  settled_outside: { months: string[]; since: string; text: string } | null;
};

/**
 * Where each month in her month list has got to, in the export's words
 * (`monthOptions`: *in progress*, *approved*, *paid*, *settled*).
 *
 * From her payments, which already hold every answer the list needs: a month
 * settled before the platform is in `settled_outside`; an agreed month is in
 * `months` with its balance, paid once nothing is outstanding - the same
 * reading `homeState` gives the month on screen; and a month in neither has
 * no agreed figure, so it is still in progress.
 *
 * `null` when the payments could not be read. The list then names the months
 * and says nothing about them, rather than guessing (A12).
 */
export type MonthListState = "open" | "approved" | "paid" | "settled";

export function monthListStates(
  months: string[],
  payments: MyPayments | null,
): Record<string, MonthListState> | null {
  if (!payments) return null;
  const outside = new Set(payments.settled_outside?.months ?? []);
  return Object.fromEntries(
    months.map((month) => {
      if (outside.has(month)) return [month, "settled"];
      const row = payments.months.find((entry) => entry.month === month);
      if (!row) return [month, "open"];
      const paid = row.state === "settled" || row.state === "overpaid";
      return [month, paid ? "paid" : "approved"];
    }),
  );
}
