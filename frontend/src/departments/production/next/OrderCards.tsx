/**
 * The cards on one order: stages, pieces by size, delivery date, deliveries,
 * cost and what is owed (owner only), the owner's decisions, photos, history.
 *
 * **Money is drawn only when the keys are there.** `order.cost` and
 * `order.settlement` are absent for anybody without `production.owner`, and a
 * card that needs them is not drawn at all (the server decides, this follows).
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../../../lib/api";
import { formatEgp } from "../../../lib/money";
import { Money } from "../../../components/Money";
import { cairoDay, pieces, plural, shortDay, stamp } from "./format";
import { reopenable, stageStatus } from "./logic";
import type { Panel, Powers } from "./logic";
import type { Delivery, DeliveryKind, HistoryEvent, OrderAnswer, OrderStage, OrderView, ProdFile, ReasonLine, Size } from "./types";
import { DateBox, Problem, useSubmit } from "./ui";
import type { Run } from "./ui";

type CardProps = { order: OrderView; powers: Powers; open: (panel: Panel) => void };

const isOpen = (order: OrderView) => order.status === "open";

function reasonsLine(lines: ReasonLine[]): string {
  return lines.map((line) => `${line.reason.toLowerCase()} ${line.quantity}`).join(", ");
}

// ── Stages ───────────────────────────────────────────────────────────────────

function detail(order: OrderView, stage: OrderStage): string {
  const note = stage.note ? stage.note : null;
  if (stage.status === "skipped") return `Skipped: ${note ?? "not needed on this order"}`;
  if (stage.status === "done") {
    const parts = [stage.done_by, shortDay(stage.done_on)].filter(Boolean) as string[];
    if (stage.key === "cutting" && order.totals.cut !== null) parts.push(`${pieces(order.totals.cut)} cut`);
    if (stage.key === "final_inspection" && order.totals.passed !== null) parts.push(`${pieces(order.totals.passed)} passed`);
    if (stage.key === "warehouse" && order.totals.counted !== null) parts.push(`${pieces(order.totals.counted)} counted`);
    if (note) parts.push(note);
    return parts.join(" · ");
  }
  const parts: string[] = [];
  if (stage.expected_date) parts.push(`Expected ${shortDay(stage.expected_date)}`);
  if (note) parts.push(stage.key === "fabric_check" ? `Last check failed: ${note}` : stage.key === "sample" ? `Changes asked for: ${note}` : note);
  return parts.join(" · ") || "Not started";
}

/** The inline editor for one stage's expected date. */
function DateEditor({ order, stage, run, onDone }: { order: OrderView; stage: OrderStage; run: Run; onDone: () => void }) {
  const [date, setDate] = useState(stage.expected_date ?? "");
  const { error, busy, submit } = useSubmit(run);
  return (
    <form
      className="prod-stage__edit"
      onSubmit={(event) => {
        event.preventDefault();
        submit(
          !date ? "Give a date." : null,
          () => api.patch<OrderAnswer>(`/api/prod/orders/${order.id}/stages/${stage.key}`, { expected_date: date }),
          `${stage.label}'s expected date changed.`,
        ).then((saved) => {
          if (saved) onDone();
        });
      }}
    >
      <DateBox label={`${stage.label}, expected date`} value={date} onChange={setDate} />
      <button type="submit" className="button button--row button--primary" disabled={busy}>
        {busy ? "Saving…" : "Save date"}
      </button>
      <button type="button" className="button button--row" onClick={onDone}>
        Cancel
      </button>
      {error && <Problem>{error}</Problem>}
    </form>
  );
}

