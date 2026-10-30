import { Link, Navigate, useLocation } from "react-router-dom";

import { startFor } from "../departments";
import type { Department } from "../departments/types";
import { can } from "../lib/api";
import type { Session } from "../lib/api";
import { movedAddress } from "./moved";
import { SETTINGS_BASES, canOpenSettings, within } from "./where";

/**
 * Any address in the staff tree that is not a screen, said inside the frame:
 *
 * - an old address goes to its new one, keeping the rest of the path, the
 *   query and the hash;
 * - an address in a department this person does not hold says so;
 * - anything else is "Nothing here", rather than a blank page.
 */
export function Elsewhere({
  session,
  departments,
}: {
  session: Session;
  /** Every department, held or not. */
  departments: readonly Department[];
}) {
  const { pathname, search, hash } = useLocation();

  const moved = movedAddress(pathname, departments.flatMap((department) => department.moved));
  if (moved) return <Navigate to={{ pathname: moved, search, hash }} replace />;

  const start = startFor(session);
  const refused =
    departments.find((department) => within(pathname, department.base) && !can(session, department.holds))
      ?.name ??
    (SETTINGS_BASES.some((base) => within(pathname, base)) && !canOpenSettings(session)
      ? "Settings"
      : null);

  if (refused) {
    return (
      <div className="page__head">
        <div className="page__title">
          <h1>Not available</h1>
          <span className="page__subtitle">
            This page is in {refused}, which your access does not include.{" "}
            <Link to={start}>Go to your start</Link>
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="page__head">
      <div className="page__title">
        <h1>Nothing here</h1>
        <span className="page__subtitle">
          There is no screen at this address. <Link to={start}>Home</Link>
        </span>
      </div>
    </div>
  );
}

/** `/`: each person's start, until Today replaces it (Batch 2.2). Keeps the query and hash. */
export function Start({ session, departments }: { session: Session; departments: readonly Department[] }) {
  const { search, hash } = useLocation();
  const start = startFor(session);
  if (start === "/") return <Elsewhere session={session} departments={departments} />;
  return <Navigate to={{ pathname: start, search, hash }} replace />;
}
