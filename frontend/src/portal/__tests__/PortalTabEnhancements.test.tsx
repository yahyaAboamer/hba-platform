// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RankingContents } from "../MyRanking";
import { WardrobeContents } from "../MyWardrobe";
import { PortalSkeleton } from "../../components/PortalSkeleton";

afterEach(cleanup);

type Wardrobe = Parameters<typeof WardrobeContents>[0]["body"];
type Ranking = Parameters<typeof RankingContents>[0]["board"];

const item = (name: string, state: string, id: string) => ({
  shopify_product_id: id,
  title: name,
  size: "M",
  state,
  image_url: null,
  image_thumb_url: null,
  shopify_order_id: id,
});

describe("the redesigned wardrobe", () => {
  it("leads with owned and incoming pieces, then requests, then her own sales", () => {
    const body: Wardrobe = {
      received: [item("Wash Hoodie", "received", "hoodie")],
      processing: [item("Track Jacket", "processing", "jacket")],
      failed: [],
      feature_requests: [{ shopify_product_id: "hoodie", title: "Wash Hoodie", image_url: null, message: "Wear this next." }],
    };
    const best = [{ shopify_product_id: "hoodie", title: "Wash Hoodie", quantity: 2, sales_piastres: 30000, sales: "EGP 300.00", image_url: null }];
    const html = renderToStaticMarkup(<MemoryRouter><WardrobeContents body={body} best={best} codes={["SARAED"]} /></MemoryRouter>);

    expect(html.indexOf('id="wardrobe-owned"')).toBeLessThan(html.indexOf('id="wardrobe-feature"'));
    expect(html.indexOf('id="wardrobe-feature"')).toBeLessThan(html.indexOf('id="wardrobe-best"'));
    expect(html).toContain("On the way");
    expect(html).toContain("Product sales, not your payout.");
  });

  it("offers all-time and monthly best sellers with a chosen business month", () => {
    const body: Wardrobe = { received: [], processing: [], failed: [], feature_requests: [] };
    const best = [{ shopify_product_id: "hoodie", title: "Wash Hoodie", quantity: 2, sales_piastres: 30000, sales: "EGP 300.00", image_url: null }];
    const onPeriod = vi.fn();
    render(<MemoryRouter><WardrobeContents body={body} best={best} sellerPeriod="all" sellerMonth="2026-09" sellerMonths={["2026-09", "2026-08"]} onSellerPeriod={onPeriod} /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "Monthly" }));
    expect(onPeriod).toHaveBeenCalledWith("month");
    expect(screen.getByRole("button", { name: "All time" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("keeps the monthly filter visible when that month sold nothing", () => {
    const body: Wardrobe = { received: [], processing: [], failed: [], feature_requests: [] };
    const html = renderToStaticMarkup(<MemoryRouter><WardrobeContents body={body} best={[]} sellerPeriod="month" sellerMonth="2026-08" sellerMonths={["2026-08"]} onSellerPeriod={() => undefined} /></MemoryRouter>);
    expect(html).toContain("No products sold through your code in August 2026.");
    expect(html).toContain("Business month");
  });

  it("lets her choose a different month without changing the rest of Wardrobe", () => {
    const body: Wardrobe = { received: [], processing: [], failed: [], feature_requests: [] };
    const onMonth = vi.fn();
    render(<MemoryRouter><WardrobeContents body={body} best={[]} sellerPeriod="month" sellerMonth="2026-09" sellerMonths={["2026-09", "2026-08"]} onSellerPeriod={() => undefined} onSellerMonth={onMonth} /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Business month"), { target: { value: "2026-08" } });
    expect(onMonth).toHaveBeenCalledWith("2026-08");
    expect(screen.getByRole("heading", { name: "In your wardrobe" })).toBeTruthy();
  });
});

const ranking: Ranking = {
  month: "2026-09",
  basis: "sales",
  rows: Array.from({ length: 8 }, (_, index) => ({
    affiliate_id: index + 1,
    rank: index + 1,
    name: index === 5 ? "Sara Edrees" : `Model ${index + 1}`,
    code: `CODE${index + 1}`,
    is_me: index === 5,
    uses: index === 5 ? 6 : 9000 + index,
    sales_piastres: index === 5 ? 1071000 : 9999999,
    // Peer metrics may be present in an older response; the UI still hides them.
  })),
};

describe("the redesigned ranking", () => {
  it("shows all positions but only her own sales and uses", () => {
    const html = renderToStaticMarkup(<RankingContents board={ranking} />);
    expect(html).toContain("All models");
    expect(html).toContain("EGP 10,710.00");
    expect(html).not.toContain("EGP 99,999.99");
    expect(html).not.toContain("9000");
    expect(html).not.toContain("CODE1");
    expect(html).not.toContain("Code uses at right");
    expect(html).toContain("Sales decide the order.");
  });

  it("opens the complete ordered board immediately", () => {
    render(<RankingContents board={ranking} />);
    expect(screen.getByRole("heading", { name: "All models" })).toBeTruthy();
    expect(screen.getAllByRole("listitem")).toHaveLength(8);
  });
});

describe("tab loading states", () => {
  it("keeps each tab's heading and card or list shape visible", () => {
    for (const name of ["wardrobe", "targets", "ranking"] as const) {
      const html = renderToStaticMarkup(<PortalSkeleton screen={name} />);
      expect(html).toContain(`aria-label="Loading ${name}"`);
      expect(html).toContain('aria-busy="true"');
      expect(html).toContain("portal-skeleton__row");
    }
  });
});
