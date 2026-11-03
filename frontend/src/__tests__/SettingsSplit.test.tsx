// @vitest-environment jsdom
/**
 * Settings split in four (Phase 2, Batch 2.3): who sees each Settings
 * section, what the owner's pages say to everybody else, every old
 * `?section=` link, the three pages that moved into Affiliates, and
 * Integrations (frame 6 of the approved mockup).
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { reply, serve, sessionOf } from "./frameHarness";
import type { Kind } from "./frameHarness";

beforeEach(() => {
  window.history.pushState({}, "", "/");
  // The Models roster asks for the width of the screen.
  window.matchMedia ??= ((query: string) => ({
    matches: false, media: query, addEventListener: () => undefined, removeEventListener: () => undefined,
    addListener: () => undefined, removeListener: () => undefined, onchange: null, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** What the page asks of the server beyond the frame's own answers. */
let seen: string[] = [];

async function open(
  address: string,
  kind: Kind = "owner",
  extra: (url: string) => Response | undefined = () => undefined,
) {
  window.history.pushState({}, "", address);
  serve(sessionOf(kind));
  const base = globalThis.fetch;
  seen = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      seen.push(url);
      return extra(url) ?? base(input, init);
    }),
  );
  render(<App />);
  await screen.findByRole("navigation", { name: "Departments" });
}

const here = () => window.location.pathname + window.location.search;
const settingsNav = () => screen.getByRole("list", { name: "Settings" });
const sectionsShown = () =>
  within(settingsNav()).getAllByRole("link").map((link) => link.textContent);

const NOT_THE_OWNERS = /This page is in Settings, and only the owner can open it\./;

