// @vitest-environment jsdom
/**
 * Production inside HBA's frame (ADR 0076, decision 6; the approved frame
 * `docs/design/hba-os-production-frame-2026-10-25.html`): HBA's sidebar folds
 * to the strip, Production's own screens fill the rest in a frame of their
 * own, and the address bar follows Production's navigation.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { appSource } from "../departments/production/ProductionScreens";
import { serve, sessionOf } from "./frameHarness";
import type { Kind } from "./frameHarness";

beforeEach(() => window.history.pushState({}, "", "/"));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function open(address: string, kind: Kind = "owner") {
  window.history.pushState({}, "", address);
  serve(sessionOf(kind), {});
  render(<App />);
  return screen.findByRole("navigation", { name: "HBA departments" });
}

describe("Production's frame", () => {
  it("maps HBA's address to Production's own", () => {
    expect(appSource("/production", "")).toBe("/production-app/");
    expect(appSource("/production/suppliers/SUP-1", "?tab=a")).toBe("/production-app/suppliers/SUP-1?tab=a");
  });

  it("folds HBA's sidebar to the strip and shows Production's screens beside it", async () => {
    const strip = await open("/production/production-orders");
    expect(document.querySelector(".frame__side")).toBeNull();
    expect(document.querySelector("iframe")!.getAttribute("src")).toBe("/production-app/production-orders");
    const production = within(strip).getByRole("link", { name: "Production" });
    expect(production.getAttribute("aria-current")).toBe("page");
    for (const name of [/^Today/, /^Inbox/, /^Operations/, /^Affiliates/, "Settings"]) {
      expect(within(strip).getByRole("link", { name })).toBeTruthy();
    }
  });

  it("opens the department names over Production and closes them with Esc", async () => {
    const strip = await open("/production");
    fireEvent.click(within(strip).getByRole("button", { name: "Show department names" }));
    const names = document.querySelector(".strip__flyout") as HTMLElement;
    expect(within(names).getByRole("link", { name: /^Inbox/ })).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(document.querySelector(".strip__flyout")).toBeNull();
  });

  it("follows Production's own navigation in the address bar without reloading it", async () => {
    await open("/production");
    const frame = document.querySelector("iframe")!;
    // Sent again on each try: on a slow machine the frame may start listening
    // only after the first message, which would then be lost.
    await waitFor(() => {
      act(() => {
        window.dispatchEvent(
          new MessageEvent("message", { origin: window.location.origin, data: { type: "production:path", path: "/samples" } }),
        );
      });
      expect(window.location.pathname).toBe("/production/samples");
    }, { timeout: 4000 });
    expect(frame.getAttribute("src")).toBe("/production-app/");
  });

  it("ignores a message from another site", async () => {
    await open("/production");
    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", { origin: "https://elsewhere.example", data: { type: "production:path", path: "/x" } }),
      );
    });
    expect(window.location.pathname).toBe("/production");
  });

  it("is where somebody holding only Production starts", async () => {
    window.history.pushState({}, "", "/");
    serve(sessionOf("production_staff"), {});
    render(<App />);
    await screen.findByRole("navigation", { name: "HBA departments" });
    expect(window.location.pathname).toBe("/production");
  });

  it("is a link in the full sidebar elsewhere", async () => {
    window.history.pushState({}, "", "/settings/me");
    serve(sessionOf("owner"), {});
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Departments" });
    expect(within(nav).getByRole("link", { name: "Production" }).getAttribute("href")).toBe("/production");
  });
});
