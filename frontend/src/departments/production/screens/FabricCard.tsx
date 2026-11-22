import "./fabric.css";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";

import { api } from "../../../lib/api";
import { KG_PROBLEM, kgOf, kgWords } from "./fabricLogic";
import type { Powers } from "./logic";
import type { FabricRow, OrderAnswer, OrderView } from "./types";
import { Problem, useSubmit } from "./ui";
import type { Run } from "./ui";

/**
 * The fabric an order took from storage (ADR 0089), in kilos and with no price: take more while the order
 * is open, or give some back. Drawn when HBA buys the order's fabric, or when the order holds some.
 */
export function FabricCard({ order, powers, run }: { order: OrderView; powers: Powers; run: Run }) {
  const uses = order.fabric_uses ?? [];
  const hbaBuys = order.fabric_bought_by === "hba";
  const editable = powers.canEdit && order.status === "open" && hbaBuys;
  const { error, busy, submit } = useSubmit(run);
  const [taking, setTaking] = useState(false);
  const [fabrics, setFabrics] = useState<FabricRow[] | null>(null);
  const [fabricId, setFabricId] = useState("");
  const [kg, setKg] = useState("");
  const [confirming, setConfirming] = useState<number | null>(null);

  // The fabrics to choose from, read when the form first opens.
  useEffect(() => {
    if (!taking || fabrics !== null) return;
    let current = true;
    api.get<{ fabrics: FabricRow[] }>("/api/prod/fabrics")
      .then((answer) => current && setFabrics(answer.fabrics.filter((row) => row.active && Number(row.in_stock_kg) > 0)))
      .catch(() => current && setFabrics([]));
    return () => {
      current = false;
    };
  }, [taking, fabrics]);

  if (!hbaBuys && uses.length === 0) return null;

  function take(event: FormEvent) {
    event.preventDefault();
    const kilos = kgOf(kg);
    const chosen = fabrics?.find((row) => String(row.id) === fabricId);
    const problem = !chosen ? "Choose a fabric from storage." : kilos === null ? KG_PROBLEM : null;
    submit(
      problem,
      () => api.post<OrderAnswer>(`/api/prod/orders/${order.id}/fabric`, { fabric_id: chosen?.id, kg: kilos }),
      `Took ${kgWords(kilos ?? 0)} of ${chosen?.name ?? "fabric"} from storage.`,
    ).then((saved) => {
      if (!saved) return;
      setTaking(false);
      setFabrics(null);
      setFabricId("");
      setKg("");
    });
  }

  function giveBack(moveId: number, words: string) {
    submit(null, () => api.del<OrderAnswer>(`/api/prod/orders/${order.id}/fabric/${moveId}`), `Gave back ${words} to storage.`).then(() =>
      setConfirming(null),
    );
  }

  return (
    <section className="prod-block" aria-labelledby="prod-fabric">
      <div className="prod-block__head">
        <h2 id="prod-fabric">Fabric from storage</h2>
        {editable && !taking && (
          <button type="button" className="button button--row" onClick={() => setTaking(true)}>
            Take fabric
          </button>
        )}
      </div>
      {error && <Problem>{error}</Problem>}
      {!hbaBuys && <p className="prod-small">The factory buys this order&apos;s fabric, so it takes none from storage.</p>}
      {uses.length === 0 ? (
        hbaBuys && <p className="prod-small">No fabric taken from storage yet.</p>
      ) : (
        <ul className="prod-filelist">
          {uses.map((use) => {
            const words = `${kgWords(use.kg)} of ${use.fabric.name}`;
            return (
              <li key={use.move_id}>
                <Link to={`/production/fabric/${use.fabric.id}`}>{use.fabric.name}</Link>
                {use.fabric.colour && <span className="prod-small"> · {use.fabric.colour}</span>} · <b>{kgWords(use.kg)}</b>
                {powers.canEdit && order.status === "open" &&
                  (confirming === use.move_id ? (
                    <span className="prod-lib-confirm">
                      {" "}Give {kgWords(use.kg)} back to storage?{" "}
                      <button type="button" className="button button--row" disabled={busy} onClick={() => giveBack(use.move_id, words)}>
                        Give back
                      </button>{" "}
                      <button type="button" className="button button--row" onClick={() => setConfirming(null)}>
                        Keep
                      </button>
                    </span>
                  ) : (
                    <>
                      {" "}
                      <button type="button" className="button button--quiet button--row" aria-label={`Give back ${words}`} disabled={busy} onClick={() => setConfirming(use.move_id)}>
                        Give back
                      </button>
                    </>
                  ))}
              </li>
            );
          })}
        </ul>
      )}
      {taking && (
        <form className="prod-form prod-fabric-take" onSubmit={take} noValidate>
          {fabrics === null ? (
            <p className="loading" role="status">Loading fabric storage…</p>
          ) : fabrics.length === 0 ? (
            <p className="prod-small prod-wide">
              No fabric is in storage. <Link to="/production/fabric">Go to Fabric</Link> to add some.
            </p>
          ) : (
            <>
              <label className="field">
                <span className="field__label">Fabric</span>
                <select className="input" value={fabricId} onChange={(event) => setFabricId(event.target.value)}>
                  <option value="">Choose a fabric…</option>
                  {fabrics.map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.name}
                      {row.colour ? ` · ${row.colour}` : ""} · {kgWords(row.in_stock_kg)} in storage
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field__label">Kilos</span>
                <input className="input" inputMode="decimal" value={kg} onChange={(event) => setKg(event.target.value)} />
              </label>
            </>
          )}
          <div className="prod-actions prod-wide">
            {fabrics && fabrics.length > 0 && (
              <button type="submit" className="button button--primary" disabled={busy}>
                {busy ? "Saving…" : "Take from storage"}
              </button>
            )}
            <button type="button" className="button" onClick={() => setTaking(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
