import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, can } from "../../../lib/api";
import type { Session } from "../../../lib/api";
import { formatEgp } from "../../../lib/money";
import { FABRIC_SEARCH_HINT, blankFabric, fabricBody, fabricLine, fabricMatches, fabricProblem, kgWords } from "./fabricLogic";
import type { FabricDraft } from "./fabricLogic";
import type { FabricDetail, FabricRow } from "./types";
import { Actions, PanelShell, Problem, SearchBox, TextBox, useIsNarrow } from "./ui";

/** The fields of a fabric, shared by the Add panel here and the Edit panel on its page. */
export function FabricFields({ draft, onChange, adding }: { draft: FabricDraft; onChange: (draft: FabricDraft) => void; adding: boolean }) {
  const set = (key: keyof FabricDraft) => (value: string) => onChange({ ...draft, [key]: value });
  return (
    <>
      <TextBox label="Name" value={draft.name} onChange={set("name")} max={120} hint="What you call it, like Black fleece 320." />
      <TextBox label="Fabric type" value={draft.fabricType} onChange={set("fabricType")} max={400} hint="Like Cotton fleece 320 gsm." />
      <TextBox label="Colour" value={draft.colour} onChange={set("colour")} max={80} />
      <TextBox label="Colour code" value={draft.colourCode} onChange={set("colourCode")} max={200} />
      {adding && (
        <TextBox label="Already in storage, kg" value={draft.inStorage} onChange={set("inStorage")} inputMode="decimal" hint="Leave blank if none yet. Fabric you buy is added when you record the purchase." />
      )}
      <TextBox label="Notes" value={draft.note} onChange={set("note")} area wide max={2000} />
    </>
  );
}

function AddPanel({ onAdded, onClose }: { onAdded: (id: number) => void; onClose: () => void }) {
  const [draft, setDraft] = useState<FabricDraft>(blankFabric);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(event: FormEvent) {
    event.preventDefault();
    const problem = fabricProblem(draft, true);
    if (problem) return setError(problem);
    setError(null);
    setBusy(true);
    try {
      const answer = await api.post<{ fabric: FabricDetail["fabric"] }>("/api/prod/fabrics", fabricBody(draft, true));
      onAdded(answer.fabric.id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The fabric could not be added.");
      setBusy(false);
    }
  }

  return (
    <PanelShell title="Add a fabric" onClose={onClose}>
      <form className="prod-form" onSubmit={save} noValidate>
        <FabricFields draft={draft} onChange={setDraft} adding />
        <Actions error={error} busy={busy} label="Add fabric" working="Adding…" extra={<button type="button" className="button" onClick={onClose}>Cancel</button>} />
      </form>
    </PanelShell>
  );
}

type Show = "active" | "inactive";

/**
 * `/production/fabric` (ADR 0089): every fabric HBA keeps, and how many kilos of each are in storage.
 * Buying fabric by the kilo fills it; an order takes from it.
 */
export function FabricList({ session }: { session: Session }) {
  const canEdit = can(session, "production.edit");
  const withMoney = can(session, "production.owner");
  const narrow = useIsNarrow();
  const navigate = useNavigate();
  const [rows, setRows] = useState<FabricRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [show, setShow] = useState<Show>("active");
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    setError(null);
    api.get<{ fabrics: FabricRow[] }>("/api/prod/fabrics")
      .then((answer) => setRows(answer.fabrics))
      .catch((caught) => setError(caught instanceof Error ? caught.message : "Fabric storage could not be loaded."));
  }, []);
  useEffect(load, [load]);

  const active = (rows ?? []).filter((row) => row.active);
  const shown = useMemo(
    () => (rows ?? []).filter((row) => row.active === (show === "active") && fabricMatches(row, query)),
    [rows, show, query],
  );
  const totalKg = active.reduce((sum, row) => sum + Number(row.in_stock_kg), 0);
  const price = (row: FabricRow) => (row.price_per_kg_piastres == null ? "Not bought yet" : `${formatEgp(row.price_per_kg_piastres)} a kg`);
  const stockClass = (row: FabricRow) => (Number(row.in_stock_kg) <= 0 ? "prod-warn" : undefined);

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Fabric</h1>
          <span className="page__subtitle">
            {rows ? `${active.length} fabric${active.length === 1 ? "" : "s"} · ${kgWords(totalKg)} in storage` : "Loading"}
          </span>
        </div>
        {canEdit && rows && (
          <div className="prod-head-actions">
            <button type="button" className="button button--primary" onClick={() => setAdding(true)}>
              Add a fabric
            </button>
          </div>
        )}
      </div>

      {adding && <AddPanel onAdded={(id) => navigate(`/production/fabric/${id}`)} onClose={() => setAdding(false)} />}

      {error && (
        <div>
          <Problem>{error}</Problem>
          <button type="button" className="button" onClick={load}>
            Try again
          </button>
        </div>
      )}
      {!error && rows === null && <p className="loading" role="status">Loading fabric storage…</p>}

      {rows && (
        <>
          <SearchBox label="Search fabric" hint={FABRIC_SEARCH_HINT} value={query} onChange={setQuery} />
          <div className="prod-chips" role="group" aria-label="Show">
            {(["active", "inactive"] as const).map((key) => (
              <button key={key} type="button" className={`chip${show === key ? " chip--on" : ""}`} aria-pressed={show === key} onClick={() => setShow(key)}>
                {key === "active" ? "In use" : "No longer used"} · {(rows ?? []).filter((row) => row.active === (key === "active")).length}
              </button>
            ))}
          </div>

          {shown.length === 0 ? (
            <p className="empty">
              {rows.length === 0
                ? "No fabric yet. Add one, or record a fabric purchase in kg and put it into storage."
                : query.trim()
                  ? "No fabric matches."
                  : "No fabric here."}
            </p>
          ) : narrow ? (
            <div className="prod-cards">
              {shown.map((row) => (
                <article key={row.id} className="prod-card">
                  <Link className="prod-rowlink" to={`/production/fabric/${row.id}`}>
                    {row.name}
                  </Link>
                  {fabricLine(row) && <div className="prod-small">{fabricLine(row)}</div>}
                  <div>
                    <b className={stockClass(row)}>{kgWords(row.in_stock_kg)}</b> in storage
                  </div>
                  <div className="prod-small">
                    {kgWords(row.bought_kg)} bought · {kgWords(row.used_kg)} used{withMoney ? ` · ${price(row)}` : ""}
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="surface prod-list">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Fabric</th>
                    <th scope="col" className="numeric">In storage</th>
                    <th scope="col" className="numeric">Bought</th>
                    <th scope="col" className="numeric">Used</th>
                    {withMoney && <th scope="col">Price</th>}
                    <th scope="col">Orders using it</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((row) => (
                    <tr key={row.id}>
                      <td>
                        <Link className="prod-rowlink" to={`/production/fabric/${row.id}`}>
                          {row.name}
                        </Link>
                        {fabricLine(row) && <div className="prod-small">{fabricLine(row)}</div>}
                      </td>
                      <td className="numeric">
                        <b className={stockClass(row)}>{kgWords(row.in_stock_kg)}</b>
                      </td>
                      <td className="numeric">{kgWords(row.bought_kg)}</td>
                      <td className="numeric">{kgWords(row.used_kg)}</td>
                      {withMoney && <td>{price(row)}</td>}
                      <td>{row.orders === 0 ? "None now" : `${row.orders} open`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}
