import { useState } from "react";
import type { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";

import { api, roleLabel, signOutAndLeave } from "../lib/api";
import type { Session } from "../lib/api";
import { pickMaintainerChoice, storedMaintainerChoice } from "../lib/theme";
import type { ThemeChoice } from "../lib/theme";
import { DashboardSwitch } from "./DashboardSwitch";
import type { Dashboard } from "./DashboardSwitch";
import { useMaintainerTheme } from "./useMaintainerTheme";
import "./Layout.css";

const THEMES: [ThemeChoice, string][] = [
  ["dark", "Dark"],
  ["light", "Light"],
  ["system", "Match my device"],
];

export type ShellSection = {
  to: string;
  label: string;
  /** Shown beside the name when there is something waiting; never a 0. */
  count?: number;
};

/**
 * The shell Operations and the Inbox share (ADR 0057, ADR 0059).
 *
 * The affiliate dashboard's own shell (`Layout.css`'s classes), holding one
 * dashboard's sections and nothing else. It asks the affiliate side for
 * nothing - no counts, no preferences beyond the person's theme - so somebody
 * who holds only this dashboard never knocks on a door that refuses them.
 *
 * The theme lives in the account menu here: the admin chooses it in
 * Settings, which the operations manager and customer service do not have.
 */
export function SideShell({
  session,
  dashboard,
  name,
  home,
  sections,
  flush = false,
  immersive = false,
  children,
}: {
  session: Session;
  dashboard: Dashboard;
  /** "Operations", "Inbox": the brand's name and the sidebar's label. */
  name: string;
  home: string;
  sections: ShellSection[];
  /** The screen runs edge to edge and scrolls inside itself (Chats). */
  flush?: boolean;
  /** On a phone the screen takes the whole display, sidebar included (an
   *  open chat, which has its own way back). */
  immersive?: boolean;
  children: ReactNode;
}) {
  const [accountOpen, setAccountOpen] = useState(false);
  const [theme, setTheme] = useState<ThemeChoice>(storedMaintainerChoice());
  useMaintainerTheme();

  function choose(choice: ThemeChoice) {
    pickMaintainerChoice(choice);
    setTheme(choice);
    api.put("/api/staff/me/theme", { theme: choice }).catch(() => undefined);
  }

  const who = session.actor.display_name || session.actor.email;
  const menuId = `${dashboard}-account-menu`;

  return (
    <div
      className={["layout", flush && "layout--flush", immersive && "layout--immersive"]
        .filter(Boolean)
        .join(" ")}
    >
      <nav className="layout__sidebar" aria-label={name}>
        <Link to={home} className="layout__brand" aria-label={`HBA ${name} home`}>
          <span className="layout__brand-mark">HBA</span>
          <span>
            <span className="layout__brand-name">{name}</span>
            <span className="layout__brand-role">hbawear.store</span>
          </span>
        </Link>
        <DashboardSwitch session={session} current={dashboard} />

        <ul className="layout__nav">
          {sections.map((section) => (
            <li key={section.to}>
              <NavLink
                to={section.to}
                className={({ isActive }) =>
                  isActive ? "layout__link layout__link--active" : "layout__link"
                }
              >
                {section.label}
                {section.count ? (
                  <span className="layout__count layout__count--settled">
                    {section.count}
                    <span className="visually-hidden"> unread</span>
                  </span>
                ) : null}
              </NavLink>
            </li>
          ))}
        </ul>

        <div className="layout__account">
          <button
            type="button"
            className="layout__account-toggle"
            aria-expanded={accountOpen}
            aria-controls={menuId}
            onClick={() => setAccountOpen(!accountOpen)}
          >
            <span className="layout__avatar">{who.charAt(0).toUpperCase()}</span>
            <span className="layout__identity">
              <span className="layout__email">{who}</span>
              <span className="layout__brand-role">{roleLabel(session.actor)}</span>
            </span>
            <span aria-hidden="true">▾</span>
          </button>
          {accountOpen && (
            <div id={menuId} className="layout__account-menu">
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

      <main className="layout__main">{children}</main>
    </div>
  );
}
