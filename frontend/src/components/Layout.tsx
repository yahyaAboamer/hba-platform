import { useEffect, useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";

import { api, signOutAndLeave } from "../lib/api";
import type { Session } from "../lib/api";
import { applyMaintainerTheme, storedTheme } from "../lib/theme";
import "./Layout.css";

/** The six workspaces and account menu from the approved admin export. */
/** Keyed by the section's `count` name, so a new badge needs no new type. */
type Counts = Record<string, number>;

const SECTIONS = [
  { to: "/", label: "Home", end: true },
  { to: "/affiliates", label: "Models", count: "models_awaiting_approval" },
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
  const [accountOpen, setAccountOpen] = useState(false);
  const [theme] = useState(() => storedTheme("maintainer"));
  /**
   * The counts beside the section names, as the approved export draws them.
   *
   * A failed fetch leaves them absent rather than zero: *no badge* reads as
   * nothing to say, while a `0` asserts there is nothing waiting - which is a
   * claim this component would be making up.
   */
  const [counts, setCounts] = useState<Counts>({});

  useEffect(() => {
    api
      .get<Counts>("/api/operations/counts")
      .then(setCounts)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    applyMaintainerTheme(theme);
  }, [theme]);

  return (
    <div className="layout">
      <nav className="layout__sidebar" aria-label="Sections">
        <Link to="/" className="layout__brand" aria-label="HBA Admin home">
          <span className="layout__brand-mark">HBA</span>
          <span><span className="layout__brand-name">Admin</span>
            <span className="layout__brand-role">hbawear.store</span></span>
        </Link>

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
                {section.count && counts[section.count] > 0 && (
                  <span className="layout__count">{counts[section.count]}</span>
                )}
              </NavLink>
            </li>
          ))}
        </ul>

        <div className="layout__account">
          <button type="button" className="layout__account-toggle"
            aria-expanded={accountOpen} aria-controls="admin-account-menu"
            onClick={() => setAccountOpen(!accountOpen)}>
            <span className="layout__avatar">{(session.actor.display_name || session.actor.email).charAt(0).toUpperCase()}</span>
            <span className="layout__identity">
              <span className="layout__email">{session.actor.display_name || session.actor.email}</span>
              <span className="layout__brand-role">{session.actor.role.replace(/_/g, " ")}</span>
            </span><span aria-hidden="true">▾</span>
          </button>
          {accountOpen && <div id="admin-account-menu" className="layout__account-menu">
            <Link to="/settings?section=team" onClick={() => setAccountOpen(false)}>Team and access</Link>
            <Link to="/glossary" onClick={() => setAccountOpen(false)}>Help</Link>
            <Link to="/settings?section=appearance" onClick={() => setAccountOpen(false)}>Appearance</Link>
            <button type="button" onClick={signOutAndLeave}>Sign out</button>
          </div>}
        </div>
      </nav>

      <main className="layout__main">
        <Outlet />
      </main>
    </div>
  );
}
