import { Outlet } from "react-router-dom";

import "./prod.css";

/**
 * What every Production screen sits in: the department's own wrapper, which
 * carries the `prod-*` rules. The sections are the sidebar's (as in every
 * department); there is no row of tabs here.
 */
export function ProductionLayout() {
  return (
    <div className="prod-screen">
      <div className="prod-screen__in">
        <Outlet />
      </div>
    </div>
  );
}
