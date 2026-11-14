import { NavLink } from "react-router-dom";

export type ProdTab = { to: string; label: string; end?: boolean };

/**
 * The row of tabs at the top of Production's native screens (the mockup's
 * `.tabs`). Production has no sidebar sections of its own, so the sections
 * live here; each later batch adds its tab to the list the layout passes in.
 * The current one is marked by `aria-current`, so it is never colour alone.
 */
export function ProdTabs({ tabs, label = "Production sections" }: { tabs: readonly ProdTab[]; label?: string }) {
  return (
    <nav className="prod-tabs" aria-label={label}>
      {tabs.map((tab) => (
        <NavLink key={tab.to} to={tab.to} end={tab.end}>
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}
