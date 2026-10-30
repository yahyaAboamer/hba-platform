// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../../lib/api";
import type { Me } from "../MyDetails";
import { Notifications } from "../MyDetails";
import { MyYou, YouGuide, YouPayout, YouSkeleton, YouTerms } from "../MyYou";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const base: Me = {
  name: "Maya Nasser", phone: "01000000000", email: "maya@example.com",
  height_cm: 168, weight_kg: 62,
  shipping: { shipping_name: "Maya Nasser", shipping_phone: "01000000000", shipping_line1: "12 Example Street", shipping_line2: null, shipping_city: "Cairo", shipping_governorate: "Cairo", shipping_notes: null },
  status: "active", state: "active", arrangement: "base_guarantee", since: "2026-01",
  codes: [{ code: "MAYA10", verified: true }],
  payout_destination: { method: "instapay", instapay_address_url: "ipn.eg/maya" },
  required_fields: { instapay: ["instapay_address_url"] },
};

function account(me: Me = base) {
  return renderToStaticMarkup(<MemoryRouter><MyYou me={me} workingMonth="2026-09" theme="dark" onTheme={() => undefined} /></MemoryRouter>);
}

describe("You account overview", () => {
  it("names the working month and groups the approved destinations", () => {
    const html = account();
    expect(html).toContain("Your terms · September 2026");
    expect(html).toContain('href="/you/payout"');
    expect(html).toContain('href="/payments"');
    expect(html).toContain('href="/you/details"');
    expect(html).toContain('href="/you/notifications"');
    expect(html).toContain('href="/you/guide"');
    expect(html).toContain("Cairo · Delivery address on file");
    expect(html).not.toContain("12 Example Street");
  });

  it("keeps payment history and account controls reachable while paused", () => {
    const html = account({ ...base, status: "inactive", state: "paused" });
    expect(html).toContain("Paused");
    expect(html).toContain('href="/payments"');
    expect(html).toContain('href="/you/notifications"');
    expect(html).toContain('href="/you/sizes"');
  });

  it("explains an abroad payment arrangement instead of calling it missing", () => {
    const html = account({ ...base, payout_destination: null, payout_abroad: true });
    expect(html).toContain("HBA arranges your payment directly");
    expect(html).not.toContain("Add where you are paid");
  });

  it("never assumes commission when terms are absent", () => {
    const html = account({ ...base, arrangement: null });
    expect(html).toContain("Your terms need HBA");
    expect(html).toContain("Not set yet");
    expect(html).not.toContain("You earn a share of eligible sales");
  });
});

describe("linked account pages", () => {
  it("opens payout as a summary before the password-protected editor", () => {
    render(<MemoryRouter><YouPayout me={base} onChanged={() => undefined} /></MemoryRouter>);
    expect(screen.getByText("Past payments stay accurate")).toBeTruthy();
    expect(screen.queryByText("Enter your password to confirm")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Change payment method" }));
    expect(screen.getByText("Where HBA should send your payment")).toBeTruthy();
  });

  it("keeps the guarantee conditional and the guide in plain language", () => {
    const terms = renderToStaticMarkup(<MemoryRouter><YouTerms me={base} workingMonth="2026-09" /></MemoryRouter>);
    const guide = renderToStaticMarkup(<MemoryRouter><YouGuide /></MemoryRouter>);
    expect(terms).toContain("met and HBA confirmed");
    expect(terms).toContain('href="/targets"');
    expect(guide).toContain("Why can sales and pay differ?");
    expect(guide).toContain("What if a target has no result yet?");
  });

  it("shows the account shape while loading", () => {
    const html = renderToStaticMarkup(<YouSkeleton />);
    expect(html).toContain('aria-label="Loading your account"');
    expect(html).toContain("you__sections");
  });

  it("retries notification choices after a failed load", async () => {
    vi.spyOn(api, "get")
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ preferences: [{ kind: "month_closed", label: "A month is closed", enabled: true }] });
    render(<Notifications />);
    expect(screen.getByRole("status", { name: "Loading notification choices" })).toBeTruthy();
    expect(await screen.findByText("Could not load your choices")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByText("Tell me when")).toBeTruthy());
    expect(screen.getByRole("switch", { name: "A month is closed" })).toBeTruthy();
  });
});