export function StagesCard({ order, powers, open, run }: CardProps & { run: Run }) {
  const [editing, setEditing] = useState<string | null>(null);
  const reopen = powers.isOwner && isOpen(order) ? reopenable(order) : null;
  return (
    <section className="prod-block" aria-labelledby="prod-stages">
      <h2 id="prod-stages">Stages</h2>
      {order.stages.map((stage) => {
        const now = order.current_stage === stage.key;
        const editable = powers.canEdit && isOpen(order) && stage.status === "todo";
        return (
          <div key={stage.key} className={`prod-stage prod-stage--${now ? "now" : stage.status}`}>
            <div className="prod-dot" aria-hidden="true">{stage.status === "done" ? "✓" : ""}</div>
            <div>
              <div className="prod-stage__name">
                {stage.position} · {stage.label}
                {now && <span className="prod-sr"> (current stage)</span>}
              </div>
              <div className="prod-small">{detail(order, stage)}</div>
              {(editable || stage.key === reopen) && editing !== stage.key && (
                <div className="prod-stage__edit">
                  {editable && (
                    <button type="button" className="button button--quiet" onClick={() => setEditing(stage.key)}>
                      Change date<span className="prod-sr"> for {stage.label}</span>
                    </button>
                  )}
                  {stage.key === reopen && (
                    <button type="button" className="button button--quiet" onClick={() => open({ kind: "reopen", stage: stage.key })}>
                      Reopen<span className="prod-sr"> {stage.label}</span>
                    </button>
                  )}
                </div>
              )}
              {editing === stage.key && <DateEditor order={order} stage={stage} run={run} onDone={() => setEditing(null)} />}
            </div>
          </div>
        );
      })}
    </section>
  );
}

// ── Pieces by size ───────────────────────────────────────────────────────────

/** Sizes whose Khazenly count differs from what shipped, on a delivery already counted. */
function mismatched(order: OrderView): Set<Size> {
  const found = new Set<Size>();
  for (const delivery of order.deliveries) {
    if (delivery.kind !== "finished" || !delivery.counted_on) continue;
    for (const line of delivery.sizes) if (line.counted !== null && line.counted !== line.shipped) found.add(line.size);
  }
  return found;
}

