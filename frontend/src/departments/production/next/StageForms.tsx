/**
 * The QC manager's stage forms: complete a simple stage, the fabric check,
 * the cut quantities and the final inspection. Each checks, before sending,
 * what the server will check (`logic.ts`), shows the running totals as the
 * person types, and shows the server's own `detail` if it still refuses.
 */
import { useMemo, useState } from "react";

import { api } from "../../../lib/api";
import { cairoToday, plural } from "./format";
import {
  blankReason,
  countsFrom,
  cutProblem,
  cutShortfall,
  inspectionProblem,
  inspectionTotals,
  lineTotal,
  reasonBody,
  reasonTotal,
  reasonsFrom,
  sizesBody,
  totalOf,
  whole,
} from "./logic";
import type { Counts, InspectionLine, ReasonRow } from "./logic";
import type { OrderAnswer, OrderView, Size } from "./types";
import { Actions, DateBox, PanelShell, ReasonRows, SizeInputs, TextBox, useSubmit } from "./ui";
import type { Run } from "./ui";

type FormProps = { order: OrderView; run: Run; onClose: () => void };

const TITLES = {
  materials: ["Mark materials arrived", "Record the day the materials reached the factory.", "Materials marked as arrived."],
  pattern_check: ["Confirm the pattern check", "Record the day the pattern and sizes were confirmed.", "Pattern check confirmed."],
  making: ["Mark making finished", "Record the day the factory finished making the pieces, printing included.", "Making marked as finished."],
} as const;

/** Materials, pattern check and making: a date and an optional note. */
export function CompleteForm({ order, run, onClose, stage }: FormProps & { stage: keyof typeof TITLES }) {
  const today = useMemo(cairoToday, []);
  const [day, setDay] = useState(today);
  const [note, setNote] = useState("");
  const { error, busy, submit } = useSubmit(run);
  const [title, intro, done] = TITLES[stage];
  return (
    <PanelShell title={title} intro={intro} onClose={onClose}>
      <form
        className="prod-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit(
            !day ? "Give the date." : day > today ? "The date can't be in the future." : null,
            () => api.post<OrderAnswer>(`/api/prod/orders/${order.id}/stages/${stage}/complete`, { done_on: day, note: note.trim() || null }),
            done,
          );
        }}
      >
        <DateBox label="Date" value={day} onChange={setDay} max={today} />
        <TextBox label="Note, optional" value={note} onChange={setNote} area wide max={2000} />
        <Actions error={error} busy={busy} label="Save" working="Saving…" />
      </form>
    </PanelShell>
  );
}

const FABRIC_CHECK = "fabric_check";

/** The fabric check: passed or failed, with a note. Only a pass completes the stage. */
export function FabricForm({ order, run, onClose }: FormProps) {
  const today = useMemo(cairoToday, []);
  const [result, setResult] = useState<"passed" | "failed">("passed");
  const [day, setDay] = useState(today);
  const [note, setNote] = useState("");
  const { error, busy, submit } = useSubmit(run);
  return (
    <PanelShell
      title="Record the fabric check"
      intro="The QC manager checks the fabric whoever bought it. A failed check keeps this stage open until the fabric passes."
      onClose={onClose}
    >
      <form
        className="prod-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit(
            result === "failed" && !note.trim()
              ? "Say what was wrong with the fabric."
              : !day
                ? "Give the date."
                : day > today
                  ? "The date can't be in the future."
                  : null,
            () => api.post<OrderAnswer>(`/api/prod/orders/${order.id}/stages/${FABRIC_CHECK}/complete`, { done_on: day, note: note.trim() || null, result }),
            result === "passed" ? "Fabric check passed." : "Fabric check recorded as failed. The stage stays open until it passes.",
          );
        }}
      >
        <fieldset className="prod-fieldset prod-wide">
          <legend className="field__label">Result</legend>
          <label className="prod-check">
            <input type="radio" name="fabric-result" checked={result === "passed"} onChange={() => setResult("passed")} />
            Passed
          </label>
          <label className="prod-check">
            <input type="radio" name="fabric-result" checked={result === "failed"} onChange={() => setResult("failed")} />
            Failed
          </label>
        </fieldset>
        <DateBox label="Date" value={day} onChange={setDay} max={today} />
        <TextBox
          label={result === "failed" ? "What was wrong" : "Note, optional"}
          value={note}
          onChange={setNote}
          area
          wide
          max={2000}
        />
        <Actions error={error} busy={busy} label="Save" working="Saving…" />
      </form>
    </PanelShell>
  );
}

