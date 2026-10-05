import { useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";

import { api, can, signOutAndLeave } from "../lib/api";
import type { Session } from "../lib/api";
import { pickMaintainerChoice, storedMaintainerChoice } from "../lib/theme";
import type { ThemeChoice } from "../lib/theme";
import { DashboardSwitch } from "./DashboardSwitch";
import { useMaintainerTheme } from "./useMaintainerTheme";
import "./Layout.css";

/**
 * Operations' three sections (ADR 0057; the approved mockup
 * `docs/design/operations-dashboard-2026-10-03.html`). The slug is the
 * address and what the dashboard reads to know which tab is open.
 */
export const OPERATIONS_SECTIONS = [
  { slug: "shopify", label: "Shopify" },
  { slug: "bosta", label: "Bosta" },
  { slug: "estebdal", label: "E-stebdal" },
] as const;

const THEMES: [ThemeChoice, string][] = [
  ["dark", "Dark"],
  ["light", "Light"],
  ["system", "Match my device"],
];

/**
 * The shell the operations manager signs in to, and the admin switches to.
 *
 * The affiliate dashboard's own shell (`Layout.css`'s classes), holding
 * Shopify, Bosta and E-stebdal and nothing else. It asks the affiliate side
 * for nothing - no counts, no preferences beyond the person's theme - so the
 * operations manager's session never knocks on a door that refuses him.
 *
 * The theme lives in the account menu here: the admin chooses it in
 * Settings, which the operations manager does not have.
 */
export function OperationsLayout({ session }: { session: Session }) {
  const [accountOpen, setAccountOpen] = useState(false);
  const [theme, setTheme] = useState<ThemeChoice>(storedMaintainerChoice());
  useMaintainerTheme();

  function choose(choice: ThemeChoice) {
    pickMaintainerChoice(choice);
    setTheme(choice);
    api.put("/api/staff/me/theme", { theme: choice }).catch(() => undefined);
  }

  const who = session.actor.display_name || session.actor.email;

  return (
    <div className="layout">
      <nav className="layout__sidebar" aria-label="Operations">
        <Link to="/operations" className="layout__brand" aria-label="HBA Operations home">
          <span className="layout__brand-mark">HBA</span>
          <span>
            <span className="layout__brand-name">Operations</span>
            <span className="layout__brand-role">hbawear.store</span>
          </span>
        </Link>
        {can(session, "affiliates.view") && <DashboardSwitch current="operations" />}

        <ul className="layout__nav">
          {OPERATIONS_SECTIONS.map((section) => (
            <li key={section.slug}>
              <NavLink
                to={`/operations/${section.slug}`}
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
          <button
            type="button"
            className="layout__account-toggle"
            aria-expanded={accountOpen}
            aria-controls="operations-account-menu"
            onClick={() => setAccountOpen(!accountOpen)}
          >
            <span className="layout__avatar">{who.charAt(0).toUpperCase()}</span>
            <span className="layout__identity">
              <span className="layout__email">{who}</span>
              <span className="layout__brand-role">{session.actor.role.replace(/_/g, " ")}</span>
            </span>
            <span aria-hidden="true">▾</span>
          </button>
          {accountOpen && (
            <div id="operations-account-menu" className="layout__account-menu">
              <div className="layout__themes" role="group" aria-label="Theme">
                {THEMES.map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={theme === value}
                    onClick={() => choose(value)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <button type="button" onClick={signOutAndLeave}>Sign out</button>
            </div>
          )}
        </div>
      </nav>

      <main className="layout__main">
        <Outlet />
      </main>
    </div>
  );
}
