// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ContactForm } from "../ContactForm";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400, status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const CONTACT = {
  id: 7, name: "Sara Edrees", phone: "010 1000 2000", email: "sara@example.com",
  shipping: {
    shipping_name: null, shipping_phone: "01012864769", shipping_line1: "4 El Nasr Rd, Apt 3",
    shipping_line2: null, shipping_city: "Dokki", shipping_governorate: "Giza", shipping_notes: null,
  },
};

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const input = (label: string) => screen.getByLabelText(label) as HTMLInputElement;
const patches = () => fetchMock.mock.calls.filter(([, init]) => init?.method === "PATCH");

describe("Contact and shipping (item 14)", () => {
  it("shows the export's fields, with her sign-in shown and not editable", () => {
    render(<ContactForm contact={CONTACT} canEdit onSaved={() => undefined} />);
    expect(input("Full name").value).toBe("Sara Edrees");
    expect(input("Phone").value).toBe("010 1000 2000");
    expect(input("Shipping address").value).toBe("4 El Nasr Rd, Apt 3");
    expect(input("City").value).toBe("Dokki");
    expect(screen.getByText("sara@example.com").tagName).toBe("SPAN");
    expect(screen.queryByLabelText("Email")).toBeNull();
    expect(screen.queryByDisplayValue("sara@example.com")).toBeNull();
  });

  it("sends only what changed, never the sign-in, and says Saved", async () => {
    fetchMock.mockImplementation(() => reply(200, {}));
    const onSaved = vi.fn();
    render(<ContactForm contact={CONTACT} canEdit onSaved={onSaved} />);
    fireEvent.change(input("Full name"), { target: { value: "Sara Edrees Ali" } });
    fireEvent.change(input("City"), { target: { value: "Mohandessin" } });
    fireEvent.click(screen.getByRole("button", { name: "Save details" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(JSON.parse(patches()[0][1].body)).toEqual({
      name: "Sara Edrees Ali", shipping: { shipping_city: "Mohandessin" },
    });
    expect(screen.getByRole("button", { name: "Saved" })).toBeTruthy();
  });

  it("a refusal saves nothing and keeps every field as typed", async () => {
    fetchMock.mockImplementation(() => reply(400, { detail: "That does not look like an Egyptian mobile number. It should be 11 digits starting 010, 011, 012 or 015 - it is the number that goes on the parcel." }));
    render(<ContactForm contact={CONTACT} canEdit onSaved={() => undefined} />);
    fireEvent.change(input("Full name"), { target: { value: "Sara E." } });
    fireEvent.click(screen.getByRole("button", { name: "More address details" }));
    fireEvent.change(input("Phone on the parcel"), { target: { value: "12345" } });
    fireEvent.click(screen.getByRole("button", { name: "Save details" }));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Egyptian mobile"));
    expect(screen.getByRole("alert").textContent).toContain("Nothing was saved.");
    expect(input("Full name").value).toBe("Sara E.");
    expect(input("Phone on the parcel").value).toBe("12345");
  });

  it("refuses a blank name without asking the server", () => {
    render(<ContactForm contact={CONTACT} canEdit onSaved={() => undefined} />);
    fireEvent.change(input("Full name"), { target: { value: "  " } });
    fireEvent.click(screen.getByRole("button", { name: "Save details" }));
    expect(screen.getByRole("alert").textContent).toBe("A name is needed. Nothing was saved.");
    expect(patches()).toHaveLength(0);
  });

  it("is read-only for staff who may not change it", () => {
    render(<ContactForm contact={CONTACT} canEdit={false} onSaved={() => undefined} />);
    expect(screen.queryAllByRole("textbox")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /Save/ })).toBeNull();
    expect(screen.getByText("Sara Edrees")).toBeTruthy();
  });
});
