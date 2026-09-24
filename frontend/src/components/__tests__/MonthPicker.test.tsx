// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { monthsBetween, platformMonths } from "../../lib/money";
import { MonthPicker } from "../MonthPicker";

afterEach(() => cleanup());

describe("the admin month control", () => {
  it("is the export's word and a select of the months it is given, newest first", () => {
    render(<MonthPicker value="2026-08" onChange={() => undefined} months={["2026-09", "2026-08", "2026-07"]} />);

    const select = screen.getByLabelText("Month") as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    expect(Array.from(select.options).map((o) => o.value)).toEqual(["2026-09", "2026-08", "2026-07"]);
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual(["September 2026", "August 2026", "July 2026"]);
    expect(select.value).toBe("2026-08");
  });

  it("keeps a month reached from outside the range on screen and in the list", () => {
    render(<MonthPicker value="2025-11" onChange={() => undefined} months={["2026-02", "2026-01"]} />);
    const select = screen.getByLabelText("Month") as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toEqual(["2026-02", "2026-01", "2025-11"]);
    expect(select.value).toBe("2025-11");
  });

  it("chooses any month offered, and still lets the page explain a marked one", () => {
    const onChange = vi.fn();
    const onLocked = vi.fn();
    render(
      <MonthPicker value="2026-09" onChange={onChange} months={["2026-09", "2026-08", "2026-01"]}
        lockFor={(m) => (m < "2026-08" ? "historical" : null)} onLockedClick={onLocked} />,
    );
    const select = screen.getByLabelText("Month");

    fireEvent.change(select, { target: { value: "2026-08" } });
    expect(onChange).toHaveBeenLastCalledWith("2026-08");
    expect(onLocked).not.toHaveBeenCalled();

    // A mark is information, not a prohibition: the month is chosen.
    fireEvent.change(select, { target: { value: "2026-01" } });
    expect(onChange).toHaveBeenLastCalledWith("2026-01");
    expect(onLocked).toHaveBeenCalledWith("2026-01", "historical");
  });

  it("is no grid: nothing to open, no legend", () => {
    const { container } = render(<MonthPicker value="2026-09" onChange={() => undefined} months={["2026-09"]} />);
    expect(container.querySelector("button")).toBeNull();
    expect(container.textContent).not.toContain("Before the platform");
  });

  it("has the profile's smaller size and no second label inside a field", () => {
    const { container } = render(
      <label>Effective from<MonthPicker value="2026-09" onChange={() => undefined} months={["2026-09"]} size="section" label={false} /></label>,
    );
    expect(container.querySelector(".month-picker--section")).toBeTruthy();
    expect(container.querySelectorAll("label")).toHaveLength(1);
    expect(screen.getByLabelText(/Effective from/).tagName).toBe("SELECT");
  });
});

describe("the months an admin control offers", () => {
  it("runs from the platform's first month to the end of its working year", () => {
    const months = platformMonths({ start_month: "2026-01", working_month: "2026-09" });
    expect(months[0] >= "2026-12").toBe(true);
    expect(months.at(-1)).toBe("2026-01");
    expect(months).toContain("2026-09");
    expect(months).not.toContain("2025-12");
    // Newest first, one of each.
    expect([...months].sort().reverse()).toEqual(months);
    expect(new Set(months).size).toBe(months.length);
  });

  it("counts inclusively across a year", () => {
    expect(monthsBetween("2025-11", "2026-02")).toEqual(["2026-02", "2026-01", "2025-12", "2025-11"]);
    expect(monthsBetween("2026-03", "2026-03")).toEqual(["2026-03"]);
  });
});