describe("who sees each section of Settings", () => {
  it("shows the owner Me, Team and access, Integrations and Company", async () => {
    await open("/settings/me", "owner");
    expect(await screen.findByRole("heading", { name: "Me" })).toBeTruthy();
    expect(sectionsShown()).toEqual(["Me", "Team and access", "Integrations", "Company"]);
    expect(within(settingsNav()).getByRole("link", { name: "Me" }).getAttribute("aria-current")).toBe("page");
  });

  it.each<Kind>(["affiliate_manager", "content_manager", "operations_manager", "customer_service"])(
    "shows %s Me and nothing else",
    async (kind) => {
      await open("/settings", kind);
      expect(await screen.findByRole("heading", { name: "Me" })).toBeTruthy();
      expect(here()).toBe("/settings/me");
      expect(sectionsShown()).toEqual(["Me"]);
      // The Settings entry opens Me.
      expect(screen.getByRole("link", { name: "Settings" }).getAttribute("href")).toBe("/settings/me");
    },
  );

  it("gives a model no Settings at all: she gets her portal", async () => {
    await open("/settings/me", "model").catch(() => undefined);
    expect(screen.queryByRole("link", { name: "Settings" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Me" })).toBeNull();
  });
});

describe("the owner's pages, opened by anybody else", () => {
  const pages = ["/settings/team", "/settings/integrations", "/settings/company"];
  const others: Kind[] = ["affiliate_manager", "content_manager", "operations_manager", "customer_service"];

  for (const kind of others) {
    it.each(pages)(`say %s is not for ${kind}`, async (page) => {
      await open(page, kind);
      expect(await screen.findByRole("heading", { name: "Not available" })).toBeTruthy();
      expect(screen.getByText(NOT_THE_OWNERS)).toBeTruthy();
      // Nothing of the page was asked of the server.
      expect(seen.some((url) => url.includes("/api/integrations") || url.includes("/api/staff?") || url.endsWith("/api/staff"))).toBe(false);
    });
  }

  it.each([
    ["/settings/team", "Team and access"],
    ["/settings/integrations", "Integrations"],
    ["/settings/company", "Company"],
  ])("open for the owner: %s", async (page, heading) => {
    await open(page, "owner", (url) => {
      if (url.endsWith("/api/integrations")) return reply(200, { checked_at: new Date().toISOString(), connections: [] });
      if (url.includes("/api/audit")) return reply(200, { events: [], has_more: false, models: [], people: [], kinds: [] });
      if (url.includes("/api/policy/versions")) return reply(200, { versions: [] });
      if (url.endsWith("/api/staff")) return reply(200, { staff: [], invitations: [], assignable_roles: [], invitable_roles: [], role_permissions: {} });
      return undefined;
    });
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeTruthy();
    expect(within(settingsNav()).getByRole("link", { name: heading }).getAttribute("aria-current")).toBe("page");
  });
});

describe("Company", () => {
  it("shows the go-live month and reads the whole activity log, with no department", async () => {
    await open("/settings/company", "owner", (url) => {
      if (url.includes("/api/audit")) return reply(200, { events: [], has_more: false, models: [], people: [], kinds: [] });
      if (url.includes("/api/policy/versions")) return reply(200, { versions: [] });
      return undefined;
    });
    expect(await screen.findByText("Go-live month")).toBeTruthy();
    expect(screen.getByText("October 2026")).toBeTruthy();
    await waitFor(() => expect(seen.some((url) => url.startsWith("/api/audit?"))).toBe(true));
    expect(seen.filter((url) => url.startsWith("/api/audit?")).every((url) => !url.includes("department="))).toBe(true);
  });
});

describe("old /settings?section= links", () => {
  const owner: [string, string][] = [
    ["team", "/settings/team"],
    ["shopify", "/settings/integrations"],
    ["historical", "/affiliates/historical"],
    ["codes", "/affiliates/brand-codes"],
    ["policy", "/settings/company"],
    ["activity", "/settings/company"],
    ["advanced", "/settings/company"],
    ["appearance", "/settings/me"],
    ["no-such-thing", "/settings/me"],
  ];
  it.each(owner)("the owner's ?section=%s goes to %s", async (section, to) => {
    await open(`/settings?section=${section}`, "owner");
    await waitFor(() => expect(here()).toBe(to));
  });

  it("goes to Me when no section is named", async () => {
    await open("/settings", "owner");
    await waitFor(() => expect(here()).toBe("/settings/me"));
  });

  const manager: [string, string][] = [
    ["team", "/settings/me"],
    ["shopify", "/settings/me"],
    ["historical", "/affiliates/historical"],
    ["codes", "/affiliates/brand-codes"],
    ["policy", "/settings/me"],
    ["advanced", "/settings/me"],
    ["activity", "/affiliates/activity"],
  ];
  it.each(manager)("an affiliate manager's ?section=%s goes to %s", async (section, to) => {
    await open(`/settings?section=${section}`, "affiliate_manager");
    await waitFor(() => expect(here()).toBe(to));
  });

  it("keeps the other query keys", async () => {
    await open("/settings?section=activity&q=ayah&affiliate_id=12", "affiliate_manager");
    await waitFor(() => expect(here()).toBe("/affiliates/activity?q=ayah&affiliate_id=12"));
  });
});

describe("Brand codes, Historical setup and the activity log, inside Affiliates", () => {
  const answers = (url: string) => {
    if (url.includes("/api/audit")) return reply(200, { events: [], has_more: false, models: [], people: [], kinds: [] });
    if (url.includes("/api/payroll/historical/review")) return reply(200, { totals: { ready: 2, blocked: 0 } });
    return undefined;
  };

  it("opens Brand codes for anybody in Affiliates, counted as Models", async () => {
    await open("/affiliates/brand-codes", "content_manager", answers);
    expect(await screen.findByRole("heading", { level: 1, name: "Brand codes" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Models" }).getAttribute("aria-current")).toBe("page");
  });

  it("links to Brand codes from Models", async () => {
    await open("/affiliates/models", "affiliate_manager", answers);
    const link = await screen.findByRole("link", { name: /Brand codes/ });
    expect(link.getAttribute("href")).toBe("/affiliates/brand-codes");
  });

  it("opens Historical setup for whoever manages pay terms, counted as Payments", async () => {
    await open("/affiliates/historical", "affiliate_manager", answers);
    expect(await screen.findByRole("heading", { level: 1, name: "Historical setup" })).toBeTruthy();
    expect(screen.getByRole("link", { name: /^Payments/ }).getAttribute("aria-current")).toBe("page");
  });

  it("links to Historical setup from Payments while months are open", async () => {
    await open("/affiliates/payments", "affiliate_manager", answers);
    const link = await screen.findByRole("link", { name: /Historical setup/ });
    expect(link.getAttribute("href")).toBe("/affiliates/historical");
  });

  it("does not link to Historical setup once every month is final", async () => {
    await open("/affiliates/payments", "affiliate_manager", (url) =>
      url.includes("/api/payroll/historical/review") ? reply(200, { totals: { ready: 0, blocked: 0 } }) : answers(url));
    await screen.findByRole("heading", { name: "Payments" });
    await waitFor(() => expect(seen.some((url) => url.includes("/api/payroll/historical/review"))).toBe(true));
    expect(screen.queryByRole("link", { name: /Historical setup/ })).toBeNull();
  });

  it("opens the activity log narrowed to Affiliates, counted as Overview", async () => {
    await open("/affiliates/activity", "content_manager", answers);
    expect(await screen.findByRole("heading", { level: 1, name: "Activity log" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Overview" }).getAttribute("aria-current")).toBe("page");
    await waitFor(() =>
      expect(seen.some((url) => url.startsWith("/api/audit?") && url.includes("department=affiliates"))).toBe(true));
  });

  it("links to the activity log from Overview for whoever may read it", async () => {
    await open("/affiliates/overview", "content_manager", answers);
    const link = await screen.findByRole("link", { name: /Activity log/ });
    expect(link.getAttribute("href")).toBe("/affiliates/activity");
  });

  it("tells somebody outside Affiliates that those pages are not theirs", async () => {
    await open("/affiliates/activity", "operations_manager", answers);
    expect(await screen.findByRole("heading", { name: "Not available" })).toBeTruthy();
    expect(screen.getByText(/This page is in Affiliates, which your access does not include\./)).toBeTruthy();
  });
});

describe("Integrations", () => {
  const BODY = {
    checked_at: new Date().toISOString(),
    connections: [
      {
        key: "bosta", name: "Bosta", what: "Deliveries", used_by: "Used by Operations and order pages",
        state: "failed", why: "Bosta refused the key at 09:40. Paste a new key from Bosta's dashboard.",
        when_label: "Last read", when: "2026-11-03T07:38:00+00:00", key_form: "bosta",
      },
      {
        key: "shopify", name: "Shopify", what: "Orders, products and tags", used_by: "Used by Operations, Affiliates and Inbox",
        state: "working", why: null, when_label: "Read at", when: "2026-11-03T12:21:00+00:00", key_form: "shopify",
      },
      {
        key: "email", name: "Email", what: "Invitations, password resets, model emails", used_by: "Used by everyone",
        state: "never", why: null, when_label: "Last sent", when: null, key_form: null,
      },
    ],
  };
  const answers = (url: string) => {
    if (url.endsWith("/api/integrations")) return reply(200, BODY);
    if (url.includes("/api/order-ops/connections/bosta")) {
      return reply(200, {
        provider: "bosta", label: "Bosta", source: "saved", hint: "••••1234", verified_at: null,
        problem: null, can_save: true, key_problem: null,
      });
    }
    return undefined;
  };

  it("says how many connections there are and how many are not working", async () => {
    await open("/settings/integrations", "owner", answers);
    expect(await screen.findByText("3 connections · 1 is not working")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toMatch(/Checked just now/);
  });

  it("draws a failed row in the refused tone, with its why, its pill and Replace key", async () => {
    await open("/settings/integrations", "owner", answers);
    const row = (await screen.findByText("Bosta", { selector: "b" })).closest("li")!;
    expect(row.className).toContain("is-failed");
    expect(within(row).getByText("Used by Operations and order pages")).toBeTruthy();
    expect(within(row).getByText(/Bosta refused the key at 09:40/).className).toContain("why");
    expect(within(row).getByText("Not working").className).toContain("conns__pill--failed");
    expect(within(row).getByText(/^Last read /)).toBeTruthy();
    expect(within(row).getByRole("button", { name: /^Replace key/ }).textContent).toBe("Replace key");
  });

  it("draws a working row with Details, and a never-read one without a time", async () => {
    await open("/settings/integrations", "owner", answers);
    const shopify = (await screen.findByText("Shopify", { selector: "b" })).closest("li")!;
    expect(shopify.className).not.toContain("is-failed");
    expect(within(shopify).getByText("Working").className).not.toContain("failed");
    expect(within(shopify).getByRole("button", { name: /^Details/ }).textContent).toBe("Details");
    expect(within(shopify).getByText(/^Read at /)).toBeTruthy();
    const email = screen.getByText("Email", { selector: "b" }).closest("li")!;
    expect(within(email).getByText("Not read yet")).toBeTruthy();
    expect(email.querySelector(".when")?.textContent).toBe("");
  });

  it("opens the key form that exists today for that row", async () => {
    await open("/settings/integrations", "owner", answers);
    const row = (await screen.findByText("Bosta", { selector: "b" })).closest("li")!;
    fireEvent.click(within(row).getByRole("button", { name: /^Replace key/ }));
    // Operations' own key card: it says where the key comes from and offers to replace it.
    const detail = await screen.findByRole("region", { name: "Bosta details" });
    expect(await within(detail).findByRole("button", { name: "Replace key" })).toBeTruthy();
    fireEvent.click(within(detail).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("region", { name: "Bosta details" })).toBeNull();
  });

  it("says Email's key is set on the server, not here", async () => {
    await open("/settings/integrations", "owner", answers);
    const row = (await screen.findByText("Email", { selector: "b" })).closest("li")!;
    fireEvent.click(within(row).getByRole("button", { name: /^Details/ }));
    expect(await screen.findByText("This key is set on the server, not here.")).toBeTruthy();
  });

  it("says so when the list cannot be read", async () => {
    await open("/settings/integrations", "owner", (url) =>
      url.endsWith("/api/integrations") ? reply(500, { detail: "The list could not be built." }) : undefined);
    expect((await screen.findByRole("alert")).textContent).toContain("could not be built");
  });
});
