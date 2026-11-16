import { useCallback, useEffect, useState } from "react";

import { api, can } from "../../../lib/api";
import type { Session } from "../../../lib/api";
import { cairoDay, plural, shortDay } from "./format";
import { isBlank } from "./logic";
import type { StageDaysRow } from "./types";
import { Problem } from "./ui";

type StageDaysAnswer = { stages: StageDaysRow[] };

/** `/production/settings`: the typical days each stage takes. The owner changes them; everybody else reads them. */
export function StageDays({ session }: { session: Session }) {
  const isOwner = can(session, "production.owner");
  const [rows, setRows] = useState<StageDaysRow[] | null>(null);
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const show = useCallback((answer: StageDaysAnswer) => {
    setRows(answer.stages);
    setTyped(Object.fromEntries(answer.stages.map((row) => [row.stage, String(row.days)])));
  }, []);

  const load = useCallback(() => {
    setError(null);
    api.get<StageDaysAnswer>("/api/prod/settings/stage-days")
      .then(show)
      .catch((caught) => setError(caught instanceof Error ? caught.message : "The typical days could not be loaded."));
  }, [show]);
  useEffect(load, [load]);

  const changed = (rows ?? []).filter((row) => typed[row.stage] !== String(row.days));

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setNotice(null);
    for (const row of changed) {
      const text = typed[row.stage] ?? "";
      if (isBlank(text) || !/^\d{1,3}$/.test(text.trim()) || Number(text) > 365) {
        setProblem(`${row.label}: give a number of days from 0 to 365.`);
        return;
      }
    }
    setProblem(null);
    setBusy(true);
    try {
      const answer = await api.put<StageDaysAnswer>("/api/prod/settings/stage-days", {
        days: Object.fromEntries(changed.map((row) => [row.stage, Number(typed[row.stage])])),
      });
      show(answer);
      setNotice("Saved. New orders will use these days.");
    } catch (caught) {
      setProblem(caught instanceof Error ? caught.message : "The days could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Stage days</h1>
          <span className="page__subtitle">How long each stage usually takes</span>
        </div>
      </div>
      <p className="prod-panel__intro">
        A new order counts back from its target date with these days to suggest an expected date for every stage. Orders already made keep the dates they have.
      </p>
      {error && (
        <div>
          <Problem>{error}</Problem>
          <button type="button" className="button" onClick={load}>Try again</button>
        </div>
      )}
      {!rows && !error && <p className="loading" role="status">Loading…</p>}
      {rows && !isOwner && (
        <div className="surface">
          <table className="table">
            <thead>
              <tr><th scope="col">Stage</th><th scope="col" className="numeric">Typical days</th><th scope="col">Last changed</th></tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.stage}>
                  <td>{row.label}</td>
                  <td className="numeric">{plural(row.days, "day")}</td>
                  <td className="prod-small">{row.updated_at ? `${shortDay(cairoDay(row.updated_at))}${row.updated_by ? ` · ${row.updated_by}` : ""}` : "As first set"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows && isOwner && (
        <div className="prod-block">
          <form className="prod-form" onSubmit={save} noValidate>
            {rows.map((row) => (
              <div key={row.stage} className="prod-field">
                <label className="field__label" htmlFor={`days-${row.stage}`}>{row.label}, days</label>
                <input
                  id={`days-${row.stage}`}
                  className="input"
                  inputMode="numeric"
                  autoComplete="off"
                  value={typed[row.stage] ?? ""}
                  onChange={(event) => setTyped({ ...typed, [row.stage]: event.target.value })}
                />
                <span className="field__hint">
                  {row.updated_at ? `Last changed ${shortDay(cairoDay(row.updated_at))}${row.updated_by ? ` by ${row.updated_by}` : ""}` : "As first set"}
                </span>
              </div>
            ))}
            <div className="prod-wide">
              {problem && <Problem>{problem}</Problem>}
              {notice && <p className="notice notice--settled" role="status">{notice}</p>}
              <div className="prod-actions">
                <button type="submit" className="button button--primary" disabled={busy || changed.length === 0}>
                  {busy ? "Saving…" : "Save"}
                </button>
              </div>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
