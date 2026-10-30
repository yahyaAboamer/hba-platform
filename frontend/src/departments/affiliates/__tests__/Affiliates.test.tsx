import { describe, expect, it } from "vitest";

import { contentSummary, missingSetup, needs, onePerAddress, rosterCsv, rosterMatches, sortRoster, type Affiliate, type Invited } from "../Affiliates";

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

describe("onePerAddress", () => {
  const invite = (over: Partial<Invited>): Invited => ({
    id: 1,
    email: "reem@example.com",
    expired: false,
    withdrawn: false,
    created_at: "2026-09-20T10:00:00Z",
    ...over,
  });

  it("keeps the live invitation when a resend lapsed the old one", () => {
    const rows = onePerAddress([
      invite({ id: 1, expired: true, created_at: "2026-09-20T10:00:00Z" }),
      invite({ id: 2, created_at: "2026-09-26T10:00:00Z" }),
    ]);
    expect(rows.map((row) => row.id)).toEqual([2]);
  });

  it("keeps the newest when none is live", () => {
    const rows = onePerAddress([
      invite({ id: 3, expired: true, created_at: "2026-09-26T10:00:00Z" }),
      invite({ id: 4, withdrawn: true, created_at: "2026-09-10T10:00:00Z" }),
    ]);
    expect(rows.map((row) => row.id)).toEqual([3]);
  });

  it("treats addresses that differ only in case as one person", () => {
    const rows = onePerAddress([
      invite({ id: 5, email: "Reem@Example.com", expired: true }),
      invite({ id: 6, email: "reem@example.com", created_at: "2026-09-26T10:00:00Z" }),
      invite({ id: 7, email: "dina@example.com" }),
    ]);
    expect(rows.map((row) => row.id).sort()).toEqual([6, 7]);
  });
});

describe("Needs you (admin Models audit)", () => {
  it("counts only what stops a live or applying model", () => {
    const noPayout = model({ id: 2, has_payout: false });
    const archived = model({ id: 3, status: "archived", has_payout: false });
    const house = model({ id: 4, account_kind: "house", is_payable: false, has_payout: false });
    expect(needs(noPayout, "payout")).toBe(true);
    expect(needs(archived, "payout")).toBe(false);
    expect(needs(house, "payout")).toBe(false);
    expect(needs(model({ status: "pending" }), "applications")).toBe(true);
    expect(needs(model({ status: "declined" }), "applications")).toBe(false);
  });

  it("names missing payout details on the row", () => {
    expect(missingSetup(model({ has_payout: false }))).toContain("no payout details");
    expect(missingSetup(model({ status: "declined", has_payout: false }))).toEqual([]);
  });

  it("finds a model by her sign-in email", () => {
    const rows = [model({ id: 1, email: "nour.h@example.com" }), model({ id: 2, name: "Salma", email: "s@example.com" })];
    expect(rosterMatches(rows, "active", "nour.h@").map((row) => row.id)).toEqual([1]);
  });
});

describe("sortRoster", () => {
  const a = model({ id: 1, name: "Zeina", sales_piastres: 100 });
  const b = model({ id: 2, name: "Amira", sales_piastres: 900 });
  it("sorts by name, and by sales highest first", () => {
    expect(sortRoster([a, b], "name").map((row) => row.id)).toEqual([2, 1]);
    expect(sortRoster([a, b], "sales").map((row) => row.id)).toEqual([2, 1]);
    expect(sortRoster([b, a], "sales").map((row) => row.id)).toEqual([2, 1]);
  });
});

describe("rosterCsv", () => {
  it("quotes a value with a comma and writes pounds, not piastres", () => {
    const csv = rosterCsv([model({ name: "Nour, the first", sales_piastres: 123456 })]);
    const [head, line] = csv.split("\n");
    expect(head.startsWith("Name,Code,Status")).toBe(true);
    expect(line.startsWith('"Nour, the first"')).toBe(true);
    expect(line).toContain("1234.56");
  });
});

describe("rosterCsv and formulas", () => {
  it("never lets a name she typed run as a spreadsheet formula", () => {
    const csv = rosterCsv([model({ name: '=HYPERLINK("http://x","y")', email: "@evil" })]);
    const line = csv.split("\n")[1];
    expect(line.startsWith(`"'=HYPERLINK(`)).toBe(true);
    expect(line).toContain(",'@evil,");
  });
});
