// @vitest-environment jsdom
/**
 * Production as a department like the others (ADR 0085): its screens at
 * `/production/*` inside the platform's own frame, with its sections in the
 * sidebar, and no framed app. The rebuild's `/production/next/*` and the old
 * framed app's pages go on to the same or the nearest page.
 */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { narrowScreen } from "../departments/production/screens/__tests__/fixtures";
import { OLD_PAGES } from "../departments/production/screens/routes";
import { reply, serve, sessionOf } from "./frameHarness";

beforeEach(() => window.history.pushState({}, "", "/"));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** The frame's usual answers, and an empty Production behind them. */
function serveProduction(address: string) {
  window.history.pushState({}, "", address);
  serve(sessionOf("production_staff"));
  narrowScreen(false);
  const frame = globalThis.fetch;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.includes("/api/prod/orders")) return reply(200, { orders: [] });
      if (url.includes("/api/prod/")) return reply(404, { detail: "Not served here" });
      return frame(input, init);
    }),
  );
}

const sections = () => {
  const sidebar = screen.getByRole("navigation", { name: "Departments" });
  return within(sidebar).getAllByRole("link").map((link) => [link.textContent, link.getAttribute("href")]);
};

describe("Production, in the frame", () => {
  it("opens on Overview, with its eight sections in the sidebar and no frame inside the page", async () => {
    serveProduction("/production");
    render(<App />);

    await waitFor(() => expect(window.location.pathname).toBe("/production/overview"));
    expect(sections()).toEqual([
      ["Overview", "/production/overview"],
      ["Orders", "/production/orders"],
      ["Tasks", "/production/tasks"],
      ["Library", "/production/library"],
      ["Fabric", "/production/fabric"],
      ["Incoming", "/production/incoming"],
      ["Suppliers", "/production/suppliers"],
      ["Stage days", "/production/settings"],
    ]);
    expect(document.querySelector("iframe")).toBeNull();
    expect(document.querySelector(".frame--strip")).toBeNull();
    await waitFor(() =>
      expect(
        within(screen.getByRole("navigation", { name: "Departments" })).getByRole("link", { name: "Overview" }).getAttribute("aria-current"),
      ).toBe("page"),
    );
  });

  it.each([
    ["/production/orders", "Orders"],
    ["/production/orders/new", "Orders"],
    ["/production/tasks", "Tasks"],
    ["/production/incoming", "Incoming"],
    ["/production/suppliers", "Suppliers"],
    ["/production/suppliers/fac", "Suppliers"],
    ["/production/settings", "Stage days"],
  ])("%s shows %s as the current section, in no frame", async (address, section) => {
    serveProduction(address);
    render(<App />);

    await waitFor(() => {
      const current = within(screen.getByRole("navigation", { name: "Departments" })).getByRole("link", { name: section });
      expect(current.getAttribute("aria-current")).toBe("page");
    });
    expect(window.location.pathname).toBe(address);
    expect(document.querySelector("iframe")).toBeNull();
  });
});

describe("addresses that moved", () => {
  it.each([
    ["/production/next", "/production/overview"],
    ["/production/next/overview", "/production/overview"],
    ["/production/next/orders", "/production/orders"],
    ["/production/next/orders/new", "/production/orders/new"],
    ["/production/next/orders/3", "/production/orders/3"],
    ["/production/next/tasks", "/production/tasks"],
    ["/production/next/incoming", "/production/incoming"],
    ["/production/next/suppliers", "/production/suppliers"],
    ["/production/next/suppliers/fac", "/production/suppliers/fac"],
    ["/production/next/settings", "/production/settings"],
  ])("%s goes to %s", async (from, to) => {
    serveProduction(from);
    render(<App />);
    await waitFor(() => expect(window.location.pathname).toBe(to));
  });

  it("keeps the query on the way", async () => {
    serveProduction("/production/next/orders/3?open=sample");
    render(<App />);
    await waitFor(() => expect(window.location.pathname).toBe("/production/orders/3"));
    expect(window.location.search).toBe("?open=sample");
  });

  it.each(Object.entries(OLD_PAGES))("the framed app's /production/%s goes to %s", async (page, to) => {
    serveProduction(`/production/${page}`);
    render(<App />);
    await waitFor(() => expect(window.location.pathname).toBe(`/production/${to}`));
    expect(document.querySelector("iframe")).toBeNull();
  });

  it("sends an old order's address, with its code, to the orders list", async () => {
    serveProduction("/production/production-orders/PO-2611-03");
    render(<App />);
    await waitFor(() => expect(window.location.pathname).toBe("/production/orders"));
  });
});
