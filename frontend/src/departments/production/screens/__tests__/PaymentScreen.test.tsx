// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { departmentsFor } from "../../../index";
import { cairoToday } from "../format";
import { paymentsAddress, paymentsSentence, photoFailures, presetOf, presetRange } from "../paymentLogic";
import type { PaymentList, PaymentRow } from "../types";
import { mockApi, narrowScreen, owner, qc, renderAt, reply } from "./fixtures";
import type { Call } from "./fixtures";

const ADDRESS = "/production/payments";

const payment = (over: Partial<PaymentRow> & { id: number }): PaymentRow => ({
  supplier: { id: "SUP-1", name: "Main factory" },
  amount_piastres: 500000,
  paid_on: "2030-11-12",
  method: "cash",
  method_label: "Cash",
  kind: "weekly",
  kind_label: "Weekly payment",
  note: null,
  reversed: false,
  created_by: "Nour",
  photos: [],
  ...over,
});

const SUPPLIERS = [
  { id: "SUP-1", name: "Main factory" },
  { id: "SUP-4", name: "Delta Fabrics" },
];

const list = (payments: PaymentRow[]): PaymentList => ({
  from: null,
  to: null,
  total_piastres: payments.filter((one) => !one.reversed).reduce((sum, one) => sum + one.amount_piastres, 0),
  payments,
  suppliers: SUPPLIERS,
});

const rows = (): PaymentRow[] => [
  payment({ id: 12, note: "Week 46", photos: [{ id: 3, mime_type: "image/jpeg", size_bytes: 1234, created_at: null }, { id: 4, mime_type: "application/pdf", size_bytes: 99, created_at: null }] }),
  payment({ id: 11, supplier: { id: "SUP-4", name: "Delta Fabrics" }, amount_piastres: 120000, kind: "deposit", kind_label: "Deposit", method: "instapay", method_label: "InstaPay", paid_on: "2030-11-03", reversed: true }),
];

function serve(extra: Record<string, (body: unknown, call: Call) => unknown> = {}, payments: PaymentRow[] = rows()) {
  const state = { payments };
  const calls = mockApi({ "GET /api/prod/payments": () => list(state.payments), ...extra });
  return { calls, state };
}

const reads = (calls: Call[]) => calls.filter((call) => call.method === "GET" && call.path === "/api/prod/payments").map((call) => call.url);
const rowOf = (text: string) => screen.getByText(text).closest("tr, li") as HTMLElement;

beforeEach(() => narrowScreen(false));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("The Payments section", () => {
  it("is in the sidebar, between Suppliers and Stage days, only for the owner", () => {
    const sections = (session: ReturnType<typeof owner>) =>
      departmentsFor(session).find((department) => department.key === "production")?.sections.map((section) => section.label);
    expect(sections(owner())).toEqual(["Overview", "Orders", "Tasks", "Library", "Fabric", "Incoming", "Suppliers", "Billing", "Payments", "Stage days"]);
    expect(sections(qc())).not.toContain("Payments");
    expect(sections(qc())).toContain("Suppliers");
  });

  it("asks nothing and says so for somebody without the owner's permission", async () => {
    const { calls } = serve();
    renderAt(ADDRESS, qc());
    expect(await screen.findByText("Payments are for the owner and the production manager.")).toBeTruthy();
    expect(reads(calls)).toHaveLength(0);
  });
});