export function SizesCard({ order, powers, open }: CardProps) {
  const t = order.totals;
  const wrong = mismatched(order);
  const unexplained = order.deliveries.filter((delivery) => delivery.needs_reason);
  const sum = (lines: ReasonLine[]) => lines.reduce((total, line) => total + line.quantity, 0);
  const cutDone = stageStatus(order, "cutting") === "done";
  const edit = powers.canEdit && isOpen(order);
  return (
    <section className="prod-block" aria-labelledby="prod-sizes">
      <div className="prod-block__head">
        <h2 id="prod-sizes">Pieces by size</h2>
        {edit && order.current_stage === "cutting" && (
          <button type="button" className="button button--row" onClick={() => open({ kind: "cut" })}>Record cut quantities</button>
        )}
        {edit && cutDone && stageStatus(order, "final_inspection") === "todo" && (
          <button type="button" className="button button--row" onClick={() => open({ kind: "inspection" })}>Enter inspection counts</button>
        )}
      </div>
      <div className="prod-scroll">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Size</th>
              <th scope="col" className="numeric">Planned</th>
              <th scope="col" className="numeric">Cut</th>
              <th scope="col" className="numeric">Passed</th>
              <th scope="col" className="numeric">To fix</th>
              <th scope="col" className="numeric">Rejected</th>
              <th scope="col" className="numeric">Khazenly counted</th>
            </tr>
          </thead>
          <tbody>
            {order.sizes.map((line) => (
              <tr key={line.size}>
                <td>{line.size}</td>
                <td className="numeric">{pieces(line.planned)}</td>
                <td className="numeric">{pieces(line.cut)}</td>
                <td className="numeric">{pieces(line.passed)}</td>
                <td className="numeric">{pieces(line.to_fix)}</td>
                <td className="numeric">{pieces(line.rejected)}</td>
                <td className={`numeric${wrong.has(line.size) ? " prod-late" : ""}`}>
                  {order.deliveries.some((delivery) => delivery.kind === "finished" && delivery.counted_on) ? pieces(line.counted) : "—"}
                  {wrong.has(line.size) && <span className="prod-sr"> (differs from what shipped)</span>}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td>Total</td>
              <td className="numeric">{pieces(t.planned)}</td>
              <td className="numeric">{pieces(t.cut)}</td>
              <td className="numeric">{pieces(t.passed)}</td>
              <td className="numeric">{pieces(t.to_fix)}</td>
              <td className="numeric">{pieces(t.rejected)}</td>
              <td className="numeric">{pieces(order.received_total)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
      {(order.reasons.cut_short.length > 0 || order.reasons.rejected.length > 0 || order.reasons.to_fix.length > 0) && (
        <ul className="prod-reasonlist">
          {order.reasons.cut_short.length > 0 && (
            <li>
              Planned to cut, {pieces(sum(order.reasons.cut_short))} fewer: {reasonsLine(order.reasons.cut_short)}
            </li>
          )}
          {order.reasons.rejected.length > 0 && (
            <li>
              Rejected {pieces(sum(order.reasons.rejected))}: {reasonsLine(order.reasons.rejected)}
            </li>
          )}
          {order.reasons.to_fix.length > 0 && (
            <li>
              To fix {pieces(sum(order.reasons.to_fix))}: {reasonsLine(order.reasons.to_fix)}
              {(order.fix_not_returned ?? 0) > 0 && `. Due back ${shortDay(order.delivery_date)}`}
            </li>
          )}
        </ul>
      )}
      {unexplained.map((delivery) => (
        <div key={delivery.id} className="prod-flag prod-flag--refused" role="status">
          Delivery {delivery.number}:{" "}
          {delivery.sizes
            .filter((line) => line.counted !== null && line.counted !== line.shipped)
            .map((line) => `size ${line.size}, the factory shipped ${line.shipped}, Khazenly counted ${line.counted}`)
            .join("; ")}
          . A reason is needed before this order can close.
        </div>
      ))}
    </section>
  );
}

// ── Delivery date ────────────────────────────────────────────────────────────

export function DatesCard({ order, powers, open }: CardProps) {
  return (
    <section className="prod-block" aria-labelledby="prod-dates">
      <div className="prod-block__head">
        <h2 id="prod-dates">Delivery date</h2>
        {powers.canEdit && isOpen(order) && (
          <button type="button" className="button button--row" onClick={() => open({ kind: "date" })}>Change date</button>
        )}
      </div>
      <div className="prod-scroll">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Set on</th>
              <th scope="col">Date</th>
              <th scope="col">By</th>
              <th scope="col">Reason</th>
            </tr>
          </thead>
          <tbody>
            {order.date_history.map((change) => (
              <tr key={change.id}>
                <td>{shortDay(cairoDay(change.created_at))}</td>
                <td className={change.new_date > order.target_date ? "prod-late" : undefined}>
                  {shortDay(change.new_date)}
                  {change.new_date > order.target_date && <span className="prod-sr"> (after the target date)</span>}
                </td>
                <td>{change.set_by === "factory" ? "Factory" : "Owner"}</td>
                <td>{change.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ── Deliveries ───────────────────────────────────────────────────────────────

function DeliveryRow({ delivery, canChange, open }: { delivery: Delivery; canChange: boolean; open: (panel: Panel) => void }) {
  const at = (kind: DeliveryKind): Panel => ({ kind: "delivery", id: delivery.id, deliveryKind: kind });
  const pill = delivery.waiting_for_count
    ? ["prod-pill--wait", "Waiting for count"]
    : delivery.needs_reason
      ? ["prod-pill--late", "Counts do not match"]
      : delivery.mismatch
        ? ["prod-pill--wait", "Counts differ, explained"]
        : ["prod-pill--ok", "Counts match"];
  const label = delivery.kind === "fix" ? "fix pieces" : "pieces";
  return (
    <div className="prod-delivery">
      <div className="prod-delivery__top">
        <div>
          <b>Delivery {delivery.number}</b>
          {delivery.kind === "fix" && " · fix pieces"}
          <div className="prod-small">
            {shortDay(delivery.shipped_on)} · factory shipped {pieces(delivery.shipped_total)} {label} ·{" "}
            {delivery.counted_total === null ? "Khazenly's count not entered yet" : `Khazenly counted ${pieces(delivery.counted_total)}`}
          </div>
        </div>
        <div className="prod-actions">
          <span className={`prod-pill ${pill[0]}`}>{pill[1]}</span>
          {canChange && delivery.waiting_for_count && (
            <button type="button" className="button button--row" onClick={() => open(at(delivery.kind))}>Enter Khazenly's count</button>
          )}
          {canChange && delivery.needs_reason && (
            <button type="button" className="button button--row" onClick={() => open(at(delivery.kind))}>Add reason</button>
          )}
          {canChange && !delivery.waiting_for_count && !delivery.needs_reason && (
            <button type="button" className="button button--row" onClick={() => open(at(delivery.kind))}>
              Change<span className="prod-sr"> delivery {delivery.number}</span>
            </button>
          )}
        </div>
      </div>
      <p className="prod-delivery__sizes">
        Shipped: {delivery.sizes.map((line) => `${line.size} ${line.shipped}`).join(" · ")}
        {delivery.counted_on && (
          <>
            <br />
            Counted {shortDay(delivery.counted_on)}: {delivery.sizes.map((line) => `${line.size} ${line.counted ?? 0}`).join(" · ")}
          </>
        )}
      </p>
      {delivery.mismatch_reason && <p className="prod-small">Reason the counts differ: {delivery.mismatch_reason}</p>}
    </div>
  );
}

export function DeliveriesCard({ order, powers, open }: CardProps) {
  const cutDone = stageStatus(order, "cutting") === "done";
  const received = stageStatus(order, "warehouse") === "done";
  const canChange = powers.canEdit && isOpen(order) && !received;
  return (
    <section className="prod-block" aria-labelledby="prod-deliveries">
      <div className="prod-block__head">
        <h2 id="prod-deliveries">Deliveries</h2>
        {canChange && cutDone && (
          <button type="button" className="button button--row" onClick={() => open({ kind: "delivery", id: null, deliveryKind: "finished" })}>
            Record a delivery
          </button>
        )}
      </div>
      {order.deliveries.length === 0 ? (
        <p className="prod-small">{cutDone ? "Nothing has left the factory yet." : "Deliveries can be recorded once cutting is done."}</p>
      ) : (
        order.deliveries.map((delivery) => <DeliveryRow key={delivery.id} delivery={delivery} canChange={canChange} open={open} />)
      )}
      {received && <p className="prod-small">The warehouse receipt is done, so deliveries can no longer be changed.</p>}
    </section>
  );
}

// ── Money (the owner's) ──────────────────────────────────────────────────────

export function CostCard({ order, powers, open }: CardProps) {
  const cost = order.cost;
  if (!cost) return null;
  return (
    <section className="prod-block" aria-labelledby="prod-cost">
      <div className="prod-block__head">
        <h2 id="prod-cost">Cost per piece</h2>
        {powers.isOwner && isOpen(order) && (
          <button type="button" className="button button--row" onClick={() => open({ kind: "actual" })}>Edit actual cost</button>
        )}
      </div>
      <div className="prod-scroll">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Part</th>
              <th scope="col" className="numeric">Target</th>
              <th scope="col" className="numeric">Actual</th>
            </tr>
          </thead>
          <tbody>
            {cost.parts.map((part) => {
              const over = part.actual_piastres !== null && part.actual_piastres > part.target_piastres;
              return (
                <tr key={part.part}>
                  <td>{part.label}</td>
                  <td className="numeric"><Money piastres={part.target_piastres} /></td>
                  <td className={`numeric${over ? " prod-late" : ""}`}>
                    {part.actual_piastres === null ? "—" : <Money piastres={part.actual_piastres} />}
                    {over && <span className="prod-sr"> (over target)</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <td>Total</td>
              <td className="numeric"><Money piastres={cost.target_total_piastres} /></td>
              <td className={`numeric${cost.actual_total_piastres !== null && cost.actual_total_piastres > cost.target_total_piastres ? " prod-late" : ""}`}>
                {cost.actual_total_piastres === null ? "—" : <Money piastres={cost.actual_total_piastres} />}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  );
}

export function OwedCard({ order }: { order: OrderView }) {
  const owed = order.settlement;
  if (owed === undefined) return null;
  return (
    <section className="prod-block" aria-labelledby="prod-owed">
      <h2 id="prod-owed">Owed to the factory for this order</h2>
      {owed === null ? (
        <p className="prod-small">This is worked out once cutting is done.</p>
      ) : (
        <>
          <table className="table">
            <tbody>
              <tr>
                <td>
                  Pieces cut, {pieces(owed.pieces_cut)} × {formatEgp(owed.making_rate_piastres)} ({owed.rate_includes_printing ? "manufacturing and printing" : "manufacturing"})
                </td>
                <td className="numeric"><Money piastres={owed.work_value_piastres} /></td>
              </tr>
              <tr>
                <td>
                  Rejected, {pieces(owed.rejected_pieces)} × {formatEgp(owed.rejected_rate_piastres)}
                  <div className="prod-small">
                    {owed.rejected_basis === "making"
                      ? "HBA bought the fabric, so only the making cost comes off"
                      : "The factory bought the fabric, so the whole piece cost comes off"}
                  </div>
                </td>
                <td className="numeric">− <Money piastres={owed.rejected_deduction_piastres} /></td>
              </tr>
              <tr>
                <td>Held until fixed, {pieces(owed.held_pieces)} × {formatEgp(owed.making_rate_piastres)}</td>
                <td className="numeric">− <Money piastres={owed.held_piastres} /></td>
              </tr>
            </tbody>
            <tfoot>
              <tr>
                <td>{owed.settled ? "Settled with the factory" : "Payable now"}</td>
                <td className="numeric"><Money piastres={owed.payable_piastres} kind={owed.settled ? "agreed" : "provisional"} /></td>
              </tr>
            </tfoot>
          </table>
        </>
      )}
    </section>
  );
}

// ── The owner's decisions ────────────────────────────────────────────────────

export function OwnerCard({ order, powers, open }: CardProps) {
  if (!powers.isOwner || !isOpen(order)) return null;
  const sampleNow = order.current_stage === "sample";
  const settleNow = order.current_stage === "settle";
  const writeOff = stageStatus(order, "final_inspection") === "done" && stageStatus(order, "warehouse") === "todo" && (order.fix_not_returned ?? 0) > 0;
  return (
    <section className="prod-block" aria-labelledby="prod-owner">
      <h2 id="prod-owner">Owner's decisions</h2>
      <div className="prod-owner">
        <div className="prod-owner__row">
          <button type="button" className="button" onClick={() => open({ kind: "edit" })}>Edit the order</button>
          {sampleNow && <button type="button" className="button button--primary" onClick={() => open({ kind: "sample" })}>Review the sample</button>}
          {settleNow && <button type="button" className="button button--primary" onClick={() => open({ kind: "settle" })}>Settle with the factory</button>}
          {writeOff && <button type="button" className="button" onClick={() => open({ kind: "writeoff" })}>Write off fix pieces</button>}
          <button type="button" className="button button--danger" onClick={() => open({ kind: "cancel" })}>Cancel this order</button>
        </div>
        {writeOff && (
          <p className="prod-small">{plural(order.fix_not_returned ?? 0, "fix piece")} still at the factory. Write them off if they will not come back.</p>
        )}
      </div>
    </section>
  );
}

// ── Photos ───────────────────────────────────────────────────────────────────

const PHOTO_TYPES = "image/jpeg,image/png,image/webp,image/gif,application/pdf";

type FilesAnswer = { files: ProdFile[] };

export function FilesCard({ order, powers, version }: { order: OrderView; powers: Powers; version: number }) {
  const [files, setFiles] = useState<ProdFile[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const picker = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    api.get<FilesAnswer>(`/api/prod/orders/${order.id}/files`)
      .then((answer) => setFiles(answer.files))
      .catch((caught) => setError(caught instanceof Error ? caught.message : "The photos could not be loaded."));
  }, [order.id]);
  useEffect(load, [load, version]);

  async function add(file: File) {
    setBusy(true);
    setError(null);
    try {
      await api.upload(`/api/prod/orders/${order.id}/files`, file);
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The file could not be added.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(file: ProdFile) {
    if (!window.confirm(`Remove ${file.name} from this order?`)) return;
    setBusy(true);
    setError(null);
    try {
      await api.del(`/api/prod/files/${file.id}`);
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The file could not be removed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="prod-block" aria-labelledby="prod-photos">
      <div className="prod-block__head">
        <h2 id="prod-photos">Photos and files</h2>
        {powers.canEdit && (
          <>
            <input
              ref={picker}
              type="file"
              accept={PHOTO_TYPES}
              hidden
              aria-label="Add a photo or PDF"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) add(file);
              }}
            />
            <button type="button" className="button button--row" disabled={busy} onClick={() => picker.current?.click()}>
              {busy ? "Saving…" : "Add a photo"}
            </button>
          </>
        )}
      </div>
      {error && <Problem>{error}</Problem>}
      {files === null && !error && <p className="loading" role="status">Loading…</p>}
      {files !== null && files.length === 0 && <p className="prod-small">No photos yet. JPG, PNG, WebP, GIF or PDF, up to 20 MB.</p>}
      {files !== null && files.length > 0 && (
        <ul className="prod-photos">
          {files.map((file) => (
            <li key={file.id} className="prod-photo">
              {file.mime_type.startsWith("image/") ? (
                <a href={`/api/prod/files/${file.id}`} target="_blank" rel="noopener noreferrer">
                  <img src={`/api/prod/files/${file.id}`} alt={file.name} loading="lazy" />
                </a>
              ) : (
                <a className="prod-photo__file" href={`/api/prod/files/${file.id}`} target="_blank" rel="noopener noreferrer">
                  PDF
                </a>
              )}
              <span className="prod-small">
                {file.name}
                {file.stage && ` · ${file.stage.replace(/_/g, " ")}`}
              </span>
              {powers.canEdit && (
                <button type="button" className="button button--row" disabled={busy} onClick={() => remove(file)}>
                  Remove<span className="prod-sr"> {file.name}</span>
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ── History ──────────────────────────────────────────────────────────────────

type HistoryAnswer = { events: HistoryEvent[] };
const HISTORY_SHOWN = 8;

export function HistoryCard({ order, version }: { order: OrderView; version: number }) {
  const [events, setEvents] = useState<HistoryEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [all, setAll] = useState(false);

  useEffect(() => {
    api.get<HistoryAnswer>(`/api/prod/orders/${order.id}/history`)
      .then((answer) => setEvents(answer.events))
      .catch((caught) => setError(caught instanceof Error ? caught.message : "The history could not be loaded."));
  }, [order.id, version]);

  const shown = events ? (all ? events : events.slice(0, HISTORY_SHOWN)) : [];
  return (
    <section className="prod-block" aria-labelledby="prod-history">
      <h2 id="prod-history">History</h2>
      {error && <Problem>{error}</Problem>}
      {events === null && !error && <p className="loading" role="status">Loading…</p>}
      {events !== null && events.length === 0 && <p className="prod-small">Nothing recorded yet.</p>}
      {shown.length > 0 && (
        <ol className="prod-history">
          {shown.map((event) => (
            <li key={event.id}>
              {event.summary ?? event.action}
              <time dateTime={event.at ?? undefined}>
                {event.who ? `${event.who} · ` : ""}
                {stamp(event.at)}
              </time>
            </li>
          ))}
        </ol>
      )}
      {events !== null && events.length > HISTORY_SHOWN && (
        <button type="button" className="button button--row" onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `Show all ${events.length}`}
        </button>
      )}
    </section>
  );
}
