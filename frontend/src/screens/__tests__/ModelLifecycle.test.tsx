// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api, type Session } from "../../lib/api";
import { ModelLifecycle } from "../ModelLifecycle";

/** ADR 0052: what each status offers on her profile, and to whom. */
const session = (permissions: string[]): Session =>
  ({ actor: { id: 1, email: "o@example.com", role: "admin" }, permissions, platform: {} }) as unknown as Session;

const admin = session(["affiliates.manage", "affiliates.erase"]);
const manager = session(["affiliates.manage"]);

function show(status: string, who = admin, extra: Record<string, unknown> = {}) {
  render(
    <ModelLifecycle
      subject={{ id: 7, name: "Laila Samir", status, erase_blockers: [], ...extra }}
      session={who}
      onChanged={() => undefined}
      onErased={() => undefined}
    />,
  );
}

afterEach(cleanup);

describe("ModelLifecycle", () => {
  it("offers Decline on an application, and no menu to pause what is not live", () => {
    show("pending");
    expect(screen.getByRole("button", { name: "Decline" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /More actions/ }));
    expect(screen.queryByRole("menuitem", { name: /Pause/ })).toBeNull();
    expect(screen.getByRole("menuitem", { name: /Erase/ })).toBeTruthy();
  });

  it("offers Pause and Archive on an active model", () => {
    show("active");
    fireEvent.click(screen.getByRole("button", { name: /More actions/ }));
    expect(screen.getByRole("menuitem", { name: /Pause/ })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /Archive/ })).toBeTruthy();
  });

  it("offers Reactivate on a paused or archived model and Reconsider on a declined one", () => {
    show("inactive");
    expect(screen.getByRole("button", { name: "Reactivate" })).toBeTruthy();
    cleanup();
    show("archived");
    expect(screen.getByRole("button", { name: "Reactivate" })).toBeTruthy();
    cleanup();
    show("declined");
    expect(screen.getByRole("button", { name: "Reconsider" })).toBeTruthy();
  });

  it("offers Erase only to an admin, and only when nothing blocks it", () => {
    show("active", manager);
    fireEvent.click(screen.getByRole("button", { name: /More actions/ }));
    expect(screen.queryByRole("menuitem", { name: /Erase/ })).toBeNull();
    cleanup();

    show("active", admin, { erase_blockers: ["a payroll month"] });
    fireEvent.click(screen.getByRole("button", { name: /More actions/ }));
    expect(screen.queryByRole("menuitem", { name: /Erase/ })).toBeNull();
  });

  it("will not pause without a reason", () => {
    show("active");
    fireEvent.click(screen.getByRole("button", { name: /More actions/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Pause/ }));
    const confirm = screen.getByRole("button", { name: "Pause" }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "On a break" } });
    expect(confirm.disabled).toBe(false);
  });

  it("will not erase until her name is typed exactly", () => {
    show("active");
    fireEvent.click(screen.getByRole("button", { name: /More actions/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Erase/ }));
    const [reason, name] = screen.getAllByRole("textbox");
    fireEvent.change(reason, { target: { value: "Test entry" } });
    const confirm = screen.getByRole("button", { name: "Erase for good" }) as HTMLButtonElement;
    fireEvent.change(name, { target: { value: "laila samir" } });
    expect(confirm.disabled).toBe(true);
    fireEvent.change(name, { target: { value: "Laila Samir" } });
    expect(confirm.disabled).toBe(false);
  });

  it("says declining deletes the application, and leaves the profile once it has", async () => {
    // ADR 0058: the owner declined to fix a typo and could not invite again.
    const patch = vi.spyOn(api, "patch").mockResolvedValue({ erased: 7, status: "declined" });
    const erased = vi.fn();
    const changed = vi.fn();
    render(
      <ModelLifecycle
        subject={{ id: 7, name: "Laila Samir", status: "pending", erase_blockers: [] }}
        session={manager}
        onChanged={changed}
        onErased={erased}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(screen.getByText(/The application is deleted/)).toBeTruthy();
    expect(screen.getByText(/invite the same email again/)).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Code typed wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "Decline and delete" }));

    await waitFor(() => expect(erased).toHaveBeenCalled());
    expect(erased.mock.calls[0][0]).toMatch(/declined and deleted/);
    expect(changed).not.toHaveBeenCalled();
    expect(patch).toHaveBeenCalledWith("/api/affiliates/7", { status: "declined", reason: "Code typed wrong" });
    patch.mockRestore();
  });

  it("says when a declined application has to be kept", () => {
    show("pending", admin, { erase_blockers: ["an order attributed to her"] });
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(screen.getByText(/It can't be deleted: there is an order attributed to her/)).toBeTruthy();
  });

  it("offers nothing to somebody who cannot manage models", () => {
    show("active", session([]));
    expect(screen.queryByRole("button")).toBeNull();
  });
});
