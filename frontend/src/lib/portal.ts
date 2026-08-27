/**
 * What `/api/me/earnings/{month}` sends back.
 *
 * One shape, read by two screens - her month and her orders both come from the
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
  /** The same thing in her words: counted, on its way, did not arrive. */
  state_text: string;
  delivered_at: string | null;
  /** §11.4. Set only where a **different** month's payroll paid it. */
  paid_in_month: string | null;
};

export type MyEarnings = {
  month: string;
  /**
   * §11.1, and the most important thing on the screen. `open` is a working
   * number that will move; `agreed` is what she is owed and cannot move;
   * `historical` predates the platform and has no commission figure at all
   * (ADR 0014).
   */
  state: "historical" | "open" | "agreed";
  is_working_month: boolean;
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
  /** Orders she sold this month that a later payroll paid. Her side of §11.4. */
  carried_out: {
    to_month: string;
    orders: number;
    base_piastres: number;
    base: string;
  }[];
  guarantee_applied: boolean;
  /**
   * Her guaranteed minimum, on a `base_guarantee` arrangement only - and
   * present whether or not it applied. §9.5 pays whichever is larger, so a
   * month where the comparison could not be made still has to name the figure
   * she signed for, or the screen reads as having forgotten it.
   */
  guarantee: {
    piastres: number;
    amount: string;
    applied: boolean;
    /** §15. `null` means nobody has recorded what she produced. */
    targets_achieved: boolean | null;
    targets_verified: boolean;
  } | null;
  commission_rate_bp: number | null;
  /** Translated, and carrying whose move it is. Today always HBA's. */
  waiting_on: { who: string; text: string }[];
  note: string | null;
  orders_detail: MyOrder[];
};