describe("The list", () => {
  it("starts on this month, and lists each payment with its photos; a reversed one is struck through", async () => {
    const { calls } = serve();
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Payments" });
    const month = presetRange("month", cairoToday());
    await waitFor(() => expect(reads(calls)).toEqual([`/api/prod/payments?from=${month.from}&to=${month.to}`]));
    expect(await screen.findByText("1 payment · EGP 5,000.00")).toBeTruthy();
    expect(screen.getByRole("button", { name: "This month" }).getAttribute("aria-pressed")).toBe("true");

    const paid = rowOf("Week 46");
    expect(within(paid).getByRole("link", { name: "Main factory" }).getAttribute("href")).toBe("/production/suppliers/SUP-1");
    expect(paid.textContent).toContain("12 Nov");
    expect(paid.textContent).toContain("Weekly payment");
    expect(paid.textContent).toContain("Cash");
    expect(paid.textContent).toContain("EGP 5,000.00");
    const photo = within(paid).getByRole("link", { name: /^Photo 1 of Weekly payment to Main factory/ });
    expect(photo.getAttribute("href")).toBe("/api/prod/receipts/3");
    expect(photo.getAttribute("target")).toBe("_blank");
    expect(photo.querySelector("img")!.getAttribute("src")).toBe("/api/prod/receipts/3");
    const pdf = within(paid).getByRole("link", { name: /^Photo 2 of/ });
    expect(pdf.textContent).toBe("PDF");
    expect(pdf.querySelector("img")).toBeNull();

    const reversed = screen.getByRole("link", { name: "Delta Fabrics" }).closest("tr, li") as HTMLElement;
    expect(reversed.textContent).toContain("Reversed");
    expect(reversed.querySelector("s")).toBeTruthy();
    // A reversed payment takes no photo.
    expect(within(reversed).queryByText("Add photos")).toBeNull();
  });

  it("changes the query with the quick periods, the dates and the supplier", async () => {
    const { calls } = serve();
    renderAt(ADDRESS, owner());
    await screen.findByText("Week 46");
    const today = cairoToday();

    fireEvent.click(screen.getByRole("button", { name: "Last month" }));
    const last = presetRange("last", today);
    await waitFor(() => expect(reads(calls).at(-1)).toBe(`/api/prod/payments?from=${last.from}&to=${last.to}`));
    expect(screen.getByRole("button", { name: "Last month" }).getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "All" }));
    await waitFor(() => expect(reads(calls).at(-1)).toBe("/api/prod/payments?"));

    fireEvent.change(screen.getByLabelText("Supplier"), { target: { value: "SUP-4" } });
    await waitFor(() => expect(reads(calls).at(-1)).toBe("/api/prod/payments?supplier=SUP-4"));

    const range = screen.getByRole("group", { name: "Paid between" });
    fireEvent.change(within(range).getByLabelText("From"), { target: { value: "2030-11-01" } });
    await waitFor(() => expect(reads(calls).at(-1)).toBe("/api/prod/payments?from=2030-11-01&supplier=SUP-4"));
    expect(screen.getByRole("button", { name: "All" }).getAttribute("aria-pressed")).toBe("false");

    // The wrong way round is said, and not asked for.
    const before = reads(calls).length;
    fireEvent.change(within(range).getByLabelText("To"), { target: { value: "2030-10-01" } });
    expect((await screen.findByRole("alert")).textContent).toBe("The From date is after the To date.");
    expect(reads(calls)).toHaveLength(before);
  });

  it("says so when the period holds none", async () => {
    serve({}, []);
    renderAt(ADDRESS, owner());
    expect(await screen.findByText("No payments in this period.")).toBeTruthy();
  });

  it("is cards on a phone", async () => {
    narrowScreen(true);
    serve();
    renderAt(ADDRESS, owner());
    await screen.findByText("Week 46");
    expect(screen.queryByRole("table")).toBeNull();
    expect(document.querySelectorAll("li.prod-card")).toHaveLength(2);
  });
});

describe("Recording a payment", () => {
  it("records it on the supplier, uploads each photo, says which one failed, and reads the list again", async () => {
    let uploads = 0;
    const { calls, state } = serve({
      "POST /api/prod/suppliers/SUP-4/payments": () => {
        state.payments = [payment({ id: 20, supplier: { id: "SUP-4", name: "Delta Fabrics" }, amount_piastres: 3000050 }), ...state.payments];
        return reply(201, { supplier: {}, entry_id: 20 });
      },
      "POST /api/prod/entries/20/photos": () => {
        uploads += 1;
        return uploads === 2 ? reply(422, { detail: "That file is not a photo or a PDF." }) : { payment: payment({ id: 20 }) };
      },
    });
    renderAt(ADDRESS, owner());
    await screen.findByText("Week 46");
    const open = screen.getByRole("button", { name: "Record payment" });
    fireEvent.click(open);
    const panel = screen.getByRole("heading", { name: "Record payment", level: 2 }).closest("section")!;

    fireEvent.click(within(panel).getByRole("button", { name: "Save payment" }));
    expect((await within(panel).findByRole("alert")).textContent).toBe("Choose the supplier.");

    fireEvent.change(within(panel).getByLabelText("Supplier"), { target: { value: "SUP-4" } });
    fireEvent.change(within(panel).getByLabelText("Amount, EGP"), { target: { value: "30,000.50" } });
    fireEvent.change(within(panel).getByLabelText("Paid by"), { target: { value: "instapay" } });
    fireEvent.change(within(panel).getByLabelText("What it is"), { target: { value: "deposit" } });
    fireEvent.change(within(panel).getByLabelText("Note, optional"), { target: { value: "Fleece deposit" } });
    expect((within(panel).getByLabelText("Date") as HTMLInputElement).value).toBe(cairoToday());
    const picker = within(panel).getByLabelText("Choose photos") as HTMLInputElement;
    expect(picker.multiple).toBe(true);
    expect(picker.accept).toBe("image/*,application/pdf");
    expect((within(panel).getByLabelText("Take a photo") as HTMLInputElement).getAttribute("capture")).toBe("environment");
    fireEvent.change(picker, { target: { files: [new File(["a"], "slip.jpg", { type: "image/jpeg" }), new File(["b"], "odd.heic")] } });
    expect(within(panel).getByRole("button", { name: /Remove\s*slip\.jpg/ })).toBeTruthy();

    fireEvent.click(within(panel).getByRole("button", { name: "Save payment" }));
    expect(
      await screen.findByText(
        "Payment recorded: EGP 30,000.50 to Delta Fabrics. A photo could not be added: odd.heic (That file is not a photo or a PDF.). Add it with Add photos.",
      ),
    ).toBeTruthy();
    const writes = calls.filter((call) => call.method !== "GET");
    expect(writes.map((call) => call.path)).toEqual(["/api/prod/suppliers/SUP-4/payments", "/api/prod/entries/20/photos", "/api/prod/entries/20/photos"]);
    expect(writes[0].body).toEqual({ amount_piastres: 3000050, paid_on: cairoToday(), method: "instapay", kind: "deposit", note: "Fleece deposit" });
    // The panel closes, focus goes back to its button, and the list is read again.
    expect(screen.queryByRole("heading", { name: "Record payment", level: 2 })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(open));
    await waitFor(() => expect(reads(calls)).toHaveLength(2));
  });
});

