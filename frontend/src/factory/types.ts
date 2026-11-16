/**
 * What `/api/factory` answers (batch 6b: `docs/plans/2026-11-16-production-factory-login-build.md`).
 *
 * The server builds every one of these from a whitelist: **there is no money
 * in them, no other supplier and no rating**, and this file has no field for
 * any. A screen cannot draw what the type does not carry.
 */

/** The order's pieces cut: what the factory said, and what HBA's QC manager confirmed. */
export type FactoryCut = { reported_total: number | null; confirmed_total: number | null };

/** One line of "Your orders". */
export type FactoryOrderRow = {
  id: number;
  code: string;
  style_name: string;
  colour: string;
  /** In words: "none", "at the factory", "outside". */
  printing: string;
  planned_total: number;
  cut: FactoryCut;
  /** Where the order is, in words the factory reads ("being made"). */
  status_words: string;
  /** `YYYY-MM-DD`. */
  delivery_date: string;
  /** The date has been moved since it was planned. */
  moved: boolean;
  /** `YYYY-MM-DD`: the date as first planned, when it has been moved. */
  moved_from?: string | null;
};

export type FactorySizeLine = {
  size: string;
  planned: number;
  reported: number | null;
  confirmed: number | null;
};

/** A report the factory sent that the QC manager has not yet confirmed. */
export type FactoryReport = {
  /** A day (`YYYY-MM-DD`) or the instant the server stamped. */
  reported_on: string;
  note: string | null;
};

/** One line of the date history. HBA's people are "HBA", never a name. */
export type FactoryDateLine = {
  on: string;
  date: string;
  by: "HBA" | "You";
  reason: string | null;
};

export type FactoryOrder = FactoryOrderRow & {
  sizes: FactorySizeLine[];
  report: FactoryReport | null;
  can_report_cut: boolean;
  can_move_date: boolean;
  dates: FactoryDateLine[];
};
