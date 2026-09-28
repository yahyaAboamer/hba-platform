// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { RankingContents } from "../MyRanking";
import { WardrobeContents } from "../MyWardrobe";

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
    uses: index + 1,
    sales_piastres: index === 5 ? 1071000 : 9999999,
  })),
};

describe("the redesigned ranking", () => {
  it("puts her nearby positions before leaders and shows only her own sales", () => {
    const html = renderToStaticMarkup(<RankingContents board={ranking} />);
    expect(html.indexOf("Around your position")).toBeLessThan(html.indexOf("Top of the board"));
    expect(html).toContain("EGP 10,710.00");
    expect(html).not.toContain("EGP 99,999.99");
    expect(html).toContain("Sales decide the order.");
  });

  it("opens the complete ordered board on request", () => {
    render(<RankingContents board={ranking} />);
    fireEvent.click(screen.getByRole("button", { name: "View full ranking" }));
    expect(screen.getByRole("heading", { name: "Full ranking" })).toBeTruthy();
    expect(screen.getAllByRole("listitem")).toHaveLength(8);
  });
});
