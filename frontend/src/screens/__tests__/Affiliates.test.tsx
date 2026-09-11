import { describe, expect, it } from "vitest";

import { contentSummary, rosterMatches, type Affiliate } from "../Affiliates";

const model = (over: Partial<Affiliate> = {}): Affiliate => ({
  id: 1,
  name: "Nour Hassan",
  phone: null,
  status: "active",
  account_kind: "model",
  is_payable: true,
  created_at: null,
  archived_at: null,
  code: "NOUR10",
  ...over,
});

describe("searching the roster", () => {
  it("finds her by name", () => {
    expect(rosterMatches([model()], "all", "nour")).toHaveLength(1);
  });

  it("finds her by the code an order knows her by", () => {
    // The case this exists for: somebody is holding an order with a code on
    // it and wants to know whose it is. A name-only search fails exactly then.
    expect(rosterMatches([model()], "all", "NOUR10")).toHaveLength(1);
    expect(rosterMatches([model()], "all", "nour10")).toHaveLength(1);
  });

  it("ignores surrounding space, which a paste brings with it", () => {
    expect(rosterMatches([model()], "all", "  nour  ")).toHaveLength(1);
  });

  it("returns everybody when nothing is typed", () => {
    expect(rosterMatches([model(), model({ id: 2 })], "all", "")).toHaveLength(2);
  });

  it("does not fall over on a model with no code yet", () => {
    expect(rosterMatches([model({ code: null })], "all", "zzz")).toHaveLength(0);
  });
});

describe("the roster segments", () => {
  const roster = [
    model({ id: 1, status: "active" }),
    model({ id: 2, status: "pending" }),
    model({ id: 3, status: "archived" }),
  ];

  it("shows everybody under All", () => {
    expect(rosterMatches(roster, "all", "")).toHaveLength(3);
  });

  it("narrows to the applications waiting to be approved", () => {
    const waiting = rosterMatches(roster, "waiting", "");
    expect(waiting.map((row) => row.id)).toEqual([2]);
  });

  it("keeps archived out of Active", () => {
    expect(rosterMatches(roster, "active", "").map((r) => r.id)).toEqual([1]);
  });

  it("combines a segment with a search rather than choosing between them", () => {
    const found = rosterMatches(
      [model({ id: 1, status: "pending", name: "Nour" }),
       model({ id: 2, status: "pending", name: "Salma", code: "SAL10" })],
      "waiting",
      "salma",
    );
    expect(found.map((row) => row.id)).toEqual([2]);
  });
});

describe("the content column", () => {
  it("shows videos and stories against what was asked for", () => {
    expect(contentSummary(model({
      content: { required_videos: 6, required_stories: 12, actual_videos: 5, actual_stories: 0, last_update: null },
    }))).toBe("5/6 · 0/12");
  });

  it("says nobody asked, rather than showing a zero she did not earn", () => {
    expect(contentSummary(model({
      content: { required_videos: null, required_stories: null, actual_videos: null, actual_stories: null, last_update: null },
    }))).toBe("Nothing asked for");
    expect(contentSummary(model({ content: null }))).toBe("Nothing asked for");
  });

  it("counts nothing produced as zero once something was asked for", () => {
    expect(contentSummary(model({
      content: { required_videos: 6, required_stories: 12, actual_videos: null, actual_stories: null, last_update: null },
    }))).toBe("0/6 · 0/12");
  });
});
