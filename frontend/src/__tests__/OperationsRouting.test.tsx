// @vitest-environment jsdom
/**
 * Where each person lands, and what they can reach (ADR 0057; ADR 0068).
 *
 * The operations manager holds Operations: no affiliate department in his
 * sidebar, and no request to the affiliate side's endpoints - a 403 that is
 * swallowed is still a door left on the latch.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { asked, serve, sessionOf } from "./frameHarness";

beforeEach(() => window.history.pushState({}, "", "/"));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the operations manager", () => {
  it("starts on Operations, on Shopify, with its four sections", async () => {
    serve(sessionOf("operations_only"));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Shopify" })).toBeTruthy();
    const sidebar = screen.getByRole("navigation", { name: "Departments" });
    expect(within(sidebar).getAllByRole("link").map((link) => link.textContent)).toEqual([
      "Shopify",
      "Bosta",
      "E-stebdal",
      "WhatsApp",
    ]);
  });

  it("sees nothing of the affiliate side, and asks it nothing", async () => {
    serve(sessionOf("operations_only"));
    render(<App />);
    await screen.findByRole("heading", { name: "Shopify" });

    expect(screen.queryByRole("button", { name: /Affiliates/ })).toBeNull();
    for (const name of ["Models", "Products", "Targets", "Payments", "Settings"]) {
      expect(screen.queryByRole("link", { name })).toBeNull();
    }
    const strayed = asked().filter(
      (url) => url.includes("/api/affiliates") || url.endsWith("/api/operations/counts"),
    );
    expect(strayed).toEqual([]);
  });

  it("is told the affiliate side is not his, from any old address", async () => {
    window.history.pushState({}, "", "/payments");
    serve(sessionOf("operations_only"));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Not available" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Go to your start" }).getAttribute("href")).toBe("/operations/shopify");
  });
});

describe("the admin", () => {
  it("holds Operations beside the affiliate side", async () => {
    serve(sessionOf("owner"));
    render(<App />);

    const operations = await screen.findByRole("button", { name: /^Operations/ });
    expect(operations.getAttribute("aria-expanded")).toBe("false");
  });

  it("reaches Operations at its own address", async () => {
    window.history.pushState({}, "", "/operations/bosta");
    serve(sessionOf("owner"));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Bosta" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Bosta" }).getAttribute("aria-current")).toBe("page");
  });
});

describe("the other managers", () => {
  it("have no way into Operations", async () => {
    window.history.pushState({}, "", "/operations/shopify");
    serve(sessionOf("affiliate_manager"));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Not available" })).toBeTruthy();
    expect(screen.getByText(/This page is in Operations, which your access does not include\./)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Operations/ })).toBeNull();
  });
});
