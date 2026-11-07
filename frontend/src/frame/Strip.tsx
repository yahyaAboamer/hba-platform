import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import type { Department } from "../departments/types";
import { roleLabel } from "../lib/api";
import type { Session } from "../lib/api";
import { Icon } from "./Icon";
import { departmentMark, todayMark } from "./Sidebar";
import type { Mark } from "./Sidebar";
import type { Waiting } from "./useWaiting";
import { TODAY, canOpenSettings, holdsToday } from "./where";
import type { Where } from "./where";

/**
 * HBA's sidebar folded to a strip while Production is open (ADR 0076,
 * decision 6), from the approved frame
 * (`docs/design/hba-os-production-frame-2026-10-25.html`, frames 1 and 2).
 *
 * Every department keeps its icon, its count and its red dot; pointing at
 * one names it. The button under the H opens the names over Production
 * without moving it. The strip is dark whatever the theme, because Production
 * has only a dark look, and Production is marked in grey, not HBA green.
 */
type Props = {
  session: Session;
  departments: readonly Department[];
  where: Where;
  waiting: Waiting;
  start: string;
};

function initialsOf(session: Session): string {
  const who = session.actor.display_name || session.actor.email;
  return who
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word.charAt(0).toUpperCase())
    .join("");
}

function to(department: Department): string {
  return department.sections[0]?.to ?? department.base;
}

/** What a strip icon says to someone who cannot see its number or dot. */
function spoken(name: string, mark: Mark | null): string {
  const said = [mark?.count?.sentence, mark?.alert].filter(Boolean).join(". ");
  return said ? `${name}: ${said}` : name;
}

function Marks({ mark }: { mark: Mark | null }) {
  return (
    <>
      {mark?.count && <span className="strip__badge" aria-hidden="true">{mark.count.number}</span>}
      {mark?.alert && <span className="strip__dot strip__dot--red" aria-hidden="true" />}
    </>
  );
}

export function Strip({ session, departments, where, waiting, start }: Props) {
  const [named, setNamed] = useState(false);
  const flyout = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const today = holdsToday(departments) ? todayMark(waiting) : null;
  const who = session.actor.display_name || session.actor.email;

  useEffect(() => {
    if (!named) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setNamed(false);
        opener.current?.focus();
      }
    }
    function onClick(event: MouseEvent) {
      const target = event.target as Node;
      if (!flyout.current?.contains(target) && !opener.current?.contains(target)) setNamed(false);
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [named]);

  const close = () => setNamed(false);

  return (
    <aside className="strip-wrap">
      <nav className="strip" aria-label="HBA departments">
        <Link className="strip__mark" to={start} aria-label="HBA: open your start page">H</Link>
        <button
          ref={opener}
          type="button"
          className="strip__btn"
          aria-expanded={named}
          aria-label={named ? "Hide department names" : "Show department names"}
          onClick={() => setNamed((open) => !open)}
        >
          <Icon name="names" />
        </button>
        <span className="strip__rule" aria-hidden="true" />
        {holdsToday(departments) && (
          <Link className="strip__btn" to={TODAY} title="Today" aria-label={today ? `Today: ${today.sentence}` : "Today"}>
            <Icon name="today" />
            {today && <span className="strip__dot" aria-hidden="true" />}
          </Link>
        )}
        {departments.map((department) => {
          const here = where.department === department;
          const mark = here || department.own ? null : departmentMark(department, waiting);
          return (
            <Link
              key={department.key}
              className="strip__btn"
              to={to(department)}
              title={department.name}
              aria-label={spoken(department.name, mark)}
              aria-current={here ? "page" : undefined}
            >
              <Icon name={department.icon} />
              <Marks mark={mark} />
            </Link>
          );
        })}
        <span className="strip__spacer" />
        {canOpenSettings(session) && (
          <Link className="strip__btn" to="/settings/me" title="Settings" aria-label="Settings">
            <Icon name="settings" />
          </Link>
        )}
        <span className="strip__avatar" role="img" aria-label={`${who}, ${roleLabel(session.actor)}`}>
          {initialsOf(session)}
        </span>
      </nav>

      {named && (
        <div ref={flyout} className="strip__flyout">
          <div className="strip__flyout-top">
            <span className="strip__brand">
              <span className="strip__mark" aria-hidden="true">H</span>
              <span>
                <b>HBA</b>
                <small>{where.department?.name ?? ""}</small>
              </span>
            </span>
            <button type="button" className="strip__close" aria-label="Hide department names" onClick={close}>
              <Icon name="close" />
            </button>
          </div>
          <ul>
            {holdsToday(departments) && (
              <li>
                <Link to={TODAY} onClick={close}>
                  <Icon name="today" />
                  <span>Today</span>
                  {today && <span className="strip__count">{today.number}</span>}
                </Link>
              </li>
            )}
            {departments.map((department) => {
              const here = where.department === department;
              const mark = here || department.own ? null : departmentMark(department, waiting);
              return (
                <li key={department.key}>
                  <Link to={to(department)} aria-current={here ? "page" : undefined} onClick={close}>
                    <Icon name={department.icon} />
                    <span>{department.name}</span>
                    {mark?.alert && <span className="strip__red" title={mark.alert} />}
                    {mark?.count && <span className="strip__count">{mark.count.number}</span>}
                  </Link>
                </li>
              );
            })}
          </ul>
          <span className="strip__spacer" />
          {canOpenSettings(session) && (
            <ul>
              <li>
                <Link to="/settings/me" onClick={close}>
                  <Icon name="settings" />
                  <span>Settings</span>
                </Link>
              </li>
            </ul>
          )}
          <div className="strip__who">
            <span className="strip__avatar" aria-hidden="true">{initialsOf(session)}</span>
            <span>
              {who}
              <small>{roleLabel(session.actor)}</small>
            </span>
          </div>
        </div>
      )}
    </aside>
  );
}

/** HBA's thin bar over Production on a phone (frame 4): its button opens HBA's menu. */
export function StripPhoneBar({
  name,
  onOpen,
  menuButton,
}: {
  name: string;
  onOpen: () => void;
  menuButton: React.RefObject<HTMLButtonElement | null>;
}) {
  return (
    <header className="strip__hbar">
      <span className="strip__mark" aria-hidden="true">H</span>
      <b>
        HBA <small>· {name}</small>
      </b>
      <button ref={menuButton} type="button" className="strip__hbar-btn" aria-haspopup="dialog" onClick={onOpen}>
        <Icon name="grid" />
        Departments
      </button>
    </header>
  );
}
