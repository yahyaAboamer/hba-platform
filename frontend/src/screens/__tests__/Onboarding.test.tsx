// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PasswordField } from "../../components/PasswordField";
import { AcceptInvitation } from "../AcceptInvitation";
import { ApplicationPending } from "../ApplicationPending";
import { Apply } from "../Apply";
import type { Me } from "../MyDetails";

/*
 * The owner's audit of the way in, 26 September: the 12-character rule the
 * server no longer had, sentences nobody needed, Outside Egypt that could not
 * be sent, and a waiting screen with nothing said big.
 */

const ok = (body: unknown, status = 200) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

let fetchMock: ReturnType<typeof vi.fn>;
let strength = 4;

beforeEach(() => {
  strength = 4;
  fetchMock = vi.fn((url: string) => {
    if (url.includes("/password-quality")) {
      return ok({ strength, problem: null, minimum: 8 });
    }
    if (url.includes("/invitations/preview")) {
      return ok({ email: "nour@example.com" });
    }
    if (url.includes("/applications/mine")) {
      return ok({ applied: false, status: null, required_fields: {} });
    }
    if (url.includes("/api/applications")) {
      return ok({ id: 1, status: "pending" }, 201);
    }
    return ok({});
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("choosing a password", () => {
  it("names the one rule and ticks it at eight characters, not twelve", async () => {
    const { rerender } = render(<PasswordField value="abcdefg" onChange={() => undefined} />);
    expect(screen.getByText("8+ characters").className).not.toContain("--met");

    rerender(<PasswordField value="abcdefgh" onChange={() => undefined} />);
    expect(screen.getByText("8+ characters").className).toContain("--met");
  });

  it("sums the meter up in one word, with no lecture under it", async () => {
    render(<PasswordField value="quiet harbour lantern" onChange={() => undefined} />);

    await waitFor(() => expect(screen.getByText("Strong")).toBeTruthy());
    expect(screen.queryByText(/Longer is what makes/)).toBeNull();
    expect(screen.queryByText(/to go/)).toBeNull();
  });

  it("lets an eight-character password continue on the invitation", async () => {
    strength = 1;
    render(
      <MemoryRouter initialEntries={["/accept-invitation?token=t0ken"]}>
        <AcceptInvitation onSignedIn={() => undefined} />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("nour@example.com")).toBeTruthy());
    expect(screen.queryByText(/we will ask for your details/)).toBeNull();

    const button = screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement;
    const box = screen.getByLabelText("Password");

    fireEvent.change(box, { target: { value: "abcdefg" } });
    expect(button.disabled).toBe(true);

    fireEvent.change(box, { target: { value: "abcdefgh" } });
    await waitFor(() => expect(button.disabled).toBe(false));
  });
});

describe("the details form", () => {
  async function openForm() {
    render(<Apply onApplied={() => undefined} />);
    await waitFor(() => expect(screen.getByText("Full name")).toBeTruthy());
  }

  it("drops 'your' from the labels and brackets 'optional'", async () => {
    await openForm();

    expect(screen.getByText("Discount code")).toBeTruthy();
    expect(screen.getByText("(optional)")).toBeTruthy();
    // The box titles - the page is still called "Your details".
    const labels = Array.from(document.querySelectorAll(".field__label"), (el) => el.textContent);
    expect(labels.filter((text) => text?.startsWith("Your"))).toEqual([]);
    expect(screen.queryByText(/Only so HBA sends you things that fit/)).toBeNull();
  });

  it("keeps the discount code's explanation behind the i", async () => {
    await openForm();
    expect(screen.queryByText(/The code customers type at checkout/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "About the discount code" }));
    expect(screen.getByText(/The code customers type at checkout/)).toBeTruthy();
  });

  it("folds the InstaPay guide until it is asked for", async () => {
    await openForm();
    expect(screen.queryByAltText(/InstaPay home screen/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Where do I find it?" }));
    expect(screen.getByAltText(/InstaPay home screen/)).toBeTruthy();
  });

  it("sends an application from outside Egypt, with no payment details", async () => {
    await openForm();

    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Nour Mahmoud" } });
    fireEvent.change(screen.getByLabelText("Phone number"), { target: { value: "01001234567" } });
    fireEvent.change(screen.getByLabelText("Discount code"), { target: { value: "NOUR10" } });
    // Something typed before switching must not travel with it.
    fireEvent.change(screen.getByLabelText("InstaPay number"), { target: { value: "01001234567" } });

    fireEvent.click(screen.getByLabelText("Outside Egypt"));
    expect(screen.queryByLabelText("InstaPay number")).toBeNull();

    const send = screen.getByRole("button", { name: "Send application" }) as HTMLButtonElement;
    expect(send.disabled).toBe(false);
    fireEvent.click(send);

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith("/api/applications") && (init as RequestInit)?.method === "POST",
        ),
      ).toBe(true),
    );
    const [, init] = fetchMock.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith("/api/applications") && (init as RequestInit)?.method === "POST",
    )!;
    const body = JSON.parse(String((init as RequestInit).body));
    expect(body.abroad).toBe(true);
    expect(body).not.toHaveProperty("payout_method");
    expect(body).not.toHaveProperty("instapay_phone");
  });
});

describe("waiting to be approved", () => {
  const me = (over: Partial<Me> = {}): Me =>
    ({
      name: "Mazen Fawzy",
      phone: "01001234567",
      email: "mazen@example.com",
      height_cm: null,
      weight_kg: null,
      shipping: {},
      status: "pending",
      state: "waiting",
      arrangement: null,
      since: null,
      codes: [{ code: "FITBROS10", verified: false }],
      payout_destination: {
        method: "bank",
        bank_name: "National Bank of Egypt",
        bank_account_number: "…0308",
      },
      required_fields: {},
      ...over,
    }) as Me;

  it("says the state big and shows where she is on the way", () => {
    render(<ApplicationPending me={me()} onChanged={() => undefined} />);

    expect(screen.getByRole("heading", { name: /checking your code/ })).toBeTruthy();
    expect(screen.getByText("In review")).toBeTruthy();
    expect(screen.getByText("Code approval")).toBeTruthy();
    expect(screen.getByText("Checking")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Change" })).toBeTruthy();
    expect(screen.queryByText(/Shortened on purpose/)).toBeNull();
  });

  it("says she is paid outside Egypt rather than that something is missing", () => {
    render(
      <ApplicationPending
        me={me({ payout_destination: null, payout_abroad: true })}
        onChanged={() => undefined}
      />,
    );

    expect(screen.getByText("Outside Egypt")).toBeTruthy();
    expect(screen.getByText("HBA will arrange it with you")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add" })).toBeTruthy();
  });
});
