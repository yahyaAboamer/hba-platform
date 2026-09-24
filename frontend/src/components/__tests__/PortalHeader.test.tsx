// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PortalHeader } from "../AffiliateLayout";

const ok = (body: unknown) =>
  Promise.resolve({
    ok: true,
    status: 200,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function header(path: string, onMonth: (month: string) => void = () => undefined) {
  return (
    <MemoryRouter initialEntries={[path]}>
      <PortalHeader
        name="Test Model"
        code="TESTCODE"
        codePending={false}
        month="2026-09"
        months={["2026-09", "2026-08", "2026-07", "2026-06"]}
        onMonth={onMonth}
      />
    </MemoryRouter>
  );
}

/** Her payments: June before the platform, July paid, August agreed and
 *  owed, September with nothing agreed yet. */
const payments = {
  months: [
    { month: "2026-08", state: "unpaid" },
    { month: "2026-07", state: "settled" },
  ],
  payments: [],
  settled_outside: { months: ["2026-06"], since: "2026-07", text: "" },
};

describe("the portal header's month control", () => {
  it("is the export's compact short month, not a select", () => {
    const html = renderToStaticMarkup(header("/ranking"));
    expect(html).not.toContain("<select");
    expect(html).toContain(">Sep<");
    expect(html).toContain('aria-label="Month: September 2026"');
    expect(html).toContain('aria-expanded="false"');
  });

  it("appears on Home, Orders and Ranking only", () => {
    expect(renderToStaticMarkup(header("/"))).toContain("Month: September 2026");
    expect(renderToStaticMarkup(header("/orders"))).toContain("Month: September 2026");
    expect(renderToStaticMarkup(header("/wardrobe"))).not.toContain("Month:");
    expect(renderToStaticMarkup(header("/targets"))).not.toContain("Month:");
  });

  it("opens her months, each with where it has got to, and closes on a choice", async () => {
    fetchMock.mockImplementation((path: string) =>
      String(path).includes("/api/me/payments") ? ok(payments) : ok({}),
    );
    const onMonth = vi.fn();
    render(header("/", onMonth));

    fireEvent.click(screen.getByRole("button", { name: "Month: September 2026" }));

    // Exactly the months she can see - no calendar around them.
    const rows = ["September 2026", "August 2026", "July 2026", "June 2026"];
    for (const label of rows) expect(screen.getByRole("button", { name: new RegExp(`^${label}`) })).toBeTruthy();
    expect(screen.queryByText("May 2026")).toBeNull();

    await waitFor(() => expect(screen.getByText("in progress")).toBeTruthy());
    expect(screen.getByRole("button", { name: /^September 2026/ }).textContent).toContain("in progress");
    expect(screen.getByRole("button", { name: /^August 2026/ }).textContent).toContain("approved");
    expect(screen.getByRole("button", { name: /^July 2026/ }).textContent).toContain("paid");
    expect(screen.getByRole("button", { name: /^June 2026/ }).textContent).toContain("settled");
    expect(screen.getByRole("button", { name: /^September 2026/ }).getAttribute("aria-current")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: /^August 2026/ }));
    expect(onMonth).toHaveBeenCalledWith("2026-08");
    expect(screen.queryByRole("button", { name: /^June 2026/ })).toBeNull();
  });

  it("names the months without guessing when her payments cannot be read", async () => {
    fetchMock.mockImplementation(() => Promise.reject(new TypeError("Failed to fetch")));
    render(header("/"));

    fireEvent.click(screen.getByRole("button", { name: "Month: September 2026" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: /^August 2026/ })).toBeTruthy();
    for (const word of ["in progress", "approved", "paid", "settled"]) {
      expect(screen.queryByText(word)).toBeNull();
    }
  });

  it("puts the calculation behind its own back header", () => {
    const html = renderToStaticMarkup(header("/earnings"));
    expect(html).toContain("How this adds up");
    expect(html).toContain("← Back");
    expect(html).not.toContain("Test Model");
  });
});
