import { Outlet } from "react-router-dom";

import { signOutAndLeave } from "../lib/api";
import type { Session } from "../lib/api";
import { storedTheme } from "../lib/theme";
import "./factory.css";

/**
 * What every factory screen sits in: a plain bar (HBA, who is signed in, a way
 * out) and the page. No sidebar and no departments - the factory has one job.
 * It takes the platform's tokens, so light and dark follow the device's choice.
 */
export function FactoryLayout({ session }: { session: Session }) {
  const who = session.actor.display_name || session.actor.email;
  return (
    <div className="factory" data-theme={storedTheme("portal")}>
      <header className="factory__top">
        <b>HBA · Production</b>
        <span className="factory__who">
          <span className="factory__name">{who}</span>
          <button type="button" className="button factory__leave" onClick={() => void signOutAndLeave()}>
            Sign out
          </button>
        </span>
      </header>
      <main className="factory__main">
        <Outlet />
      </main>
    </div>
  );
}
