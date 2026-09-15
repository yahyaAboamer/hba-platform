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
    expect(rosterMatches([model()], "active", "nour")).toHaveLength(1);
  });

  it("finds her by the code an order knows her by", () => {
    // The case this exists for: somebody is holding an order with a code on
    // it and wants to know whose it is. A name-only search fails exactly then.
    expect(rosterMatches([model()], "active", "NOUR10")).toHaveLength(1);
    expect(rosterMatches([model()], "active", "nour10")).toHaveLength(1);
  });

  it("ignores surrounding space, which a paste brings with it", () => {
    expect(rosterMatches([model()], "active", "  nour  ")).toHaveLength(1);
  });

  it("returns the whole filter when nothing is typed", () => {
    expect(rosterMatches([model(), model({ id: 2 })], "active", "")).toHaveLength(2);
  });

  it("does not fall over on a model with no code yet", () => {
    expect(rosterMatches([model({ code: null })], "active", "zzz")).toHaveLength(0);
  });
});

describe("the roster filters, as the export names them", () => {
  const roster = [
    model({ id: 1, status: "active" }),
    model({ id: 2, status: "pending" }),
    model({ id: 3, status: "inactive" }),
    model({ id: 4, status: "archived" }),
  ];

  it("keeps everybody who is not working out of Active", () => {
    expect(rosterMatches(roster, "active", "").map((r) => r.id)).toEqual([1]);
  });

  it("narrows to the applications waiting to be approved", () => {
    expect(rosterMatches(roster, "applications", "").map((r) => r.id)).toEqual([2]);
  });

  it("puts paused and archived under one word, Inactive", () => {
    expect(rosterMatches(roster, "inactive", "").map((r) => r.id)).toEqual([3, 4]);
  });

  it("lists no models under Invitations, which lists invitations instead", () => {
    expect(rosterMatches(roster, "invitations", "")).toHaveLength(0);
  });

  it("combines a filter with a search rather than choosing between them", () => {
    const found = rosterMatches(
      [model({ id: 1, status: "pending", name: "Nour" }),
       model({ id: 2, status: "pending", name: "Salma", code: "SAL10" })],
      "applications",
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
