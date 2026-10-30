// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  PREVIEW_READ_ONLY,
  api,
  isPortalPreview,
  portalPath,
  startPortalPreview,
  stopPortalPreview,
} from "../../lib/api";
import type { Me } from "../../portal/MyDetails";
import { Measurements, Notifications, ShippingAddress } from "../../portal/MyDetails";
import { MyYou, YouPayout } from "../../portal/MyYou";
import { previewFrameFor } from "../../departments/affiliates/PortalPreview";

const ok = (body: unknown) =>
  Promise.resolve({
    ok: true,
    status: 200,
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const me: Me = {
  name: "Maya Nasser", phone: "01000000000", email: "maya@example.com",
  height_cm: 168, weight_kg: 62,
  shipping: { shipping_name: "Maya Nasser", shipping_phone: "01000000000", shipping_line1: "12 Example Street", shipping_line2: null, shipping_city: "Cairo", shipping_governorate: "Cairo", shipping_notes: null },
  status: "active", state: "active", arrangement: "commission", since: "2026-01",
  codes: [{ code: "MAYA10", verified: true }],
  payout_destination: { method: "instapay", instapay_address_url: "ipn.eg/maya" },
  required_fields: { instapay: ["instapay_address_url"] },
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(() => ok({}));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  stopPortalPreview();
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("her reads, in a preview (ADR 0064)", () => {
  // Paths held in lists rather than written into `api.get(...)`:
  // `tests/test_reachability.py` reads every such call in the interface,
  // tests included, as a request a screen makes.
  it("go to the preview's address for the model named", async () => {
    startPortalPreview(7);

    for (const read of ["/api/me", "/api/me/home/2026-09", "/api/me/best-sellers?month=2026-09", "/api/applications/mine"]) {
      await api.get(read);
    }

    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      "/api/affiliates/7/portal",
      "/api/affiliates/7/portal/home/2026-09",
      "/api/affiliates/7/portal/best-sellers?month=2026-09",
      "/api/affiliates/7/portal/application",
    ]);
  });

  it("leave everything else alone, and nothing changes without a preview", () => {
    expect(portalPath("/api/me/payments/3/proof")).toBe("/api/me/payments/3/proof");
    startPortalPreview(7);
    expect(portalPath("/api/me/payments/3/proof")).toBe("/api/affiliates/7/portal/payments/3/proof");
    expect(portalPath("/api/auth/me")).toBe("/api/auth/me");
    expect(portalPath("/api/members")).toBe("/api/members");
  });

  it("refuse every write before it is sent", async () => {
    startPortalPreview(7);

    const somewhere = "/api/me/measurements";
    for (const write of [
      () => api.put(somewhere, {}),
      () => api.post(somewhere),
      () => api.patch(somewhere, {}),
      () => api.del(somewhere),
      () => api.upload(somewhere, new Blob(["x"])),
    ]) {
      await expect(write()).rejects.toThrow(PREVIEW_READ_ONLY);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("never read her payout details in full", async () => {
    startPortalPreview(7);
    const unmasked = "/api/me/payout-destination";

    const refused = await api.get(unmasked).catch((caught) => caught);

    expect(refused).toBeInstanceOf(ApiError);
    expect((refused as ApiError).status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("her screens, in a preview", () => {
  it("offer no Sign out, which would sign the staff member out", () => {
    const own = renderToStaticMarkup(<MemoryRouter><MyYou me={me} workingMonth="2026-09" theme="dark" onTheme={() => undefined} /></MemoryRouter>);
    startPortalPreview(7);
    const preview = renderToStaticMarkup(<MemoryRouter><MyYou me={me} workingMonth="2026-09" theme="dark" onTheme={() => undefined} /></MemoryRouter>);

    expect(own).toContain("Sign out");
    expect(preview).not.toContain("Sign out");
    // Everything else she sees is still there.
    expect(preview).toContain("Where you are paid");
  });

  it("keep her payout shortened and offer no change", () => {
    startPortalPreview(7);
    render(<MemoryRouter><YouPayout me={me} onChanged={() => undefined} /></MemoryRouter>);

    expect(screen.getByText("Change where you are paid")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Change payment method" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Show them in full" })).toBeNull();
  });

  it("show her address and sizes with no button to edit them", () => {
    startPortalPreview(7);
    const html = renderToStaticMarkup(<>
      <ShippingAddress me={me} onChanged={() => undefined} />
      <Measurements me={me} onChanged={() => undefined} />
    </>);

    expect(html).toContain("12 Example Street");
    expect(html).toContain("168 cm");
    expect(html).not.toContain("Change it");
    expect(html).not.toContain("Change these");
  });

  it("show her notification switches as she set them, held still", async () => {
    fetchMock.mockImplementation(() => ok({ preferences: [
      { kind: "month_closed", label: "My month is closed", enabled: true },
      { kind: "paid", label: "I have been paid", enabled: false },
    ] }));
    startPortalPreview(7);
    render(<Notifications />);

    const switches = await waitFor(() => screen.getAllByRole("switch"));
    expect(switches.map((one) => one.getAttribute("aria-checked"))).toEqual(["true", "false"]);
    expect(switches.every((one) => (one as HTMLButtonElement).disabled)).toBe(true);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/affiliates/7/portal/notifications");
  });
});

describe("the frame's own address", () => {
  it("is recognised before routing, and nothing else is", () => {
    expect(previewFrameFor("/affiliates/models/12/portal/frame")).toBe(12);
    // The address it had before the frame: an old bookmark, or a tab left open.
    expect(previewFrameFor("/affiliates/12/portal/frame")).toBe(12);
    expect(previewFrameFor("/affiliates/models/12/portal")).toBeNull();
    expect(previewFrameFor("/affiliates/models/abc/portal/frame")).toBeNull();
    expect(isPortalPreview()).toBe(false);
  });
});
