import { describe, expect, it } from "vitest";

import {
  fromServer,
  outcomesFrom,
  periodsToWrite,
  runs,
  toBasisPoints,
} from "../payHistory";
import type { Arrangement, MonthRow, PayHistory } from "../payHistory";

/**
 * The pay-history editor's arithmetic. ADR 0036, task #17.
 *
 * This is the half that decides what is *recorded*, so it is the half worth
 * testing: how many periods a strip of months collapses into, which target
 * outcomes travel with them, and what a typed percentage becomes.
 */

function month(month: string, overrides: Partial<MonthRow> = {}): MonthRow {
  return {
    month,
    has_orders: true,
    approved: false,
    settled_outside: false,
    terms: null,
    outcome: null,
    ...overrides,
  };
}

function commission(rateBp = 1000): Arrangement {
  return { kind: "commission", rateBp, amountPiastres: 0, met: null };
}

function guarantee(met: boolean | null, base = 300_000): Arrangement {
  return {
    kind: "base_guarantee",
    rateBp: 1000,
    amountPiastres: base,
    met,
  };
}

describe("runs", () => {
  it("collapses consecutive identical months into one period", () => {
    const months = ["2026-02", "2026-03", "2026-04"].map((m) => month(m));
    const set = {
      "2026-02": commission(),
      "2026-03": commission(),
      "2026-04": commission(),
    };

    expect(runs(months, set)).toEqual([
      { ...commission(), from: "2026-02", to: "2026-04" },
    ]);
  });

  it("starts a new period where the arrangement changes", () => {
    const months = ["2026-02", "2026-03", "2026-04"].map((m) => month(m));
    const set = {
      "2026-02": commission(800),
      "2026-03": commission(1000),
      "2026-04": commission(1000),
    };

    const result = runs(months, set);

    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({ from: "2026-02", to: "2026-02", rateBp: 800 });
    expect(result[1]).toMatchObject({ from: "2026-03", to: "2026-04", rateBp: 1000 });
  });

  it("does not join two stretches across a month with nothing set", () => {
    // Joining them would claim she was on terms during a month nobody set any
    // for — and that month would then be silently calculable.
    const months = ["2026-02", "2026-03", "2026-04"].map((m) => month(m));
    const set = { "2026-02": commission(), "2026-04": commission() };

    const result = runs(months, set);

    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({ from: "2026-02", to: "2026-02" });
    expect(result[1]).toMatchObject({ from: "2026-04", to: "2026-04" });
  });

  it("splits a row where the target outcome differs", () => {
    // One row could not say whether the target was met, and that is the
    // column deciding which of the two months was paid the floor.
    const months = ["2026-02", "2026-03"].map((m) =>
      month(m, { settled_outside: true }),
    );
    const set = { "2026-02": guarantee(true), "2026-03": guarantee(false) };

    const result = runs(months, set);

    expect(result).toHaveLength(2);
    expect(result[0].met).toBe(true);
    expect(result[1].met).toBe(false);
  });

  it("is empty when nothing has been set", () => {
    expect(runs([month("2026-02")], {})).toEqual([]);
  });
});

describe("periodsToWrite", () => {
  it("does NOT split on the target outcome, where the table does", () => {
    // **The difference between what is shown and what is recorded.** June on a
    // guarantee with the target met and July on the same guarantee with it
    // missed are one arrangement: the rate and the floor are identical, and
    // the outcome lives on the target rather than on the pay terms.
    //
    // Writing them split would put two compensation periods on record where
    // the business made one decision — and the save note would promise four
    // arrangements while meaning three. Found by looking at the built screen.
    const months = ["2026-02", "2026-03"].map((m) =>
      month(m, { settled_outside: true }),
    );
    const set = { "2026-02": guarantee(true), "2026-03": guarantee(false) };

    expect(runs(months, set)).toHaveLength(2);

    const periods = periodsToWrite(months, set);
    expect(periods).toHaveLength(1);
    expect(periods[0]).toMatchObject({ from: "2026-02", to: "2026-03" });
  });

  it("still splits where the arrangement itself changes", () => {
    const months = ["2026-02", "2026-03"].map((m) => month(m));
    const set = { "2026-02": commission(800), "2026-03": commission(1000) };

    expect(periodsToWrite(months, set)).toHaveLength(2);
  });

  it("still refuses to bridge a month with nothing set", () => {
    const months = ["2026-02", "2026-03", "2026-04"].map((m) => month(m));
    const set = { "2026-02": commission(), "2026-04": commission() };

    expect(periodsToWrite(months, set)).toHaveLength(2);
  });
});

