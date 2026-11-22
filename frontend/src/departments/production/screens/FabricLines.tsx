import "./fabric.css";
import { KG_PROBLEM, kgOf, kgWords } from "./fabricLogic";
import type { ChoiceFabric } from "./types";

/** One fabric an order is being made with: which, and how many kilos. Both as typed. */
export type FabricLine = { fabricId: string; kg: string };

/** The first thing wrong with the lines, or `null`: each needs a fabric and kilos, no fabric twice, no more than storage holds. */
export function fabricLinesProblem(lines: readonly FabricLine[], fabrics: readonly ChoiceFabric[]): string | null {
  const seen = new Set<string>();
  for (const line of lines) {
    const fabric = fabrics.find((candidate) => String(candidate.id) === line.fabricId);
    if (!fabric) return "Choose a fabric for each line of fabric from storage, or remove the line.";
    if (seen.has(line.fabricId)) return `${fabric.name} is on two lines. Put its kilos on one.`;
    seen.add(line.fabricId);
    const kilos = kgOf(line.kg);
    if (kilos === null) return KG_PROBLEM;
    if (kilos > Number(fabric.in_stock_kg)) return `Only ${kgWords(fabric.in_stock_kg)} of ${fabric.name} is in storage.`;
  }
  return null;
}

/**
 * The New order form's "Fabric from storage" (ADR 0089): the fabrics this order is made with and the
 * kilos of each, taken from storage when the order is created. Shown only when HBA buys the fabric.
 */
export function FabricLines({ lines, fabrics, onChange }: { lines: FabricLine[]; fabrics: ChoiceFabric[]; onChange: (lines: FabricLine[]) => void }) {
  const set = (index: number, change: Partial<FabricLine>) => onChange(lines.map((line, at) => (at === index ? { ...line, ...change } : line)));
  return (
    <fieldset className="prod-fieldset prod-wide">
      <legend className="field__label">Fabric from storage, optional</legend>
      {fabrics.length === 0 ? (
        <p className="prod-small">No fabric is in storage yet. You can take it later from the order&apos;s page.</p>
      ) : (
        <>
          {lines.map((line, index) => (
            <div key={index} className="prod-fabric-line">
              <label className="field">
                <span className="field__label">Fabric</span>
                <select className="input" value={line.fabricId} aria-label={`Fabric, line ${index + 1}`} onChange={(event) => set(index, { fabricId: event.target.value })}>
                  <option value="">Choose a fabric…</option>
                  {fabrics.map((fabric) => (
                    <option key={fabric.id} value={fabric.id}>
                      {fabric.name}
                      {fabric.colour ? ` · ${fabric.colour}` : ""} · {kgWords(fabric.in_stock_kg)} in storage
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field__label">Kilos</span>
                <input className="input" inputMode="decimal" aria-label={`Kilos, line ${index + 1}`} value={line.kg} onChange={(event) => set(index, { kg: event.target.value })} />
              </label>
              <button type="button" className="button button--quiet button--row" onClick={() => onChange(lines.filter((_, at) => at !== index))}>
                Remove<span className="prod-sr"> line {index + 1}</span>
              </button>
            </div>
          ))}
          <button type="button" className="button button--row" onClick={() => onChange([...lines, { fabricId: "", kg: "" }])}>
            {lines.length === 0 ? "Take fabric from storage" : "Add another fabric"}
          </button>
          <p className="prod-small">The kilos come off storage when the order is created. Cancelling the order gives them back.</p>
        </>
      )}
    </fieldset>
  );
}
