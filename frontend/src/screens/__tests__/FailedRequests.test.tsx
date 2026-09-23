// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MyCalculation } from "../MyCalculation";
import { MyWardrobe } from "../MyWardrobe";

/**
 * A12, driven by requests that actually fail.
 *
 * The earlier tests for this checked the decision functions with the failure
 * passed in as a value. That is the right unit to check the *rule*, and it
 * cannot check the wiring: a screen that swallows its own error never reaches
 * those functions with anything to decide. The audit asked for the real
 * thing - "actual rejected API requests, not only static text assertions" -
 * and this is it.
 *
 * `api` calls the global `fetch`, so a stub that rejects is a request that
 * failed in exactly the way a dropped connection fails. The component runs its
 * own effect, takes its own catch branch, and renders whatever it decides,
 * which is the part that was wrong.
 */

const ok = (body: unknown) =>
  Promise.resolve({
    ok: true,
    status: 200,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const earnings = {
  month: "2026-08",
  state: "approved",
  amount_piastres: 200_000,
  amount: "EGP 2,000.00",
  makeup: [{ label: "Commission", detail: "10% of EGP 20,000.00", piastres: 200_000 }],
  sales: { counted_piastres: 2_000_000, counted: "EGP 20,000.00" },
  orders: { earned: 1, pending: 0, void: 0, counted: 1, uses: 1 },
  orders_detail: [],
  carried_in: [],
  carried_out: [],
  waiting_on: [],
  targets: null,
  guarantee: null,
  guarantee_applied: false,
  commission_rate_bp: 1000,
  note: null,
};

const wardrobe = { received: [], processing: [], failed: [], feature_requests: [] };

/** The portal's outlet context, which `usePortal` reads. */
function Portal({ children }: { children: React.ReactNode }) {
  return (
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route
          element={
            <Outlet
              context={{
                me: { name: "Nour", code: "NOUR10" },
                month: "2026-08",
                months: ["2026-08"],
                setMonth: () => undefined,
                reload: () => undefined,
              }}
            />
          }
        >
          <Route path="/" element={children} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  // Explicit, because this project does not run vitest with `globals: true`
  // and React Testing Library only registers its own automatic cleanup when
  // it can see a global `afterEach`. Without it the previous test's DOM is
  // still mounted, and an assertion that something is *absent* passes or
  // fails on a screen that is not the one under test.
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the calculation when the ledger cannot be reached", () => {
  /** The earnings read answers; the payments read does not. */
  function route(paymentsFails: boolean) {
    fetchMock.mockImplementation((path: string) => {
      if (String(path).includes("/api/me/payments")) {
        return paymentsFails
          ? Promise.reject(new TypeError("Failed to fetch"))
          : ok({ months: [], payments: [], outstanding_piastres: 0 });
      }
      if (String(path).includes("/api/me/earnings")) return ok(earnings);
      return ok({});
    });
  }

  it("does not claim the month is unpaid when the request failed", async () => {
    route(true);

    render(<Portal><MyCalculation /></Portal>);

    // The defect: this said "approved" - agreed and not yet paid - on the
    // strength of a request that never answered.
    await waitFor(() =>
      expect(screen.getByText(/payment status unavailable/i)).toBeTruthy(),
    );
    expect(screen.queryByText(/^approved$/i)).toBeNull();
  });

  it("still says 'approved' when the ledger answers and has nothing", async () => {
    route(false);

    render(<Portal><MyCalculation /></Portal>);

    await waitFor(() => expect(screen.getByText(/^approved$/i)).toBeTruthy());
    expect(screen.queryByText(/payment status unavailable/i)).toBeNull();
  });

  it("keeps the breakdown either way, because that read succeeded", async () => {
    route(true);

    render(<Portal><MyCalculation /></Portal>);

    await waitFor(() => expect(screen.getByText("Commission")).toBeTruthy());
  });
});

describe("the wardrobe when best sellers cannot be loaded", () => {
  function route(bestFails: boolean) {
    fetchMock.mockImplementation((path: string) => {
      if (String(path).includes("/api/me/best-sellers")) {
        return bestFails
          ? Promise.reject(new TypeError("Failed to fetch"))
          : ok({ products: [] });
      }
      if (String(path).includes("/api/me/wardrobe")) return ok(wardrobe);
      return ok({});
    });
  }

  it("says the section failed instead of vanishing", async () => {
    route(true);

    render(<Portal><MyWardrobe /></Portal>);

    // The defect: `.catch(() => setBest([]))` made this indistinguishable
    // from a model who has genuinely sold nothing.
    await waitFor(() =>
      expect(screen.getByText(/could not load your best sellers/i)).toBeTruthy(),
    );
  });

  it("stays silent when the request answers with nothing", async () => {
    route(false);

    render(<Portal><MyWardrobe /></Portal>);

    // Wait for the wardrobe itself to settle before asserting an absence,
    // or the assertion passes on a screen that has not loaded yet.
    await waitFor(() => expect(screen.queryByText(/loading wardrobe/i)).toBeNull());
    expect(screen.queryByText(/could not load your best sellers/i)).toBeNull();
    expect(screen.queryByText(/your best sellers/i)).toBeNull();
  });

  it("offers a retry that succeeds the second time", async () => {
    // First attempt fails, second answers: the whole point of the button.
    let attempts = 0;
    fetchMock.mockImplementation((path: string) => {
      if (String(path).includes("/api/me/best-sellers")) {
        attempts += 1;
        return attempts === 1
          ? Promise.reject(new TypeError("Failed to fetch"))
          : ok({
              products: [
                {
                  shopify_product_id: "1",
                  title: "Linen shirt",
                  quantity: 4,
                  sales_piastres: 400_000,
                },
              ],
            });
      }
      if (String(path).includes("/api/me/wardrobe")) return ok(wardrobe);
      return ok({});
    });

    render(<Portal><MyWardrobe /></Portal>);

    const retry = await screen.findByRole("button", { name: /try again/i });
    retry.click();

    await waitFor(() => expect(screen.getByText("Linen shirt")).toBeTruthy());
    expect(screen.queryByText(/could not load your best sellers/i)).toBeNull();
  });
});
