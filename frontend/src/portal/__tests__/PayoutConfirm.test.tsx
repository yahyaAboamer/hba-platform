// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MyPayout } from "../MyPayout";

/**
 * Decision h (owner, 25 September): the password is asked for after
 * *Save details*, and a failed confirmation neither saves the change nor
 * throws away what she typed.
 */
const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function fillWallet() {
  fireEvent.click(screen.getByRole("radio", { name: "Wallet" }));
  fireEvent.change(screen.getByLabelText("Which wallet"), { target: { value: "Vodafone Cash" } });
  fireEvent.change(screen.getByLabelText("Wallet number"), { target: { value: "01001234567" } });
}

describe("changing where she is paid", () => {
  it("chooses the method with the export's segment, in its order and words", () => {
    render(<MyPayout current={null} required={{ instapay: [], wallet: [], bank: [] }} onChanged={() => undefined} onCancel={() => undefined} />);
    expect(screen.getAllByRole("radio").map((r) => r.textContent)).toEqual(["InstaPay", "Wallet", "Bank"]);
    expect(screen.getByRole("button", { name: "Back" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Save details" })).toBeTruthy();
  });

  it("asks for the password after Save details, and a refused one saves nothing and keeps the form", async () => {
    fetchMock.mockImplementation(() => reply(403, { detail: "That password is not right." }));
    const onChanged = vi.fn();
    render(
      <MyPayout current={null} required={{ wallet: ["wallet_provider", "wallet_phone"] }}
        onChanged={onChanged} onCancel={() => undefined} />,
    );
    fillWallet();

    fireEvent.click(screen.getByRole("button", { name: "Save details" }));
    const password = screen.getByLabelText("Enter your password to confirm") as HTMLInputElement;
    fireEvent.change(password, { target: { value: "wrong-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("That password is not right."));
    expect(onChanged).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    // Only the password is cleared; the change she was confirming is still there.
    expect((screen.getByLabelText("Enter your password to confirm") as HTMLInputElement).value).toBe("");
    expect(screen.getByText(/After this change/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect((screen.getByLabelText("Wallet number") as HTMLInputElement).value).toBe("01001234567");
    expect((screen.getByLabelText("Which wallet") as HTMLSelectElement).value).toBe("Vodafone Cash");
    expect(screen.getByRole("radio", { name: "Wallet" }).getAttribute("aria-checked")).toBe("true");
  });

  it("saves only once the password is accepted", async () => {
    fetchMock.mockImplementation(() => reply(200, {}));
    const onChanged = vi.fn();
    render(
      <MyPayout current={null} required={{ wallet: ["wallet_provider", "wallet_phone"] }}
        onChanged={onChanged} onCancel={() => undefined} />,
    );
    fillWallet();
    fireEvent.click(screen.getByRole("button", { name: "Save details" }));
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Enter your password to confirm"), { target: { value: "right-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body)).toMatchObject({ method: "wallet", wallet_phone: "01001234567", password: "right-password" });
  });
});
