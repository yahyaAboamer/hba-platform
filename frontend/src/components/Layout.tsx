import { Link, NavLink, Outlet } from "react-router-dom";

import { signOutAndLeave } from "../lib/api";
import type { Session } from "../lib/api";
import "./Layout.css";

/**
 * §12.3. Overview · Affiliates · Orders · Payroll · Payments · Targets · Settings.
 *
 * The order is the order of a month: see where things stand, check who is on
 * the programme and what they sold, agree what is owed, pay it. Targets and
 * Settings sit below because they are set up once and revisited, not walked
 * through every month.
 */
const SECTIONS = [
  { to: "/", label: "Overview", end: true },
  { to: "/affiliates", label: "Affiliates" },
  { to: "/orders", label: "Orders" },
  { to: "/payroll", label: "Payroll" },
  { to: "/payments", label: "Payments" },
  { to: "/targets", label: "Targets" },
  { to: "/settings", label: "Settings" },
];

export function Layout({ session }: { session: Session }) {

  return (
    <div className="layout">
      <nav className="layout__sidebar" aria-label="Sections">
        <div className="layout__brand">
          <span className="layout__brand-name">HBA</span>
          <span className="layout__brand-role">{session.actor.role.replace(/_/g, " ")}</span>
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
           * the seven sections above it. What "void" or "carried forward"
           * mean is reached from here or from a term wherever it already
           * appears, never a destination somebody scans past every month.
           */}
          <Link to="/glossary" className="layout__glossary">
            What these words mean
          </Link>
          <button type="button" className="layout__sign-out" onClick={signOutAndLeave}>
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
