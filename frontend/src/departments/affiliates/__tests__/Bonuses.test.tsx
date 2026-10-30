// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Session } from "../../lib/api";
import { Bonuses } from "../Bonuses";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400, status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const MANAGER = { actor: {}, permissions: ["affiliates.view", "payroll.bonus"], platform: {} } as unknown as Session;
const VIEWER = { actor: {}, permissions: ["affiliates.view"], platform: {} } as unknown as Session;

const ROWS = {
  bonuses: [
    {
      id: 7, month: "2026-10", amount_piastres: 50_000, amount: "EGP 500.00",
      reason: "Eid campaign", added_by: "Owner", added_at: "2026-10-20T10:00:00Z",
      withdrawn_by: null, withdrawn_at: null, can_withdraw: true,
    },
  ],
};

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => { fetchMock = vi.fn(() => reply(200, ROWS)); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const at = (session: Session, open = false) => render(
  <Bonuses affiliateId="3" name="Nour" month="2026-10" session={session}
    open={open} onOpened={() => {}} onChanged={() => {}} />,
);

describe("Bonuses (ADR 0070)", () => {
  it("lists her bonuses with the staff-only reason", async () => {
    at(VIEWER);
    expect(await screen.findByText("“Eid campaign”")).toBeTruthy();
    expect(screen.getByText("EGP 500.00")).toBeTruthy();
  });

  it("offers nothing to change without the permission", async () => {
    at(VIEWER);
    await screen.findByText("“Eid campaign”");
    expect(screen.queryByRole("button", { name: "Add bonus" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Withdraw" })).toBeNull();
  });

  it("sends whole pounds as piastres, with the month and reason", async () => {
    at(MANAGER, true);
    const amount = await screen.findByRole("textbox", { name: "Amount (EGP)" });
    fireEvent.change(amount, { target: { value: "750" } });
    fireEvent.change(screen.getByRole("textbox", { name: /^Reason \(optional\)/ }), { target: { value: "Extra shoot" } });
    fetchMock.mockImplementationOnce(() => reply(201, { id: 8 }));

    fireEvent.click(screen.getByRole("button", { name: "Add EGP 750 bonus" }));

    await waitFor(() => {
      const posted = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
      expect(posted?.[0]).toBe("/api/affiliates/3/bonuses");
      const body = JSON.parse(posted?.[1].body);
      expect(body).toMatchObject({ month: "2026-10", amount_piastres: 75_000, reason: "Extra shoot" });
      expect(body.operation_key).toMatch(/^bonus:3:/);
    });
  });

  it("will not send pounds and piastres", async () => {
    at(MANAGER, true);
    const amount = await screen.findByRole("textbox", { name: "Amount (EGP)" });
    fireEvent.change(amount, { target: { value: "12.5" } });
    // The field keeps digits only, so 12.5 becomes 125 - never a fraction.
    expect((amount as HTMLInputElement).value).toBe("125");
  });
});
