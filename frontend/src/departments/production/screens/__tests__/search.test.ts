import { describe, expect, it } from "vitest";

import { byUrgency, orderMatches, taskMatches } from "../search";
import { makeManual, makeRow, makeTask } from "./fixtures";

const FLAGS = { late: false, waiting_for_owner: false, count_mismatch: false, fix_pieces_due: false };

describe("Searching an order", () => {
  const row = makeRow({
    id: 7, style_name: "Boxy tee", colour: "Washed black", code: "PO-2611-07", colour_code: "BLK-02",
    fabric_type: "Single jersey", print_supplier_name: "Nile Print", notes: "Second run",
  });

  it("matches every field it is searched by, in any case", () => {
    for (const query of ["po-2611-07", "BOXY", "washed", "blk-02", "main factory", "nile", "jersey", "making", "second run"]) {
      expect(orderMatches(row, query), query).toBe(true);
    }
  });

  it("needs every word, in any order, and matches everything when empty", () => {
    expect(orderMatches(row, "  black   tee ")).toBe(true);
    expect(orderMatches(row, "tee hoodie")).toBe(false);
    expect(orderMatches(row, "   ")).toBe(true);
  });
});

describe("Searching a task", () => {
  it("looks through a typed task's note, next action and updates, but a worked-out task has none", () => {
    const typed = makeManual({
      id: 3, title: "Call the printer", note: "About the zip pullers", next_action: "Send the artwork",
      updates: [{ id: 1, text: "No answer on Sunday", next_action: null, created_at: null, created_by: null }],
    });
    for (const query of ["printer", "pullers", "artwork", "sunday"]) expect(taskMatches(typed, query), query).toBe(true);
    const generated = makeTask({ key: "order:1:cut", title: "Record cut quantities", waiting_on: "Main factory" });
    expect(taskMatches(generated, "main factory")).toBe(true);
    expect(taskMatches(generated, "pullers")).toBe(false);
  });
});

describe("The Overview's order", () => {
  it("puts late orders first (latest first), then those waiting for the owner, then the rest as they came", () => {
    const rows = [
      makeRow({ id: 1, style_name: "a" }),
      makeRow({ id: 2, style_name: "b", flags: { ...FLAGS, waiting_for_owner: true } }),
      makeRow({ id: 3, style_name: "c", lateness_days: 2, flags: { ...FLAGS, late: true } }),
      makeRow({ id: 4, style_name: "d" }),
      makeRow({ id: 5, style_name: "e", lateness_days: 9, flags: { ...FLAGS, late: true, waiting_for_owner: true } }),
    ];
    expect(byUrgency(rows).map((row) => row.id)).toEqual([5, 3, 2, 1, 4]);
  });
});
