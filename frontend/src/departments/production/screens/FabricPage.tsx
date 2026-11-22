import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api, can } from "../../../lib/api";
import type { Session } from "../../../lib/api";
import { formatEgp } from "../../../lib/money";
import { FabricFields } from "./FabricList";
import { KG_PROBLEM, countOf, fabricBody, fabricDraft, fabricLine, fabricProblem, kgWords, moveWords, signedKg } from "./fabricLogic";
import type { FabricDraft } from "./fabricLogic";
import { cairoDay, shortDay } from "./format";
import { isBlank } from "./logic";
import type { FabricDetail } from "./types";
import { Actions, PanelShell, Problem, TextBox } from "./ui";

function EditPanel({ detail, onSaved, onClose }: { detail: FabricDetail; onSaved: (next: FabricDetail) => void; onClose: () => void }) {
  const [draft, setDraft] = useState<FabricDraft>(() => fabricDraft(detail.fabric));
  const [active, setActive] = useState(detail.fabric.active);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(event: FormEvent) {
    event.preventDefault();
    const problem = fabricProblem(draft, false);
    if (problem) return setError(problem);
    setError(null);
    setBusy(true);
    try {
      onSaved(await api.patch<FabricDetail>(`/api/prod/fabrics/${detail.fabric.id}`, { ...fabricBody(draft, false), active }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The fabric could not be saved.");
      setBusy(false);
    }
  }

  return (
    <PanelShell title="Edit fabric" onClose={onClose}>
      <form className="prod-form" onSubmit={save} noValidate>
        <FabricFields draft={draft} onChange={setDraft} adding={false} />
        <label className="prod-check prod-wide">
          <input type="checkbox" checked={!active} onChange={(event) => setActive(!event.target.checked)} />
          No longer used: hide it from new orders and purchases
        </label>
        <Actions error={error} busy={busy} label="Save fabric" working="Saving…" extra={<button type="button" className="button" onClick={onClose}>Cancel</button>} />
      </form>
    </PanelShell>
  );
}

function CountPanel({ detail, onSaved, onClose }: { detail: FabricDetail; onSaved: (next: FabricDetail) => void; onClose: () => void }) {
  const [kg, setKg] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(event: FormEvent) {
    event.preventDefault();
    const counted = countOf(kg);
    if (counted === null) return setError(KG_PROBLEM);
    if (isBlank(note)) return setError("Say why storage is being corrected, like waste or a recount.");
    setError(null);
    setBusy(true);
    try {
      onSaved(await api.post<FabricDetail>(`/api/prod/fabrics/${detail.fabric.id}/count`, { kg_in_storage: counted, note: note.trim() }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The count could not be saved.");
      setBusy(false);
    }
  }

  return (
    <PanelShell
      title="Count storage"
      intro={`The platform has ${kgWords(detail.fabric.in_stock_kg)} of ${detail.fabric.name}. Type what is really there; the difference is recorded with your reason.`}
      onClose={onClose}
    >
      <form className="prod-form" onSubmit={save} noValidate>
        <TextBox label="Kilos in storage now" value={kg} onChange={setKg} inputMode="decimal" />
        <TextBox label="Why" value={note} onChange={setNote} max={400} hint="Like Waste after cutting, or Recounted the rolls." />
        <Actions error={error} busy={busy} label="Save count" working="Saving…" extra={<button type="button" className="button" onClick={onClose}>Cancel</button>} />
      </form>
    </PanelShell>
  );
}

/** `/production/fabric/:id` (ADR 0089): one fabric, its kilos, and every kilo in and out. */
export function FabricPage({ session }: { session: Session }) {
  const { id = "" } = useParams();
  const canEdit = can(session, "production.edit");
  const [detail, setDetail] = useState<FabricDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [panel, setPanel] = useState<"edit" | "count" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api.get<FabricDetail>(`/api/prod/fabrics/${encodeURIComponent(id)}`)
      .then(setDetail)
      .catch((caught) => setError(caught instanceof Error ? caught.message : "The fabric could not be loaded."));
  }, [id]);
  useEffect(load, [load]);

  const back = <Link className="prod-back" to="/production/fabric">← Fabric</Link>;
  if (!detail) {
    return (
      <>
        {back}
        {error ? <Problem>{error}</Problem> : <p className="loading" role="status">Loading the fabric…</p>}
      </>
    );
  }

  const { fabric, moves } = detail;
  const saved = (next: FabricDetail, words: string) => {
    setDetail(next);
    setPanel(null);
    setNotice(words);
  };

  return (
    <>
      {back}
      <div className="page__head">
        <div className="page__title">
          <h1>{fabric.name}</h1>
          <span className="page__subtitle">
            {[fabricLine(fabric), fabric.colour_code, fabric.active ? null : "No longer used"].filter(Boolean).join(" · ") || "Fabric"}
          </span>
        </div>
        {canEdit && (
          <div className="prod-head-actions">
            <button type="button" className="button" onClick={() => setPanel("count")}>
              Count storage
            </button>
            <button type="button" className="button" onClick={() => setPanel("edit")}>
              Edit
            </button>
          </div>
        )}
      </div>

      {notice && <p className="notice notice--settled" role="status">{notice}</p>}
      {panel === "edit" && <EditPanel detail={detail} onSaved={(next) => saved(next, "Fabric saved.")} onClose={() => setPanel(null)} />}
      {panel === "count" && <CountPanel detail={detail} onSaved={(next) => saved(next, "Count saved.")} onClose={() => setPanel(null)} />}

      <dl className="prod-facts">
        <div>
          <dt>In storage</dt>
          <dd className={Number(fabric.in_stock_kg) <= 0 ? "prod-warn" : undefined}>{kgWords(fabric.in_stock_kg)}</dd>
        </div>
        <div>
          <dt>Bought</dt>
          <dd>{kgWords(fabric.bought_kg)}</dd>
        </div>
        <div>
          <dt>Used by orders</dt>
          <dd>{kgWords(fabric.used_kg)}</dd>
        </div>
        {fabric.price_per_kg_piastres !== undefined && (
          <div>
            <dt>Price a kg</dt>
            <dd>{fabric.price_per_kg_piastres === null ? "Not bought yet" : formatEgp(fabric.price_per_kg_piastres)}</dd>
          </div>
        )}
      </dl>

      {(fabric.supplier || fabric.note) && (
        <dl className="prod-details prod-block">
          {fabric.supplier && (
            <div>
              <dt>Usual supplier</dt>
              <dd>
                <Link to={`/production/suppliers/${fabric.supplier.id}`}>{fabric.supplier.name}</Link>
              </dd>
            </div>
          )}
          {fabric.note && (
            <div>
              <dt>Notes</dt>
              <dd>{fabric.note}</dd>
            </div>
          )}
        </dl>
      )}

      <section className="prod-block" aria-labelledby="fabric-moves">
        <h2 id="fabric-moves">Every kilo in and out</h2>
        {moves.length === 0 ? (
          <p className="empty">Nothing yet. Record a fabric purchase in kg and put it into this fabric, or count what is in storage.</p>
        ) : (
          <div className="prod-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">What</th>
                  <th scope="col" className="numeric">Kilos</th>
                  <th scope="col">By</th>
                </tr>
              </thead>
              <tbody>
                {moves.map((move) => (
                  <tr key={move.id}>
                    <td>{shortDay(cairoDay(move.created_at))}</td>
                    <td>
                      {move.order && (move.kind === "use" || move.kind === "return") ? (
                        <>
                          {move.kind === "use" ? "Taken by " : "Given back by "}
                          <Link to={`/production/orders/${move.order.id}`}>{move.order.code}</Link>
                          {move.kind === "use" && move.returned ? " (given back since)" : ""}
                        </>
                      ) : (
                        moveWords(move)
                      )}
                      {move.note && <div className="prod-small">{move.note}</div>}
                    </td>
                    <td className={`numeric${Number(move.kg) < 0 ? " prod-warn" : ""}`}>{signedKg(move.kg)}</td>
                    <td>{move.by ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
