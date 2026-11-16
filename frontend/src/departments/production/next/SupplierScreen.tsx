import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, can } from "../../../lib/api";
import type { Session } from "../../../lib/api";
import { PurchaseForm } from "./PurchaseForm";
import { SectionBar } from "./SectionBar";
import { SupplierForm } from "./SupplierForms";
import { listSentence, openWords, owedWords, ratingLine, sectionNames, visibleSuppliers } from "./supplierLogic";
import type { SectionFilter, SupplierPowers } from "./supplierLogic";
import type { Section, SupplierAnswer, SupplierList, SupplierRow } from "./types";
import { Problem, useIsNarrow } from "./ui";
import type { Run } from "./ui";

type Panel = "add" | "purchase";

/** What a supplier owes or is owed, in words, for the owner's list. */
function Owed({ row }: { row: SupplierRow }) {
  if (row.owed_piastres === undefined) return null;
  const tone = row.owed_piastres > 0 ? "prod-warn" : row.owed_piastres < 0 ? "prod-ok" : undefined;
  return <span className={tone}>{owedWords(row.owed_piastres)}</span>;
}

function Row({ row, narrow }: { row: SupplierRow; narrow: boolean }) {
  return (
    <li className={`prod-task${narrow ? " prod-task--narrow" : ""}`}>
      <div className="prod-task__what">
        <Link className="prod-rowlink" to={`/production/next/suppliers/${row.id}`}>
          {row.name}
        </Link>
        <div className="prod-small">
          {sectionNames(row.sections)} · {openWords(row)}
        </div>
        <div className="prod-small">{ratingLine(row)}</div>
      </div>
      <div className="prod-task__side">
        {!row.active && <span className="prod-pill">Inactive</span>}
        <Owed row={row} />
      </div>
    </li>
  );
}

/** `/production/next/suppliers`: every supplier, by section, with what is open and (for the owner) what is owed. */
export function SupplierScreen({ session }: { session: Session }) {
  const powers = useMemo<SupplierPowers>(
    () => ({
      canEdit: can(session, "production.edit"),
      isOwner: can(session, "production.owner"),
      canManage: can(session, "production.suppliers"),
    }),
    [session],
  );
  const narrow = useIsNarrow();
  const [data, setData] = useState<SupplierList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<SectionFilter>("all");
  const [showInactive, setShowInactive] = useState(false);
  const [panel, setPanel] = useState<Panel | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const trigger = useRef<Element | null>(null);
  // Which answer is the newest, and whether the screen is still there: an answer that an earlier request
  // delivers late, or one for a screen that has been left, is dropped.
  const latest = useRef(0);
  const alive = useRef(true);
  const inactiveToggle = useId();

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      latest.current += 1;
    };
  }, []);

  const load = useCallback(() => {
    const mine = ++latest.current;
    api.get<SupplierList>("/api/prod/suppliers")
      .then((answer) => {
        if (latest.current !== mine) return;
        setData(answer);
        setError(null);
      })
      .catch((caught) => {
        if (latest.current === mine) setError(caught instanceof Error ? caught.message : "The suppliers could not be loaded.");
      });
  }, []);
  useEffect(load, [load]);

  function openPanel(next: Panel, from: Element | null) {
    trigger.current = from;
    setNotice(null);
    setPanel(next);
  }

  function closePanel() {
    setPanel(null);
    queueMicrotask(() => {
      const back = trigger.current;
      if (back instanceof HTMLElement && back.isConnected) back.focus();
      else heading.current?.focus();
    });
  }

  // A panel's write: on success the list is read again and the panel closes; a refusal is the panel's to show.
  const run = useCallback<Run<SupplierAnswer>>(
    async (request, done) => {
      try {
        const answer = await request();
        if (!alive.current) return null;
        setPanel(null);
        setNotice(answer.notice ?? done);
        load();
        queueMicrotask(() => {
          const back = trigger.current;
          if (back instanceof HTMLElement && back.isConnected) back.focus();
          else heading.current?.focus();
        });
        return null;
      } catch (caught) {
        return caught instanceof Error ? caught.message : "It could not be saved.";
      }
    },
    [load],
  );

  function sectionsChanged(sections: Section[], said: string, change: "added" | "renamed" | "removed", id?: number) {
    setData((before) => (before ? { ...before, sections } : before));
    setNotice(said);
    if (change === "renamed") load(); // the rows carry the section's name
    if (change === "removed") {
      if (filter === id) setFilter("all");
      heading.current?.focus();
    }
  }

  const rows = data?.suppliers ?? [];
  const shown = visibleSuppliers(rows, filter, showInactive);
  const active = rows.filter((row) => row.active);
  const hasInactive = rows.some((row) => !row.active);
  const emptyWords = rows.length === 0 ? "There are no suppliers yet." : filter === "all" ? "No suppliers to show." : "No suppliers in this section.";

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1 ref={heading} tabIndex={-1}>Suppliers</h1>
          <span className="page__subtitle">{data ? listSentence(active.length, data.owed_total_piastres) : "Loading"}</span>
        </div>
        {(powers.isOwner || powers.canManage) && (
          <div className="prod-head-actions">
            {powers.isOwner && (
              <button type="button" className="button" onClick={(event) => openPanel("purchase", event.currentTarget)}>
                Record a purchase
              </button>
            )}
            {powers.canManage && (
              <button type="button" className="button button--primary" onClick={(event) => openPanel("add", event.currentTarget)}>
                Add supplier
              </button>
            )}
          </div>
        )}
      </div>

      {notice && <p className="notice notice--settled" role="status">{notice}</p>}

      {panel === "add" && <SupplierForm key="add" sections={data?.sections} run={run} onClose={closePanel} />}
      {panel === "purchase" && (
        <PurchaseForm
          key="purchase"
          suppliers={active.map((row) => ({ id: row.id, name: row.name }))}
          run={run}
          onClose={closePanel}
        />
      )}

      {error && (
        <div>
          <Problem>{error}</Problem>
          <button type="button" className="button" onClick={load}>
            Try again
          </button>
        </div>
      )}

      {!error && data === null && <p className="loading" role="status">Loading suppliers…</p>}

      {data && (
        <>
          <SectionBar
            sections={data.sections}
            rows={rows}
            filter={filter}
            onFilter={setFilter}
            showInactive={showInactive}
            canManage={powers.canManage}
            onSections={sectionsChanged}
          />
          {hasInactive && (
            <label className="prod-check" htmlFor={inactiveToggle}>
              <input id={inactiveToggle} type="checkbox" checked={showInactive} onChange={(event) => setShowInactive(event.target.checked)} />
              Show inactive
            </label>
          )}
          {shown.length === 0 ? (
            <p className="empty">{emptyWords}</p>
          ) : (
            <ul className="surface prod-tasks" aria-label="Suppliers">
              {shown.map((row) => (
                <Row key={row.id} row={row} narrow={narrow} />
              ))}
            </ul>
          )}
        </>
      )}
    </>
  );
}
