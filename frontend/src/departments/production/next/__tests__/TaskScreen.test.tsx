// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Session } from "../../../../lib/api";
import type { ManualTask, Task } from "../types";
import { makeManual, makeRow, makeTask, makeTaskList, mockApi, narrowScreen, owner, qc, renderAt, reply } from "./fixtures";
import type { Call } from "./fixtures";
import { makeSupplierPage } from "./supplierFixtures";

const ADDRESS = "/production/next/tasks";

const ZIP = { id: 2, code: "PO-2611-03", style_name: "Zip hoodie", colour: "Olive" };
const SWEATPANTS = { id: 4, code: "PO-2611-01", style_name: "Wide-leg sweatpants", colour: "Grey" };

/** Seven open tasks, one of each kind, across all four groups. */
const tasks = (): Task[] => [
  makeTask({ key: "order:2:stage:sample", title: "Approve the sample", who: "owner", order: ZIP, stage: "sample", group: "overdue", overdue_days: 3, due: "2030-11-10", since: "2030-11-10", open: "sample" }),
  makeTask({ key: "delivery:7:reason", title: "Give a reason for 1 missing piece", due: "2030-11-12", group: "overdue", overdue_days: 1, stage: "warehouse", open: "delivery-reason:7" }),
  makeManual({ id: 5, title: "Visit the new print house", due: "2030-11-13", group: "today" }),
  makeTask({ key: "order:4:stage:cutting", title: "Record cut quantities", order: SWEATPANTS, stage: "cutting", due: "2030-11-15", open: "cut" }),
  makeTask({ key: "order:1:fix", title: "Receive 30 fix pieces", who: "factory", waiting_on: "Main factory", since: "2030-11-10", due: "2030-11-17", stage: "warehouse", open: "delivery" }),
  makeTask({ key: "order:1:stage:sample", title: "Factory to send the changed sample", who: "factory", waiting_on: "Main factory", order: ZIP, due: "2030-11-20", group: "later", stage: "sample", open: null }),
  makeTask({ key: "order:1:stage:making", title: "Final inspection", due: "2030-11-26", group: "later", stage: "making", open: "stage:making" }),
];

const readOnly = (): Session => {
  const reader = qc();
  reader.permissions = ["production.view"];
  return reader;
};

const openOrders = {
  orders: [
    makeRow({ id: 4, code: "PO-2611-01", style_name: "Wide-leg sweatpants", colour: "Grey" }),
    makeRow({ id: 2, code: "PO-2611-03", style_name: "Zip hoodie", colour: "Olive" }),
  ],
};

/** The tasks as the server keeps them: a write to a hand-added task changes the next read. */
function serve(initial: Task[] = tasks(), extra: Record<string, (body: unknown, call: Call) => unknown> = {}) {
  const state = { tasks: initial };
  const calls = mockApi({
    "GET /api/prod/tasks": () => makeTaskList(state.tasks),
    "GET /api/prod/orders": openOrders,
    ...extra,
  });
  return { calls, state };
}

const writes = (calls: Call[]) => calls.filter((call) => call.method !== "GET");
const rowOf = (title: string): HTMLElement => screen.getByText(title).closest("li")!;
const formOf = (name: string): HTMLElement => screen.getByRole("heading", { name, level: 2 }).closest("section")!;