describe("outcomesFrom", () => {
  it("collects met and missed for guarantee months before go-live", () => {
    const months = ["2026-02", "2026-03"].map((m) =>
      month(m, { settled_outside: true }),
    );
    const set = { "2026-02": guarantee(true), "2026-03": guarantee(false) };

    expect(outcomesFrom(months, set)).toEqual({
      "2026-02": "met",
      "2026-03": "missed",
    });
  });

  it("sends nothing for a guarantee month the platform pays for", () => {
    // The server refuses an outcome there — a target asserted without counts
    // would unlock a guarantee on a month that can still be paid — and sending
    // one would fail the whole save.
    const months = [month("2026-09", { settled_outside: false })];
    const set = { "2026-09": guarantee(true) };

    expect(outcomesFrom(months, set)).toEqual({});
  });

  it("sends nothing for an arrangement that has no targets", () => {
    const months = [month("2026-02", { settled_outside: true })];
    const set = { "2026-02": commission() };

    expect(outcomesFrom(months, set)).toEqual({});
  });

  it("omits a month whose outcome has not been answered yet", () => {
    const months = [month("2026-02", { settled_outside: true })];
    const set = { "2026-02": guarantee(null) };

    expect(outcomesFrom(months, set)).toEqual({});
  });
});

describe("fromServer", () => {
  it("reads an existing history back onto the strip", () => {
    const body: PayHistory = {
      affiliate_id: 1,
      name: "Jana",
      working_month: "2026-09",
      go_live_month: "2026-08",
      joined_month: "2026-02",
      periods: [],
      // `fromServer` reads the strip, not the verdict. Present because the
      // payload carries it, and deliberately empty: this test is about
      // arrangements coming back onto the tiles.
      readiness: {
        start_month: "2026-02",
        start_is_recorded: false,
        months: [],
        eligible: 0,
        ready: 0,
        blocking: 0,
      },
      months: [
        month("2026-02", {
          settled_outside: true,
          outcome: "met",
          terms: {
            start_month: "2026-02",
            end_month: null,
            compensation_type: "base_guarantee",
            commission_rate_bp: 1000,
            fixed_amount_piastres: null,
            base_amount_piastres: 300_000,
            expected_customer_discount_bp: null,
          },
        }),
        month("2026-03"),
      ],
    };

    const set = fromServer(body);

    expect(set["2026-02"]).toEqual(guarantee(true));
    // A month with no terms is absent rather than blank, which is what the
    // save bar counts when it says how many are still without an arrangement.
    expect(set["2026-03"]).toBeUndefined();
  });
});

describe("toBasisPoints", () => {
  it("reads whole and fractional percentages exactly", () => {
    expect(toBasisPoints("10")).toBe(1000);
    expect(toBasisPoints("12.5")).toBe(1250);
    expect(toBasisPoints("8.25")).toBe(825);
    expect(toBasisPoints(" 10% ")).toBe(1000);
  });

  it("refuses anything that is not a rate", () => {
    // `null` disables Apply. A rate read loosely is a rate somebody did not
    // type, and it decides money for every month in the selection.
    expect(toBasisPoints("")).toBeNull();
    expect(toBasisPoints(".")).toBeNull();
    expect(toBasisPoints("ten")).toBeNull();
    expect(toBasisPoints("10.005")).toBeNull();
    expect(toBasisPoints("-5")).toBeNull();
  });
});
