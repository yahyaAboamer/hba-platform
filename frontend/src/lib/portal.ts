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
export type MakeupLine = {
  label: string;
  detail: string | null;
  piastres: number;
  amount: string;
};

export type MyOrder = {
  order_number: string;
  placed_at: string;
  base_piastres: number;
  base: string;
  /** §9.4. Only `earned` counts toward a payout. */
  state: "earned" | "pending" | "void";
  /** The same thing in their words: counted, on its way, did not arrive. */
  state_text: string;
  delivered_at: string | null;
  /** §11.4. Set only where a **different** month's payroll paid it. */
  paid_in_month: string | null;
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
  is_working_month: boolean;
  /**
   * The calendar has not reached this month yet. Distinct from "open with no
   * sales", which is the same figures and a completely different sentence -
   * and it is what a model invited before go-live sees first.
   */
  not_started: boolean;
  sales: {
    earned_piastres: number;
    earned: string;
    pending_piastres: number;
    pending: string;
  };
  orders: { earned: number; pending: number; void: number };
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
  targets: {
    required_videos: number;
    required_stories: number;
    actual_videos: number | null;
    actual_stories: number | null;
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
  } | null;
  /** Translated, and carrying whose move it is. Today always HBA's. */
  waiting_on: { who: string; text: string }[];
  note: string | null;
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
  kind: "credit" | "writeoff" | "correction";
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
};