beforeEach(() => narrowScreen(false));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("The Tasks screen", () => {
  it("shows the four groups in order, each task with its order, who, date and button", async () => {
    serve();
    renderAt(ADDRESS, owner());
    expect(await screen.findByRole("heading", { level: 1, name: "Tasks" })).toBeTruthy();
    expect(screen.getByText("7 open · 2 overdue · 1 for today, Wednesday 13 Nov")).toBeTruthy();
    expect(screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent)).toEqual(["Overdue", "Today", "This week", "Later"]);

    const sample = rowOf("Approve the sample");
    expect(sample.textContent).toContain("Zip hoodie · Olive · PO-2611-03");
    expect(sample.textContent).toContain("waiting 3 days");
    expect(sample.textContent).toContain("Owner");
    expect(sample.textContent).toContain("10 Nov · 3 days");
    expect(within(sample).getByRole("link", { name: "Review sample: Approve the sample" }).getAttribute("href")).toBe("/production/next/orders/2?open=sample");

    const fix = rowOf("Receive 30 fix pieces");
    expect(fix.textContent).toContain("waiting on Main factory for 3 days");
    expect(fix.textContent).toContain("Factory");
    expect(fix.textContent).toContain("17 Nov");
    expect(within(fix).getByRole("link", { name: /^Record delivery/ }).getAttribute("href")).toBe("/production/next/orders/1?open=delivery");

    expect(rowOf("Final inspection").textContent).toContain("around 26 Nov");
    expect(rowOf("Visit the new print house").textContent).toContain("Added by hand · no order");
    const reason = rowOf("Give a reason for 1 missing piece");
    expect(within(reason).getByRole("link", { name: /^Add reason/ }).getAttribute("href")).toBe("/production/next/orders/1?open=delivery-reason:7");
    expect(within(rowOf("Record cut quantities")).getByRole("link", { name: /^Enter counts/ })).toBeTruthy();
    // Work with nothing to fill in goes to the order.
    expect(within(rowOf("Factory to send the changed sample")).getByRole("link", { name: /^Open order/ }).getAttribute("href")).toBe("/production/next/orders/2");
  });

  it("filters with a count on each chip", async () => {
    serve();
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Tasks" });
    for (const name of ["Everything · 7", "Overdue · 2", "QC manager · 4", "Owner · 1", "Waiting on suppliers · 2"]) {
      expect(screen.getByRole("button", { name })).toBeTruthy();
    }
    expect(screen.getByRole("button", { name: "Everything · 7" }).getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Overdue · 2" }));
    expect(screen.getByRole("button", { name: "Overdue · 2" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("Approve the sample")).toBeTruthy();
    expect(screen.getByText("Give a reason for 1 missing piece")).toBeTruthy();
    expect(screen.queryByText("Record cut quantities")).toBeNull();
    expect(screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent)).toEqual(["Overdue"]);

    fireEvent.click(screen.getByRole("button", { name: "Waiting on suppliers · 2" }));
    expect(screen.getByText("Receive 30 fix pieces")).toBeTruthy();
    expect(screen.getByText("Factory to send the changed sample")).toBeTruthy();
    expect(screen.queryByText("Approve the sample")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Owner · 1" }));
    expect(screen.getByText("Approve the sample")).toBeTruthy();
    expect(screen.queryByText("Receive 30 fix pieces")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "QC manager · 4" }));
    expect(screen.getByText("Visit the new print house")).toBeTruthy();
    expect(screen.queryByText("Approve the sample")).toBeNull();
  });

  it("says so when a filter, or the whole list, is empty", async () => {
    serve([makeTask({ key: "k", title: "Record cut quantities", open: "cut" })]);
    renderAt(ADDRESS, owner());
    await screen.findByText("Record cut quantities");
    fireEvent.click(screen.getByRole("button", { name: "Owner · 0" }));
    expect(screen.getByText("Nothing is waiting on the owner.")).toBeTruthy();
    cleanup();
    serve([]);
    renderAt(ADDRESS, owner());
    expect(await screen.findByText("Nothing to do right now.")).toBeTruthy();
    expect(screen.getByText("0 open · 0 for today, Wednesday 13 Nov")).toBeTruthy();
  });

  it("shows a refusal, and tries again", async () => {
    let failing = true;
    mockApi({ "GET /api/prod/tasks": () => (failing ? reply(500, { detail: "The tasks are not available." }) : makeTaskList([])) });
    renderAt(ADDRESS, owner());
    expect((await screen.findByRole("alert")).textContent).toBe("The tasks are not available.");
    failing = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Nothing to do right now.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("The two purchase tasks", () => {
  const purchaseTasks = (): Task[] => [
    makeTask({
      key: "purchase:1:chase", title: "Chase the Heavy fleece, black delivery", who: "factory", waiting_on: "Main factory", since: "2030-11-09",
      due: "2030-11-12", group: "overdue", overdue_days: 1, open: "purchase:1", supplier: { id: "fac", name: "Main factory" },
    }),
    makeTask({
      key: "purchase:2:arrival", title: "Check Zips on arrival", who: "qc", due: "2030-11-19", group: "week", since: "2030-11-13",
      open: "purchase:2", supplier: { id: "fac", name: "Main factory" },
    }),
  ];

  it("reads Mark received and opens that purchase on its supplier's page", async () => {
    serve(purchaseTasks());
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Tasks" });
    const chase = within(rowOf("Chase the Heavy fleece, black delivery")).getByRole("link", { name: /^Mark received/ });
    expect(chase.getAttribute("href")).toBe("/production/next/suppliers/fac?open=purchase:1");
    const arrival = within(rowOf("Check Zips on arrival")).getByRole("link", { name: /^Mark received/ });
    expect(arrival.getAttribute("href")).toBe("/production/next/suppliers/fac?open=purchase:2");
    // The title carries no money, and neither does the row.
    expect(document.body.textContent).not.toMatch(/EGP/);
  });

  it("gives somebody who can only read the supplier, never a button that writes", async () => {
    serve(purchaseTasks());
    renderAt(ADDRESS, readOnly());
    await screen.findByRole("heading", { level: 1, name: "Tasks" });
    expect(screen.queryByRole("link", { name: /^Mark received/ })).toBeNull();
    expect(within(rowOf("Check Zips on arrival")).getByRole("link", { name: /^Open supplier/ }).getAttribute("href")).toBe("/production/next/suppliers/fac");
  });

  it("goes to the supplier's page, and the page opens the form", async () => {
    mockApi({
      "GET /api/prod/tasks": () => makeTaskList(purchaseTasks()),
      "GET /api/prod/suppliers/fac": { supplier: makeSupplierPage({}, false) },
    });
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Tasks" });
    fireEvent.click(within(rowOf("Chase the Heavy fleece, black delivery")).getByRole("link", { name: /^Mark received/ }));
    expect(await screen.findByRole("heading", { level: 2, name: "Mark Heavy fleece, black received" })).toBeTruthy();
  });
});

describe("A task's button, by who is looking", () => {
  it("gives the QC manager the forms they use, and the order for the owner's", async () => {
    serve();
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Tasks" });
    expect(within(rowOf("Approve the sample")).getByRole("link", { name: /^Open order/ }).getAttribute("href")).toBe("/production/next/orders/2");
    expect(within(rowOf("Approve the sample")).queryByRole("link", { name: /^Review sample/ })).toBeNull();
    expect(within(rowOf("Give a reason for 1 missing piece")).getByRole("link", { name: /^Add reason/ })).toBeTruthy();
    expect(within(rowOf("Final inspection")).getByRole("link", { name: /^Mark finished/ }).getAttribute("href")).toBe("/production/next/orders/1?open=stage:making");
    // The QC manager writes hand-added tasks.
    expect(screen.getByRole("button", { name: "Add task" })).toBeTruthy();
    expect(within(rowOf("Visit the new print house")).getByRole("button", { name: /^Mark done/ })).toBeTruthy();
  });

  it("gives somebody who can only read the order for every task, and nothing that writes", async () => {
    serve();
    renderAt(ADDRESS, readOnly());
    await screen.findByRole("heading", { level: 1, name: "Tasks" });
    for (const title of ["Approve the sample", "Give a reason for 1 missing piece", "Record cut quantities", "Receive 30 fix pieces", "Final inspection"]) {
      expect(within(rowOf(title)).getByRole("link", { name: /^Open order/ })).toBeTruthy();
    }
    expect(screen.queryByRole("link", { name: /^(Add reason|Enter counts|Review sample|Record delivery|Mark finished)/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^(Add task|Mark done|Edit|Delete)/ })).toBeNull();
    expect(within(rowOf("Visit the new print house")).queryAllByRole("button")).toHaveLength(0);
  });
});

describe("Adding a task", () => {
  it("asks for a title before sending anything", async () => {
    const { calls } = serve();
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Tasks" });
    fireEvent.click(screen.getByRole("button", { name: "Add task" }));
    const form = formOf("Add task");
    fireEvent.click(within(form).getByRole("button", { name: "Add task" }));
    expect((await within(form).findByRole("alert")).textContent).toBe("Give the task's title.");
    expect(writes(calls)).toHaveLength(0);
  });

  it("sends the title, date, order, note and who it is for, then shows it", async () => {
    const { calls, state } = serve(tasks(), {
      "POST /api/prod/tasks": (body) => {
        const sent = body as { title: string; due_on: string; order_id: number; note: string; for_owner: boolean };
        const made = makeManual({ id: 9, title: sent.title, due: sent.due_on, note: sent.note, for_owner: sent.for_owner, who: "owner", group: "week", order: ZIP });
        state.tasks = [...state.tasks, made];
        return { task: made };
      },
    });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Tasks" });
    const add = screen.getByRole("button", { name: "Add task" });
    fireEvent.click(add);
    const form = formOf("Add task");
    // The orders still in production are offered, and nothing else.
    await within(form).findByRole("option", { name: "Zip hoodie · Olive · PO-2611-03" });
    expect(within(form).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "No order", "Wide-leg sweatpants · Grey · PO-2611-01", "Zip hoodie · Olive · PO-2611-03",
    ]);

    fireEvent.change(within(form).getByLabelText("Task"), { target: { value: "  Call the zip supplier " } });
    fireEvent.change(within(form).getByLabelText("Date (optional)"), { target: { value: "2030-11-20" } });
    fireEvent.change(within(form).getByLabelText("Order (optional)"), { target: { value: "2" } });
    fireEvent.change(within(form).getByLabelText("Note (optional)"), { target: { value: "Ask about the minimum" } });
    fireEvent.click(within(form).getByLabelText("For the owner"));
    fireEvent.click(within(form).getByRole("button", { name: "Add task" }));

    expect(await screen.findByText("Added: Call the zip supplier")).toBeTruthy();
    expect(writes(calls)).toEqual([
      expect.objectContaining({
        method: "POST",
        path: "/api/prod/tasks",
        body: { title: "Call the zip supplier", due_on: "2030-11-20", order_id: 2, note: "Ask about the minimum", for_owner: true },
      }),
    ]);
    // The form closes, the list is read again, and focus goes back to the button that opened it.
    expect(screen.queryByRole("heading", { name: "Add task", level: 2 })).toBeNull();
    expect(rowOf("Call the zip supplier").textContent).toContain("Ask about the minimum");
    expect(rowOf("Call the zip supplier").textContent).toContain("Zip hoodie · Olive · PO-2611-03 · Added by hand");
    await waitFor(() => expect(document.activeElement).toBe(add));
  });

  it("shows the server's own words when it refuses, and keeps what was typed", async () => {
    serve(tasks(), { "POST /api/prod/tasks": () => reply(422, { detail: "Pick an order that is still in production." }) });
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Tasks" });
    fireEvent.click(screen.getByRole("button", { name: "Add task" }));
    const form = formOf("Add task");
    fireEvent.change(within(form).getByLabelText("Task"), { target: { value: "Check the labels" } });
    fireEvent.click(within(form).getByRole("button", { name: "Add task" }));
    expect((await within(form).findByRole("alert")).textContent).toBe("Pick an order that is still in production.");
    expect((within(form).getByLabelText("Task") as HTMLInputElement).value).toBe("Check the labels");
    // Esc closes the form.
    fireEvent.keyDown(within(form).getByLabelText("Task"), { key: "Escape" });
    expect(screen.queryByRole("heading", { name: "Add task", level: 2 })).toBeNull();
  });
});

describe("A hand-added task", () => {
  const typed = (): ManualTask => makeManual({ id: 5, title: "Visit the new print house", due: "2030-11-13", group: "today", note: "Ask about minimums" });

  it("is marked done, and the list and its counts are read again", async () => {
    const { calls, state } = serve(tasks(), {
      "PATCH /api/prod/tasks/5": () => {
        state.tasks = state.tasks.filter((task) => task.key !== "task:5");
        return { task: { ...typed(), done: true, group: "done" } };
      },
    });
    renderAt(ADDRESS, qc());
    await screen.findByText("Visit the new print house");
    fireEvent.click(within(rowOf("Visit the new print house")).getByRole("button", { name: "Mark done: Visit the new print house" }));
    expect(await screen.findByText("Marked done: Visit the new print house")).toBeTruthy();
    expect(writes(calls)).toEqual([expect.objectContaining({ method: "PATCH", path: "/api/prod/tasks/5", body: { done: true } })]);
    await waitFor(() => expect(screen.queryByText("Today")).toBeNull());
    expect(screen.getByRole("button", { name: "Everything · 6" })).toBeTruthy();
  });

  it("shows the server's words when marking done is refused, and keeps the task", async () => {
    serve(tasks(), { "PATCH /api/prod/tasks/5": () => reply(404, { detail: "There is no such task." }) });
    renderAt(ADDRESS, qc());
    await screen.findByText("Visit the new print house");
    fireEvent.click(screen.getByRole("button", { name: "Mark done: Visit the new print house" }));
    expect((await screen.findByRole("alert")).textContent).toBe("There is no such task.");
    expect(screen.getByText("Visit the new print house")).toBeTruthy();
  });

  it("is edited in a form that starts with what it has, sending the whole of it", async () => {
    const { calls, state } = serve(tasks(), {
      "PATCH /api/prod/tasks/5": (body) => {
        const sent = body as { title: string };
        state.tasks = state.tasks.map((task) => (task.key === "task:5" ? { ...typed(), title: sent.title } : task));
        return { task: { ...typed(), title: sent.title } };
      },
    });
    state.tasks = state.tasks.map((task) => (task.key === "task:5" ? typed() : task));
    renderAt(ADDRESS, qc());
    await screen.findByText("Visit the new print house");
    const edit = screen.getByRole("button", { name: "Edit: Visit the new print house" });
    fireEvent.click(edit);
    const form = formOf("Edit task");
    expect((within(form).getByLabelText("Task") as HTMLInputElement).value).toBe("Visit the new print house");
    expect((within(form).getByLabelText("Date (optional)") as HTMLInputElement).value).toBe("2030-11-13");
    expect((within(form).getByLabelText("Note (optional)") as HTMLTextAreaElement).value).toBe("Ask about minimums");
    expect((within(form).getByLabelText("For the owner") as HTMLInputElement).checked).toBe(false);
    fireEvent.change(within(form).getByLabelText("Task"), { target: { value: "Visit the print house" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save task" }));
    expect(await screen.findByText("Saved: Visit the print house")).toBeTruthy();
    expect(writes(calls)).toEqual([
      expect.objectContaining({
        method: "PATCH",
        path: "/api/prod/tasks/5",
        body: { title: "Visit the print house", due_on: "2030-11-13", order_id: null, note: "Ask about minimums", for_owner: false },
      }),
    ]);
    expect(await screen.findByText("Visit the print house")).toBeTruthy();
  });

  it("asks before it is deleted, and keeps it when told to", async () => {
    const { calls, state } = serve(tasks(), {
      "DELETE /api/prod/tasks/5": () => {
        state.tasks = state.tasks.filter((task) => task.key !== "task:5");
        return { deleted: 5 };
      },
    });
    renderAt(ADDRESS, qc());
    await screen.findByText("Visit the new print house");
    fireEvent.click(screen.getByRole("button", { name: "Delete: Visit the new print house" }));
    const row = rowOf("Visit the new print house");
    expect(within(row).getByText("Delete this task?")).toBeTruthy();
    // Focus is on the safe answer.
    expect(document.activeElement).toBe(within(row).getByRole("button", { name: "Keep it" }));
    expect(writes(calls)).toHaveLength(0);

    fireEvent.click(within(row).getByRole("button", { name: "Keep it" }));
    expect(within(row).queryByText("Delete this task?")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(within(row).getByRole("button", { name: "Delete: Visit the new print house" })));
    expect(writes(calls)).toHaveLength(0);

    fireEvent.click(within(row).getByRole("button", { name: "Delete: Visit the new print house" }));
    fireEvent.click(within(row).getByRole("button", { name: "Delete task: Visit the new print house" }));
    expect(await screen.findByText("Deleted: Visit the new print house")).toBeTruthy();
    expect(writes(calls)).toEqual([expect.objectContaining({ method: "DELETE", path: "/api/prod/tasks/5" })]);
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Today" })).toBeNull());
  });

  it("is listed under done when asked, and can be reopened", async () => {
    const done = makeManual({ id: 8, title: "Order the swing tags", done: true, done_at: "2030-11-12T10:00:00Z", group: "done" });
    const { calls, state } = serve(tasks(), {
      "PATCH /api/prod/tasks/8": () => {
        state.tasks = state.tasks.map((task) => (task.key === "task:8" ? { ...done, done: false, done_at: null, group: "later" } : task));
        return { task: { ...done, done: false, group: "later" } };
      },
    });
    const reads = () => calls.filter((call) => call.method === "GET" && call.path === "/api/prod/tasks").map((call) => call.url);
    renderAt(ADDRESS, qc());
    await screen.findByText("Visit the new print house");
    expect(screen.queryByText("Order the swing tags")).toBeNull();

    state.tasks = [...state.tasks, done];
    fireEvent.click(screen.getByLabelText("Show tasks done in the last 14 days"));
    const row = await waitFor(() => rowOf("Order the swing tags"));
    expect(reads().at(-1)).toBe("/api/prod/tasks?done=1");
    expect(screen.getByRole("heading", { level: 2, name: "Done in the last 14 days" })).toBeTruthy();
    expect(row.textContent).toContain("Done 12 Nov");
    // Done tasks are not in the counts.
    expect(screen.getByRole("button", { name: "Everything · 7" })).toBeTruthy();

    fireEvent.click(within(row).getByRole("button", { name: "Reopen: Order the swing tags" }));
    expect(await screen.findByText("Reopened: Order the swing tags")).toBeTruthy();
    expect(writes(calls)).toEqual([expect.objectContaining({ method: "PATCH", path: "/api/prod/tasks/8", body: { done: false } })]);
  });
});

describe("Slow and out-of-order answers", () => {
  it("keeps the newer list when an earlier read answers late", async () => {
    let release: (value: unknown) => void = () => undefined;
    const slow = new Promise((resolve) => {
      release = resolve;
    });
    mockApi({
      "GET /api/prod/tasks": (_body, call) =>
        call.url.includes("done=1") ? slow : makeTaskList([makeManual({ id: 1, title: "The newer answer" })]),
    });
    renderAt(ADDRESS, qc());
    await screen.findByText("The newer answer");
    // Ask for the done ones (the answer is slow), then change your mind: the plain read answers first.
    const toggle = screen.getByLabelText("Show tasks done in the last 14 days");
    fireEvent.click(toggle);
    fireEvent.click(toggle);
    await waitFor(() => expect((toggle as HTMLInputElement).checked).toBe(false));
    release(makeTaskList([makeManual({ id: 2, title: "The older answer" })]));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.getByText("The newer answer")).toBeTruthy();
    expect(screen.queryByText("The older answer")).toBeNull();
  });

  it("drops an answer that arrives after the screen has been left", async () => {
    let release: (value: unknown) => void = () => undefined;
    const slow = new Promise((resolve) => {
      release = resolve;
    });
    mockApi({ "GET /api/prod/tasks": () => slow });
    const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { unmount } = renderAt(ADDRESS, qc());
    await screen.findByText("Loading tasks…");
    unmount();
    release(makeTaskList([makeManual({ id: 2, title: "Too late" })]));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(errors).not.toHaveBeenCalled();
    errors.mockRestore();
  });
});

describe("On a phone", () => {
  it("stacks each task, with its buttons below at a size a thumb can press", async () => {
    narrowScreen(true);
    serve();
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Tasks" });
    const rows = document.querySelectorAll("li.prod-task--narrow");
    expect(rows).toHaveLength(7);
    const sample = rowOf("Give a reason for 1 missing piece");
    expect(sample.querySelector(".prod-task__actions")).toBeTruthy();
    expect(sample.textContent).toContain("QC manager · 12 Nov · 1 day");
    expect(within(sample).getByRole("link", { name: /^Add reason/ })).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    // The desktop row is not rendered at all.
    expect(document.querySelector(".prod-task__side")).toBeNull();
  });
});

describe("The Tasks tab", () => {
  it("says how many tasks are overdue, in words, on every screen", async () => {
    mockApi({
      "GET /api/prod/orders": { orders: [] },
      "GET /api/prod/tasks": makeTaskList(tasks()),
    });
    renderAt("/production/next/orders", qc());
    const tabs = await screen.findByRole("navigation", { name: "Production sections" });
    const link = await within(tabs).findByRole("link", { name: "Tasks 2 overdue" });
    expect(link.getAttribute("href")).toBe("/production/next/tasks");
    // Overview leads; Suppliers follows Incoming, before Stage days.
    expect(within(tabs).getAllByRole("link").map((item) => item.textContent)).toEqual(["Overview", "Orders", "Tasks 2 overdue", "Incoming", "Suppliers", "Stage days"]);
  });

  it("shows no count when nothing is overdue, and survives the count not loading", async () => {
    const calls = mockApi({ "GET /api/prod/orders": { orders: [] }, "GET /api/prod/tasks": makeTaskList([makeManual({ id: 1, title: "x", group: "later" })]) });
    renderAt("/production/next/orders", qc());
    const tabs = await screen.findByRole("navigation", { name: "Production sections" });
    await waitFor(() => expect(calls.some((call) => call.path === "/api/prod/tasks")).toBe(true));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(within(tabs).getByRole("link", { name: "Tasks" })).toBeTruthy();
    cleanup();
    mockApi({ "GET /api/prod/orders": { orders: [] } }); // /api/prod/tasks is refused with a 404
    renderAt("/production/next/orders", qc());
    expect(await screen.findByRole("heading", { name: "Production orders" })).toBeTruthy();
    expect(within(screen.getByRole("navigation", { name: "Production sections" })).getByRole("link", { name: "Tasks" })).toBeTruthy();
  });

  it("changes as soon as a task is marked done on the Tasks screen", async () => {
    const overdueManual = makeManual({ id: 5, title: "Chase the invoice", group: "overdue", overdue_days: 2, due: "2030-11-11" });
    const { state } = serve([overdueManual], {
      "PATCH /api/prod/tasks/5": () => {
        state.tasks = [];
        return { task: { ...overdueManual, done: true } };
      },
    });
    renderAt(ADDRESS, qc());
    const tabs = await screen.findByRole("navigation", { name: "Production sections" });
    expect(await within(tabs).findByRole("link", { name: "Tasks 1 overdue" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Mark done: Chase the invoice" }));
    await screen.findByText("Marked done: Chase the invoice");
    await waitFor(() => expect(within(tabs).getByRole("link", { name: "Tasks" })).toBeTruthy());
  });
});
