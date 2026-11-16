// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockApi, narrowScreen, owner, qc, renderAt } from "./fixtures";

const settings = {
  stages: [
    { stage: "sample", label: "Sample", days: 7, updated_at: null, updated_by: null },
    { stage: "materials", label: "Materials", days: 7, updated_at: null, updated_by: null },
    { stage: "making", label: "Making", days: 17, updated_at: "2030-10-02T09:00:00Z", updated_by: "Nour" },
  ],
};

beforeEach(() => narrowScreen(false));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Stage days", () => {
  it("is read-only for somebody who is not the owner", async () => {
    mockApi({ "GET /api/prod/settings/stage-days": settings });
    renderAt("/production/settings", qc());
    expect(await screen.findByText("17 days")).toBeTruthy();
    expect(screen.getByText("2 Oct · Nour")).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("lets the owner change a number and save only what changed", async () => {
    const calls = mockApi({
      "GET /api/prod/settings/stage-days": settings,
      "PUT /api/prod/settings/stage-days": () => ({ stages: settings.stages.map((row) => (row.stage === "making" ? { ...row, days: 20 } : row)) }),
    });
    renderAt("/production/settings", owner());
    const making = (await screen.findByLabelText("Making, days")) as HTMLInputElement;
    const save = screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);

    fireEvent.change(making, { target: { value: "abc" } });
    fireEvent.click(save);
    expect((await screen.findByRole("alert")).textContent).toBe("Making: give a number of days from 0 to 365.");

    fireEvent.change(making, { target: { value: "20" } });
    fireEvent.click(save);
    await waitFor(() => expect(calls.filter((call) => call.method === "PUT")).toHaveLength(1));
    expect(calls.find((call) => call.method === "PUT")!.body).toEqual({ days: { making: 20 } });
    expect(await screen.findByText("Saved. New orders will use these days.")).toBeTruthy();
    expect((screen.getByLabelText("Making, days") as HTMLInputElement).value).toBe("20");
  });
});
