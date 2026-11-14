import { Outlet } from "react-router-dom";

import "./prod.css";
import { ProdTabs } from "./ProdTabs";
import type { ProdTab } from "./ProdTabs";

/** The tabs that exist so far. Later batches (Tasks, Incoming, Suppliers, Overview) add theirs here. */
export const PROD_TABS: readonly ProdTab[] = [
  { to: "/production/next/orders", label: "Orders" },
  { to: "/production/next/settings", label: "Stage days" },
];

/** What every native Production screen sits in: the tab row, then the screen. */
export function NextLayout() {
  return (
    <div className="prod-screen">
      <div className="prod-screen__in">
        <ProdTabs tabs={PROD_TABS} />
        <Outlet />
      </div>
    </div>
  );
}