/** Cutting: pieces cut per size, why any are fewer than planned, and the date the factory now promises. */
export function CutForm({ order, run, onClose }: FormProps) {
  const today = useMemo(cairoToday, []);
  const planned = order.totals.planned ?? 0;
  const [cut, setCut] = useState<Counts>(() => countsFrom(Object.fromEntries(order.sizes.map((line) => [line.size, line.planned]))));
  const [reasons, setReasons] = useState<ReasonRow[]>([blankReason()]);
  const [promised, setPromised] = useState(order.delivery_date);
  const [day, setDay] = useState(today);
  const { error, busy, submit } = useSubmit(run);

  const draft = { cut, planned, reasons, promised, today };
  const shortfall = cutShortfall(draft);
  const given = reasonTotal(reasons);
  const hints = Object.fromEntries(order.sizes.map((line) => [line.size, `planned ${line.planned}`])) as Partial<Record<Size, string>>;
  const has = (size: Size) => order.sizes.some((line) => line.size === size);

  return (
    <PanelShell
      title="Record cut quantities"
      intro="How many pieces were cut in each size, and the date the factory now promises to finish. Recording this completes cutting."
      onClose={onClose}
    >
      <form
        className="prod-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit(
            cutProblem(draft) ?? (!day ? "Give the date." : day > today ? "The date can't be in the future." : null),
            () =>
              api.put<OrderAnswer>(`/api/prod/orders/${order.id}/cut`, {
                sizes: sizesBody(cut, has),
                reasons: shortfall > 0 ? reasonBody(reasons) : [],
                promised_date: promised,
                done_on: day,
              }),
            "Cut quantities recorded.",
          );
        }}
      >
        <SizeInputs
          legend="Pieces cut"
          counts={cut}
          onChange={(size, value) => setCut({ ...cut, [size]: value })}
          hints={hints}
          total={`Cut ${totalOf(cut).toLocaleString("en-GB")} of ${planned.toLocaleString("en-GB")} planned${
            shortfall > 0 ? `: ${plural(shortfall, "piece")} fewer` : shortfall < 0 ? `: ${plural(-shortfall, "piece")} more` : ""
          }`}
        />
        {shortfall > 0 && (
          <ReasonRows
            legend={`Why ${plural(shortfall, "piece")} fewer were cut`}
            rows={reasons}
            onChange={setReasons}
            summary={`Reasons add up to ${given.toLocaleString("en-GB")} of ${shortfall.toLocaleString("en-GB")}`}
            tone={given === shortfall ? "ok" : "late"}
          />
        )}
        <DateBox label="Date the factory now promises" value={promised} onChange={setPromised} hint="If it differs from the delivery date, the change is kept in the date history." />
        <DateBox label="Cut on" value={day} onChange={setDay} max={today} />
        <Actions error={error} busy={busy} label="Save cut quantities" working="Saving…" />
      </form>
    </PanelShell>
  );
}

