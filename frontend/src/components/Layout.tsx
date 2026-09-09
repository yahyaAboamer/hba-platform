import { useEffect, useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";

import { signOutAndLeave } from "../lib/api";
import type { Session } from "../lib/api";
import { applyMaintainerTheme, storeTheme, storedTheme } from "../lib/theme";
import "./Layout.css";

/**
 * **Home · Models · Products · Targets · Payments · Settings.** Six, from the
 * approved design (`docs/redesign/designs/Admin Dashboard.dc.html`, rule S02).
 *
 * The order is still the order of a month: see where things stand, check who
 * is on the programme, check what they were sent, check what they were asked
 * for, agree and pay it. Settings sits last because it is set up once and
 * revisited.
 *
 * ## What left the top level, and where it went
 *
 * **Orders** and **Payroll** were sections here and are not any more. Neither
 * was deleted — S02 is explicit that secondary destinations keep every
 * necessary operation, and both routes still work, still carry their
 * permissions, and still have a way in:
 *
 * - `/orders` — every attributed order, for support. Reached from Home, where
 *   the sales figure it explains already is. The design does the same, and
 *   titles it *Attributed orders*.
 * - `/payroll` — agreeing a month. Reached from Payments, which is the screen
 *   about the same money. In the finished design there is no separate payroll
 *   screen at all: approval happens inside one model's payment. Merging them
 *   is Phase 05B/06A work, so until then this is a link rather than a rebuild
 *   — which keeps the operation exactly where it works today.
 *
 * A tab bar that grows and shrinks as batches land moves everything under
 * somebody's cursor each time, so **Products is here now** even though Phase
 * 03 builds it. It says so, in as many words, rather than looking empty.
 *
 * ## The paths did not change
 *
 * `/affiliates` still reads *Models* rather than moving to `/models`. The
 * label is what the business says and what the design draws; the path is what
 * two people have bookmarked and what every internal link already points at.
 * Renaming it during a redesign buys a tidier URL and spends a working
 * bookmark, and S07 asks for deep links that keep working.
 */
const SECTIONS = [
  { to: "/", label: "Home", end: true },
  { to: "/affiliates", label: "Models" },
  { to: "/products", label: "Products" },
  { to: "/targets", label: "Targets" },
  { to: "/payments", label: "Payments" },
  { to: "/settings", label: "Settings" },
];

export function Layout({ session }: { session: Session }) {
  /**
   * Dark by default here too, as the approved admin export draws it, and
   * remembered per device under its own key — a model's phone and a
   * maintainer's laptop are not one preference.
   *
   * Stamped on `<html>` rather than on this element: sign-in and first-run
   * render outside this layout, and a tool that is dark once you are in and
   * white on the way there is a tool that flashes at you every morning.
   */
  const [theme, setTheme] = useState(() => storedTheme("maintainer"));

  useEffect(() => {
    applyMaintainerTheme(theme);
  }, [theme]);

  return (
    <div className="layout">
      <nav className="layout__sidebar" aria-label="Sections">
        <div className="layout__brand">
          <span className="layout__brand-name">HBA</span>
          <span className="layout__brand-role">
            {session.actor.role.replace(/_/g, " ")}
          </span>
        </div>

        <ul className="layout__nav">
          {SECTIONS.map((section) => (
            <li key={section.to}>
              <NavLink
                to={section.to}
                end={section.end}
                className={({ isActive }) =>
                  isActive ? "layout__link layout__link--active" : "layout__link"
                }
              >
                {section.label}
              </NavLink>
            </li>
          ))}
        </ul>

        <div className="layout__account">
          <span className="layout__email" title={session.actor.email}>
            {session.actor.display_name || session.actor.email}
          </span>
          {/*
           * Reference material, not a workflow step - deliberately not one of
           * the six sections above it. What "void" or "carried forward"
           * mean is reached from here or from a term wherever it already
           * appears, never a destination somebody scans past every month.
           */}
          <Link to="/glossary" className="layout__glossary">
            What these words mean
          </Link>
          {/*
           * A switch, not a menu. There are two states and naming the one you
           * would move to is shorter to read than a label plus a control.
           */}
          <button
            type="button"
            className="layout__theme"
            onClick={() => {
              const next = theme === "dark" ? "light" : "dark";
              setTheme(next);
              storeTheme(next, "maintainer");
            }}
          >
            {theme === "dark" ? "Light theme" : "Dark theme"}
          </button>
          <button
            type="button"
            className="layout__sign-out"
            onClick={signOutAndLeave}
          >
            Sign out
          </button>
        </div>
      </nav>

      <main className="layout__main">
        <Outlet />
      </main>
    </div>
  );
}
