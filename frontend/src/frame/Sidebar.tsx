import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { clockTime } from "../components/OpsSource";
import type { Department, DepartmentSection } from "../departments/types";
import { api, roleLabel, signOutAndLeave } from "../lib/api";
import type { Session } from "../lib/api";
import { pickMaintainerChoice, storedMaintainerChoice } from "../lib/theme";
import type { ThemeChoice } from "../lib/theme";
import { Icon } from "./Icon";
import type { Waiting } from "./useWaiting";
import { canOpenSettings } from "./where";
import type { Where } from "./where";

const THEMES: [ThemeChoice, string][] = [
  ["dark", "Dark"],
  ["light", "Light"],
  ["system", "Match my device"],
];

/** What waits at one section, or in a folded department. Nothing waiting: nothing drawn. */
type Mark = {
  count: { number: number; sentence: string; settled: boolean } | null;
  alert: string | null;
};

/**
 * `since` is the last clean read. When the failures began is not recorded
 * (each failed attempt rewrites its time), so the sentence claims no more
 * than that: not read since the last time it was.
 */
function failedSentence(label: string | null, since: string | null | undefined): string {
  const what = since ? `not read since ${clockTime(since)}` : "could not be read";
  return label ? `${label} ${what}` : `${what[0].toUpperCase()}${what.slice(1)}`;
}

function sectionMark(section: DepartmentSection, waiting: Waiting): Mark {
  const found = section.count ? waiting.counts[section.count.key] : undefined;
  const failing = section.alert !== undefined && section.alert in waiting.failures;
  return {
    count:
      section.count && typeof found === "number" && found > 0
        ? { number: found, sentence: section.count.sentence(found), settled: section.count.settled === true }
        : null,
    alert: failing ? failedSentence(null, waiting.failures[section.alert as string]) : null,
  };
}

/** A folded department adds up its sections, or shows the dot if any has one. */
function departmentMark(department: Department, waiting: Waiting): Mark {
  const marks = department.sections.map((section) => sectionMark(section, waiting));
  const counted = marks.filter((mark) => mark.count !== null);
  const failed = department.sections.flatMap((section, index) =>
    marks[index].alert !== null
      ? [failedSentence(section.label, waiting.failures[section.alert as string])]
      : [],
  );
  return {
    count: counted.length
      ? {
          number: counted.reduce((sum, mark) => sum + (mark.count?.number ?? 0), 0),
          sentence: counted.map((mark) => mark.count?.sentence).join(", "),
          settled: false,
        }
      : null,
    alert: failed.length ? failed.join(". ") : null,
  };
}

function Count({ mark }: { mark: NonNullable<Mark["count"]> }) {
  return (
    <span className={mark.settled ? "frame__count frame__count--settled" : "frame__count"}>
      <span aria-hidden="true">{mark.number}</span>
      <span className="visually-hidden"> {mark.sentence}</span>
    </span>
  );
}

function Alert({ sentence }: { sentence: string }) {
  return (
    <span className="frame__alert" title={sentence}>
      <span className="visually-hidden"> {sentence}</span>
    </span>
  );
}

/** The brand: the mark, "HBA", and the department you are in. */
export function Brand({ role }: { role: string }) {
  return (
    <div className="frame__brand">
      <span className="frame__mark" aria-hidden="true">H</span>
      <span>
        <span className="frame__name">HBA</span>
        <span className="frame__role">{role}</span>
      </span>
    </div>
  );
}

/**
 * The person at the foot: avatar, name and the role's words, opening a menu
 * with the theme, Team and access, and Sign out. The theme lives here because
 * the operations manager and customer service have no Settings to choose it in.
 */