/** Final inspection: passed, to fix and rejected per size. Saved in batches; completed when every size adds up. */
export function InspectionForm({ order, run, onClose }: FormProps) {
  const today = useMemo(cairoToday, []);
  const [lines, setLines] = useState<InspectionLine[]>(() =>
    order.sizes
      .filter((line) => (line.cut ?? 0) > 0)
      .map((line) => ({
        size: line.size,
        cut: line.cut ?? 0,
        passed: line.passed === null ? "" : String(line.passed),
        to_fix: line.to_fix === null ? "" : String(line.to_fix),
        rejected: line.rejected === null ? "" : String(line.rejected),
      })),
  );
  const [rejectedReasons, setRejectedReasons] = useState<ReasonRow[]>(() =>
    order.reasons.rejected.length ? reasonsFrom(order.reasons.rejected) : [blankReason()],
  );
  const [toFixReasons, setToFixReasons] = useState<ReasonRow[]>(() =>
    order.reasons.to_fix.length ? reasonsFrom(order.reasons.to_fix) : [blankReason()],
  );
  const [day, setDay] = useState(today);
  const { error, busy, submit } = useSubmit(run);

  const draft = { lines, rejectedReasons, toFixReasons };
  const totals = inspectionTotals(draft);
  const set = (size: Size, column: "passed" | "to_fix" | "rejected", value: string) =>
    setLines(lines.map((line) => (line.size === size ? { ...line, [column]: value } : line)));

  function send(complete: boolean) {
    submit(
      inspectionProblem(draft, complete) ?? (complete && (!day || day > today) ? "Give a date that is not in the future." : null),
      () =>
        api.put<OrderAnswer>(`/api/prod/orders/${order.id}/inspection`, {
          sizes: Object.fromEntries(
            lines.map((line) => [line.size, { passed: whole(line.passed), to_fix: whole(line.to_fix), rejected: whole(line.rejected) }]),
          ),
          reasons: [
            ...reasonBody(rejectedReasons).map((reason) => ({ ...reason, kind: "rejected" as const })),
            ...reasonBody(toFixReasons).map((reason) => ({ ...reason, kind: "to_fix" as const })),
          ],
          complete,
          ...(complete ? { done_on: day } : {}),
        }),
      complete ? "Final inspection completed." : "Inspection counts saved.",
    );
  }

  const sum = (given: number, wanted: number) => `Reasons add up to ${given.toLocaleString("en-GB")} of ${wanted.toLocaleString("en-GB")}`;

  return (
    <PanelShell
      title="Record the inspection"
      intro="Pieces finish in batches, so counts can be saved as you go. To complete the inspection, passed, to fix and rejected must add up to the number cut, in every size."
      onClose={onClose}
    >
      <form
        className="prod-form prod-form--wide"
        onSubmit={(event) => {
          // Enter in a count box submits the form: that only saves. Completing the inspection is
          // its own button, so a keystroke cannot finish a stage whose numbers happen to add up.
          event.preventDefault();
          send(false);
        }}
      >
        <div className="prod-inspect prod-wide" role="group" aria-label="Counts by size">
          {lines.map((line) => {
            const left = line.cut - lineTotal(line);
            return (
              <div key={line.size} className="prod-inspect__row">
                <span className="prod-inspect__size">
                  {line.size}
                  <span className="prod-inspect__cut">{line.cut.toLocaleString("en-GB")} cut</span>
                </span>
                {(["passed", "to_fix", "rejected"] as const).map((column) => (
                  <label key={column}>
                    <span aria-hidden="true">{column === "passed" ? "Passed" : column === "to_fix" ? "To fix" : "Rejected"}</span>
                    <input
                      className="input"
                      inputMode="numeric"
                      autoComplete="off"
                      aria-label={`${line.size} ${column === "to_fix" ? "to fix" : column}`}
                      value={line[column]}
                      onChange={(event) => set(line.size, column, event.target.value)}
                    />
                  </label>
                ))}
                <span className={`prod-inspect__left${left < 0 ? " prod-late" : ""}`} aria-live="polite">
                  {left === 0 ? "All counted" : left > 0 ? `${left.toLocaleString("en-GB")} left` : `${(-left).toLocaleString("en-GB")} too many`}
                </span>
              </div>
            );
          })}
          <p className="prod-total" aria-live="polite">
            Total: {totals.passed.toLocaleString("en-GB")} passed, {totals.to_fix.toLocaleString("en-GB")} to fix,{" "}
            {totals.rejected.toLocaleString("en-GB")} rejected, of {totals.cut.toLocaleString("en-GB")} cut
          </p>
        </div>
        <ReasonRows
          legend={`Why pieces were rejected (${totals.rejected.toLocaleString("en-GB")})`}
          noun="Rejected reason"
          rows={rejectedReasons}
          onChange={setRejectedReasons}
          summary={sum(reasonTotal(rejectedReasons), totals.rejected)}
          tone={reasonTotal(rejectedReasons) === totals.rejected ? "ok" : "late"}
        />
        <ReasonRows
          legend={`Why pieces need fixing (${totals.to_fix.toLocaleString("en-GB")})`}
          noun="Fix reason"
          rows={toFixReasons}
          onChange={setToFixReasons}
          summary={sum(reasonTotal(toFixReasons), totals.to_fix)}
          tone={reasonTotal(toFixReasons) === totals.to_fix ? "ok" : "late"}
        />
        <DateBox label="Inspection completed on" value={day} onChange={setDay} max={today} hint="Used only when you complete the inspection." />
        <Actions
          error={error}
          busy={busy}
          label="Save counts for now"
          working="Saving…"
          extra={
            <button type="button" className="button" disabled={busy} onClick={() => send(true)}>
              Complete the inspection
            </button>
          }
        />
      </form>
    </PanelShell>
  );
}
