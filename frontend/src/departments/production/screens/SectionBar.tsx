import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { api } from "../../../lib/api";
import { chipCount, removable } from "./supplierLogic";
import type { SectionFilter } from "./supplierLogic";
import type { Section, SectionsAnswer, SupplierRow } from "./types";
import { Problem } from "./ui";

/** What the bar is doing beside the chips: naming a new section, renaming one, or asking before removing one. */
type Editing = { kind: "add" } | { kind: "rename"; section: Section } | { kind: "remove"; section: Section };

type Props = {
  sections: readonly Section[];
  rows: readonly SupplierRow[];
  filter: SectionFilter;
  onFilter: (filter: SectionFilter) => void;
  showInactive: boolean;
  /** `production.suppliers`: add, rename and remove. */
  canManage: boolean;
  /** The sections as the server now has them. `renamed` and `removed` ask the list to read its rows again. */
  onSections: (sections: Section[], notice: string, change: "added" | "renamed" | "removed", id?: number) => void;
};

/**
 * The section chips, with their counts, and (for `production.suppliers`) adding, renaming and removing a
 * section. A section can be removed only while no supplier is in it; the server's refusal is shown if it
 * still says no.
 */
export function SectionBar({ sections, rows, filter, onFilter, showInactive, canManage, onSections }: Props) {
  const [editing, setEditing] = useState<Editing | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const keep = useRef<HTMLButtonElement>(null);
  // The id of the control to give focus back to once the bar has drawn without what it was editing.
  const returnTo = useRef<string | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // Choosing another chip closes whatever was being edited for the one before.
  useEffect(() => {
    setEditing(null);
    setError(null);
  }, [filter]);

  useEffect(() => {
    if (editing !== null || returnTo.current === null) return;
    document.getElementById(returnTo.current)?.focus();
    returnTo.current = null;
  }, [editing]);

  // The name box, or the safe answer of a question, takes focus when it opens.
  useEffect(() => {
    if (editing?.kind === "remove") keep.current?.focus();
    else if (editing) input.current?.focus();
  }, [editing]);

  const unsectioned = rows.some((row) => row.sections.length === 0);
  const selected = typeof filter === "number" ? sections.find((section) => section.id === filter) : undefined;

  function start(next: Editing, trigger: string) {
    setError(null);
    setName(next.kind === "rename" ? next.section.name : "");
    setEditing(next);
    returnTo.current = trigger;
  }
  function stop() {
    setEditing(null);
    setError(null);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!editing || editing.kind === "remove") return;
    const typed = name.trim();
    if (!typed) {
      setError("Give the section a name.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (editing.kind === "add") {
        const answer = await api.post<SectionsAnswer>("/api/prod/sections", { name: typed });
        if (!alive.current) return;
        onSections(answer.sections, `Added the ${typed} section.`, "added", answer.section_id);
      } else {
        const answer = await api.patch<SectionsAnswer>(`/api/prod/sections/${editing.section.id}`, { name: typed });
        if (!alive.current) return;
        onSections(answer.sections, `Renamed ${editing.section.name} to ${typed}.`, "renamed", editing.section.id);
      }
      setEditing(null);
    } catch (caught) {
      if (alive.current) setError(caught instanceof Error ? caught.message : "The section could not be saved.");
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  async function remove(section: Section) {
    setBusy(true);
    setError(null);
    try {
      const answer = await api.del<SectionsAnswer>(`/api/prod/sections/${section.id}`);
      if (!alive.current) return;
      setEditing(null);
      onSections(answer.sections, `Removed the ${section.name} section.`, "removed", section.id);
    } catch (caught) {
      if (alive.current) setError(caught instanceof Error ? caught.message : "The section could not be removed.");
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  const chip = (key: SectionFilter, label: string) => (
    <button
      key={String(key)}
      type="button"
      className={`chip${filter === key ? " chip--on" : ""}`}
      aria-pressed={filter === key}
      onClick={() => onFilter(key)}
    >
      {label} · {chipCount(rows, key, showInactive)}
    </button>
  );

  return (
    <>
      <div className="prod-chips" role="group" aria-label="Sections">
        {chip("all", "All")}
        {sections.map((section) => chip(section.id, section.name))}
        {unsectioned && chip("none", "No section")}
        {canManage && (
          <button id="section-add" type="button" className="chip" onClick={() => start({ kind: "add" }, "section-add")}>
            + Add section
          </button>
        )}
      </div>

      {canManage && selected && !editing && (
        <div className="prod-sectionbar">
          <span className="prod-small">The {selected.name} section:</span>
          <button id="section-rename" type="button" className="button button--row" onClick={() => start({ kind: "rename", section: selected }, "section-rename")}>
            Rename<span className="prod-sr"> {selected.name}</span>
          </button>
          {removable(selected) ? (
            <button id="section-remove" type="button" className="button button--row" onClick={() => start({ kind: "remove", section: selected }, "section-remove")}>
              Remove<span className="prod-sr"> {selected.name}</span>
            </button>
          ) : (
            <span className="prod-small">
              It can be removed once no supplier is in it ({selected.supplier_count} {selected.supplier_count === 1 ? "is" : "are"}, counting inactive ones).
            </span>
          )}
        </div>
      )}

      {editing && editing.kind !== "remove" && (
        <form className="prod-sectionbar prod-sectionbar--form" onSubmit={save} noValidate>
          <label className="field__label" htmlFor="section-name">
            {editing.kind === "add" ? "Name of the new section" : `New name for ${editing.section.name}`}
          </label>
          <input
            ref={input}
            id="section-name"
            className="input"
            value={name}
            maxLength={60}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") stop();
            }}
          />
          <button type="submit" className="button button--row button--primary" disabled={busy}>
            {busy ? "Saving…" : editing.kind === "add" ? "Add section" : "Save name"}
          </button>
          <button type="button" className="button button--row" onClick={stop}>
            Cancel
          </button>
        </form>
      )}

      {editing?.kind === "remove" && (
        <div className="prod-sectionbar" role="group" aria-label={`Remove ${editing.section.name}`}>
          <span id="section-remove-question">Remove the {editing.section.name} section?</span>
          <button type="button" className="button button--row" disabled={busy} onClick={() => remove(editing.section)}>
            Remove section
          </button>
          <button ref={keep} type="button" className="button button--row" aria-describedby="section-remove-question" onClick={stop}>
            Keep it
          </button>
        </div>
      )}

      {error && <Problem>{error}</Problem>}
    </>
  );
}