function Account({ session, onNavigate }: { session: Session; onNavigate: () => void }) {
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useState<ThemeChoice>(storedMaintainerChoice());
  const wrap = useRef<HTMLDivElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      if (!wrap.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  function choose(choice: ThemeChoice) {
    pickMaintainerChoice(choice);
    setTheme(choice);
    api.put("/api/staff/me/theme", { theme: choice }).catch(() => undefined);
  }

  const who = session.actor.display_name || session.actor.email;
  const initials = who
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word.charAt(0).toUpperCase())
    .join("");

  return (
    <div
      className="frame__account-wrap"
      ref={wrap}
      onKeyDown={(event) => {
        if (event.key !== "Escape" || !open) return;
        // Only the menu closes - not the phone menu it may sit in.
        event.stopPropagation();
        setOpen(false);
        toggle.current?.focus();
      }}
    >
      {open && (
        <div id={menuId} className="frame__menu">
          <div className="frame__themes" role="group" aria-label="Theme">
            {THEMES.map(([value, label]) => (
              <button key={value} type="button" aria-pressed={theme === value} onClick={() => choose(value)}>
                {label}
              </button>
            ))}
          </div>
          {canOpenSettings(session) && (
            <Link
              to="/settings?section=team"
              onClick={() => {
                setOpen(false);
                onNavigate();
              }}
            >
              Team and access
            </Link>
          )}
          <button type="button" onClick={signOutAndLeave}>Sign out</button>
        </div>
      )}
      <button
        type="button"
        ref={toggle}
        className="frame__account"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen(!open)}
      >
        <span className="frame__avatar" aria-hidden="true">{initials}</span>
        <span className="frame__who">
          <span>{who}</span>
          <small>{roleLabel(session.actor)}</small>
        </span>
        <Icon name="down" />
      </button>
    </div>
  );
}

/**
 * The departments, Settings and the account: what the sidebar and the phone's
 * full-screen menu both hold.
 *
 * The department you are in is open; the others are folded and show what
 * waits in them. Pressing a folded one opens it where it stands, without
 * going anywhere, and pressing the open one folds it. Moving to another
 * address puts it back to the department of that address.
 */
export function SideBody({
  session,
  departments,
  where,
  pathname,
  waiting,
  onNavigate,
}: {
  session: Session;
  departments: readonly Department[];
  where: Where;
  pathname: string;
  waiting: Waiting;
  /** The phone's menu closes when something is chosen. */
  onNavigate: () => void;
}) {
  const current = where.department?.key ?? null;
  const [fold, setFold] = useState<{ at: string; open: string | null }>({ at: pathname, open: current });
  let open = fold.open;
  if (fold.at !== pathname) {
    open = current;
    setFold({ at: pathname, open: current });
  }
  const sectionsId = useId();

  return (
    <>
      <nav className="frame__nav" aria-label="Departments">
        <ul className="frame__depts">
          {departments.map((department) => {
            const isOpen = open === department.key;
            const mark = isOpen ? null : departmentMark(department, waiting);
            return (
              <li key={department.key}>
                <button
                  type="button"
                  className="frame__dept"
                  aria-expanded={isOpen}
                  // Only a list that is drawn can be pointed at.
                  aria-controls={isOpen ? `${sectionsId}-${department.key}` : undefined}
                  onClick={() => setFold({ at: pathname, open: isOpen ? null : department.key })}
                >
                  <Icon name={department.icon} />
                  <span className="frame__dept-name">{department.name}</span>
                  {mark?.alert && <Alert sentence={mark.alert} />}
                  {mark?.count && <Count mark={mark.count} />}
                  <Icon name="chev" className="frame__chev" />
                </button>
                {isOpen && (
                  <ul className="frame__sections" id={`${sectionsId}-${department.key}`}>
                    {department.sections.map((section) => {
                      const here = where.section === section;
                      const sectionState = sectionMark(section, waiting);
                      return (
                        <li key={section.slug}>
                          <Link
                            to={section.to}
                            aria-current={here ? "page" : undefined}
                            onClick={onNavigate}
                          >
                            <span>{section.label}</span>
                            {sectionState.alert && <Alert sentence={sectionState.alert} />}
                            {sectionState.count && <Count mark={sectionState.count} />}
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      </nav>

      {canOpenSettings(session) && (
        <div className="frame__foot">
          <ul className="frame__depts">
            <li>
              <Link
                to="/settings"
                className="frame__dept"
                aria-current={where.settings ? "page" : undefined}
                onClick={onNavigate}
              >
                <Icon name="settings" />
                <span className="frame__dept-name">Settings</span>
              </Link>
            </li>
          </ul>
        </div>
      )}

      <Account session={session} onNavigate={onNavigate} />
    </>
  );
}

/** The sidebar on a laptop: 216px, brand on top, the departments, the person. */
export function Sidebar(props: {
  session: Session;
  departments: readonly Department[];
  where: Where;
  pathname: string;
  waiting: Waiting;
  role: string;
}) {
  const { role, ...body } = props;
  return (
    <aside className="frame__side">
      <Brand role={role} />
      <SideBody {...body} onNavigate={() => undefined} />
    </aside>
  );
}
