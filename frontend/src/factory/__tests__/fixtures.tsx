/**
 * What the factory desk's tests share: a factory's session, the orders as
 * `/api/factory` answers them, and a render at an address. Not a test file.
 */
import { render } from "@testing-library/react";
import { MemoryRouter, Routes } from "react-router-dom";

import type { Session } from "../../lib/api";
import { factoryRoutes } from "../routes";
import type { FactoryOrder, FactoryOrderRow } from "../types";

/** A factory's own login: the `factory` role, no permission at all, and `is_factory`. */
export function factorySession(): Session {
  return {
    actor: {
      id: 21,
      email: "main@factory.example",
      display_name: "Main factory",
      roles: ["factory"],
      is_staff: false,
      is_model: false,
      is_factory: true,
    },
    permissions: [],
    platform: { working_month: "2026-11", go_live_month: "2026-10", start_month: "2026-01" },
  } as Session;
}

export function renderDesk(address: string) {
  return render(
    <MemoryRouter initialEntries={[address]}>
      <Routes>{factoryRoutes(factorySession())}</Routes>
    </MemoryRouter>,
  );
}

export function makeRow(over: Partial<FactoryOrderRow> & { id: number; style_name: string }): FactoryOrderRow {
  return {
    code: `PO-2611-0${over.id}`,
    colour: "Grey",
    printing: "none",
    planned_total: 800,
    cut: { reported_total: null, confirmed_total: null },
    status_words: "tell us how many you cut",
    delivery_date: "2030-12-05",
    moved: false,
    ...over,
  };
}

/** The sweatpants of the mockup: S, M and L planned 120, 240 and 240; the date moved once, by HBA. */
export function makeOrder(over: Partial<FactoryOrder> = {}): FactoryOrder {
  return {
    ...makeRow({ id: 2, style_name: "Wide-leg sweatpants" }),
    sizes: [
      { size: "S", planned: 120, reported: null, confirmed: null },
      { size: "M", planned: 240, reported: null, confirmed: null },
      { size: "L", planned: 240, reported: null, confirmed: null },
    ],
    report: null,
    can_report_cut: true,
    can_move_date: true,
    dates: [{ on: "2030-11-02", date: "2030-12-05", by: "HBA", reason: "Planned" }],
    ...over,
  };
}

/** The same order after the factory reported 118, 240 and 236 on 16 November. */
export function reportedOrder(over: Partial<FactoryOrder> = {}): FactoryOrder {
  return makeOrder({
    cut: { reported_total: 594, confirmed_total: null },
    sizes: [
      { size: "S", planned: 120, reported: 118, confirmed: null },
      { size: "M", planned: 240, reported: 240, confirmed: null },
      { size: "L", planned: 240, reported: 236, confirmed: null },
    ],
    report: { reported_on: "2030-11-16", note: "Short on fabric for S and L" },
    ...over,
  });
}
