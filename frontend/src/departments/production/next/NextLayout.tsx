import { useCallback, useEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";

import { api } from "../../../lib/api";
import "./prod.css";
import { ProdTabs } from "./ProdTabs";
import type { ProdTab } from "./ProdTabs";
import type { TaskList } from "./types";

const TASKS = "/production/next/tasks";
const INCOMING = "/production/next/incoming";

/** The tabs, Overview first. */
export function prodTabs(overdue: number): readonly ProdTab[] {
  return [
    { to: "/production/next/overview", label: "Overview" },
    { to: "/production/next/orders", label: "Orders" },
    { to: TASKS, label: "Tasks", count: overdue, countLabel: `${overdue} overdue` },
    { to: INCOMING, label: "Incoming" },
    { to: "/production/next/suppliers", label: "Suppliers" },
    { to: "/production/next/settings", label: "Stage days" },
  ];
}

/** What a screen inside the layout can ask of it (`useOutletContext`). */
export type LayoutContext = { setOverdue: (count: number) => void };

/** What every native Production screen sits in: the tab row, then the screen. */
export function NextLayout() {
  const [overdue, setOverdue] = useState(0);
  const { pathname } = useLocation();
  const onTasks = pathname.startsWith(TASKS);
  const latest = useRef(0);

  // The Tasks tab says how many tasks are overdue. Every screen but Tasks itself reads it when it opens;
  // Tasks reports its own, so a task marked done changes the tab at once.
  useEffect(() => {
    if (onTasks) return;
    const mine = ++latest.current;
    api.get<Partial<TaskList>>("/api/prod/tasks")
      .then((answer) => {
        if (latest.current === mine && typeof answer.counts?.overdue === "number") setOverdue(answer.counts.overdue);
      })
      .catch(() => undefined); // a missing count must never take the screen down
    return () => {
      latest.current += 1;
    };
  }, [onTasks, pathname]);

  const report = useCallback((count: number) => setOverdue(count), []);

  return (
    <div className="prod-screen">
      <div className="prod-screen__in">
        <ProdTabs tabs={prodTabs(overdue)} />
        <Outlet context={{ setOverdue: report } satisfies LayoutContext} />
      </div>
    </div>
  );
}