describe("A payment's photos", () => {
  it("adds photos to a payment, one upload each", async () => {
    const withPhoto = payment({ id: 12, note: "Week 46", photos: [{ id: 3, mime_type: "image/jpeg", size_bytes: 1, created_at: null }, { id: 9, mime_type: "image/png", size_bytes: 1, created_at: null }] });
    const { calls } = serve({ "POST /api/prod/entries/12/photos": () => ({ payment: withPhoto }) });
    renderAt(ADDRESS, owner());
    await screen.findByText("Week 46");
    const input = within(rowOf("Week 46")).getByLabelText(/^Add photos/) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["a"], "one.png", { type: "image/png" }), new File(["b"], "two.png", { type: "image/png" })] } });
    expect(await screen.findByText("2 photos added to Weekly payment to Main factory, 12 Nov.")).toBeTruthy();
    expect(calls.filter((call) => call.method === "POST").map((call) => call.path)).toEqual(["/api/prod/entries/12/photos", "/api/prod/entries/12/photos"]);
    expect(within(rowOf("Week 46")).getAllByRole("link", { name: /^Photo/ })).toHaveLength(2);
  });

  it("asks before removing one, and removes only that one", async () => {
    const { calls } = serve({
      "DELETE /api/prod/receipts/3": () => ({ payment: payment({ id: 12, note: "Week 46", photos: [{ id: 4, mime_type: "application/pdf", size_bytes: 99, created_at: null }] }) }),
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderAt(ADDRESS, owner());
    await screen.findByText("Week 46");
    const remove = () => within(rowOf("Week 46")).getByRole("button", { name: /^Remove photo 1 of Weekly payment/ });
    fireEvent.click(remove());
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(calls.filter((call) => call.method === "DELETE")).toHaveLength(0);

    fireEvent.click(remove());
    expect(await screen.findByText("Photo removed from Weekly payment to Main factory, 12 Nov.")).toBeTruthy();
    expect(calls.filter((call) => call.method === "DELETE").map((call) => call.path)).toEqual(["/api/prod/receipts/3"]);
    expect(within(rowOf("Week 46")).getAllByRole("link", { name: /^Photo/ })).toHaveLength(1);
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1, name: "Payments" }));
  });
});

describe("The payments' words", () => {
  it("knows each quick period from today", () => {
    expect(presetRange("month", "2030-02-14")).toEqual({ from: "2030-02-01", to: "2030-02-28" });
    expect(presetRange("last", "2030-01-14")).toEqual({ from: "2029-12-01", to: "2029-12-31" });
    expect(presetRange("year", "2030-01-14")).toEqual({ from: "2030-01-01", to: "2030-12-31" });
    expect(presetRange("all", "2030-01-14")).toEqual({ from: "", to: "" });
    expect(presetOf({ from: "2030-02-01", to: "2030-02-28" }, "2030-02-14")).toBe("month");
    expect(presetOf({ from: "2030-02-02", to: "2030-02-28" }, "2030-02-14")).toBeNull();
  });

  it("builds the address and the sentences", () => {
    expect(paymentsAddress({ from: "", to: "" }, "")).toBe("/api/prod/payments");
    expect(paymentsAddress({ from: "2030-11-01", to: "2030-11-30" }, "SUP-1")).toBe("/api/prod/payments?from=2030-11-01&to=2030-11-30&supplier=SUP-1");
    expect(paymentsSentence(2, 123400)).toBe("2 payments · EGP 1,234.00");
    expect(photoFailures([])).toBeNull();
    expect(photoFailures([{ name: "a.jpg", why: "" }, { name: "b.jpg", why: "Too big" }])).toBe("2 photos could not be added: a.jpg, b.jpg (Too big). Add them with Add photos.");
  });
});
