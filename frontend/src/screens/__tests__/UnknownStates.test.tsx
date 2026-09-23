import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { homeState, STATE_LABEL } from "../MyMonth";
import { WardrobeContents } from "../MyWardrobe";
import type { MyEarnings, PaymentMonth } from "../../lib/portal";

/**
 * A12. A failed read is not an answer.
 *
 * Three screens turned a request that never answered into a statement of
 * fact: the calculation said **approved** — agreed and not yet paid — when it
 * could not reach the ledger at all; the wardrobe turned a failed
 * best-sellers read into an empty list, which looks exactly like a model who
 * has sold nothing; and the payments tab said *nothing has been paid yet*
 * about a ledger that only begins at go-live.
 *
 * Each of those is a sentence about her money, produced by an error.
 */

const earnings = (over: Partial<MyEarnings> = {}): MyEarnings =>
  ({
    month: "2026-08",
    state: "approved",
    amount_piastres: 200_000,
    amount: "EGP 2,000.00",
    makeup: [],
    ...over,
  }) as MyEarnings;

const settled = { month: "2026-08", state: "settled" } as PaymentMonth;

describe("a month whose settlement could not be read", () => {
  it("says the payment status is unavailable rather than 'approved'", () => {
    const state = homeState(earnings(), undefined, false);

    expect(state).toBe("unknown");
    expect(STATE_LABEL[state]).toBe("payment status unavailable");
  });

  it("still says 'approved' when the ledger genuinely has nothing", () => {
    // The distinction the old code could not draw: this one is an answer.
    expect(homeState(earnings(), undefined, true)).toBe("approved");
  });

  it("reports a recorded payment when the ledger says so", () => {
    expect(homeState(earnings(), settled, true)).toBe("paid");
  });

  it("does not let a failed ledger read disturb a month that never needed it", () => {
    // An open month and a pre-platform month are decided by the earnings
    // read alone, so a broken settlement request costs them nothing.
    expect(homeState(earnings({ state: "open" }), undefined, false)).toBe("open");
    expect(homeState(earnings({ state: "historical" }), undefined, false)).toBe(
      "settled",
    );
  });
});

type WardrobeBody = Parameters<typeof WardrobeContents>[0]["body"];

const wardrobe = {
  received: [],
  processing: [],
  failed: [],
  feature_requests: [],
} as unknown as WardrobeBody;

describe("best sellers that could not be loaded", () => {
  const render = (props: Parameters<typeof WardrobeContents>[0]) =>
    renderToStaticMarkup(
      <MemoryRouter>
        <WardrobeContents {...props} />
      </MemoryRouter>,
    );

  it("says the section failed instead of vanishing", () => {
    const html = render({ body: wardrobe, best: null, bestError: "Network error" });

    expect(html).toContain("Could not load your best sellers");
  });

  it("stays silent for a model who genuinely has no sales", () => {
    const html = render({ body: wardrobe, best: [], bestError: null });

    expect(html).not.toContain("Could not load");
    expect(html).not.toContain("Your best sellers");
  });

  it("is still silent while the read is in flight", () => {
    // `null` with no error is *not answered yet*, which is a third thing and
    // must not be drawn as either of the other two.
    const html = render({ body: wardrobe, best: null, bestError: null });

    expect(html).not.toContain("Could not load");
    expect(html).not.toContain("Your best sellers");
  });
});
