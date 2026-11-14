/**
 * The remaining panels on the order page: the delivery date, and the owner's
 * decisions (the sample, writing pieces off, settling, reopening, cancelling,
 * the actual cost and editing the order).
 */
import { useEffect, useState } from "react";

import { api } from "../../../lib/api";
import { egpPlain, formatEgp, parseEgp } from "../../../lib/money";
import { shortDay } from "./format";
import { COST_LABELS, COST_PARTS, blankCounts, blankCost, isBlank, totalOf, unreadable, whole, NOT_WHOLE } from "./logic";
import type { Counts, CostText } from "./logic";
import { OrderFields, draftBody, draftFromOrder, draftProblem } from "./OrderFields";
import type { Choices, OrderAnswer, OrderView, Size, StageKey } from "./types";
import { Actions, PanelShell, Problem, SizeInputs, TextBox, DateBox, useSubmit } from "./ui";
import type { Run } from "./ui";

type FormProps = { order: OrderView; run: Run; onClose: () => void };

/** Change the delivery date: who moved it and why are kept, with the old date. */
export function DateChangeForm({ order, run, onClose, isOwner }: FormProps & { isOwner: boolean }) {
  const [date, setDate] = useState("");
  const [by, setBy] = useState<"owner" | "factory">(isOwner ? "owner" : "factory");
  const [reason, setReason] = useState("");
  const { error, busy, submit } = useSubmit(run);
  return (
    <PanelShell
      title="Change the delivery date"
      intro={`It is ${shortDay(order.delivery_date)} now. The old date, who moved it and why are kept in the history.`}
      onClose={onClose}
    >
      <form
        className="prod-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit(
            !date
              ? "Give the new date."
              : date === order.delivery_date
                ? `The delivery date is already ${order.delivery_date}.`
                : isBlank(reason)
                  ? "Say why the date is moving."
                  : null,
            () => api.post<OrderAnswer>(`/api/prod/orders/${order.id}/delivery-date`, { new_date: date, set_by: by, reason: reason.trim() }),
            "Delivery date changed.",
          );
        }}
      >
        <DateBox label="New delivery date" value={date} onChange={setDate} />
        <div className="prod-field">
          <label className="field__label" htmlFor="date-by">Who moved it</label>
          <select id="date-by" className="input" value={by} onChange={(event) => setBy(event.target.value as "owner" | "factory")}>
            <option value="factory">The factory</option>
            <option value="owner">The owner</option>
          </select>
        </div>
        <TextBox label="Why" value={reason} onChange={setReason} wide max={200} hint="For example: waiting in the print queue." />
        <Actions error={error} busy={busy} label="Save the new date" working="Saving…" />
      </form>
    </PanelShell>
  );
}

/** The owner's decision on the sample. */
export function SampleForm({ order, run, onClose }: FormProps) {
  const [note, setNote] = useState("");
  const { error, busy, submit } = useSubmit(run);
  const send = (decision: "approved" | "changes") =>
    submit(
      decision === "changes" && isBlank(note) ? "Say what the factory should change." : null,
      () => api.post<OrderAnswer>(`/api/prod/orders/${order.id}/sample`, { decision, note: note.trim() || null }),
      decision === "approved" ? "Sample approved." : "Asked the factory for changes.",
    );
  return (
    <PanelShell
      title="Review the sample"
      intro={order.sample.status === "changes" ? "You asked for changes. Decide again when the changed sample is in." : "Approving the sample lets the order move on to materials."}
      onClose={onClose}
    >
      <form
        className="prod-form"
        onSubmit={(event) => {
          event.preventDefault();
          send("approved");
        }}
      >
        <TextBox label="Note, required if you ask for changes" value={note} onChange={setNote} area wide max={2000} />
        <Actions
          error={error}
          busy={busy}
          label="Approve the sample"
          working="Saving…"
          extra={
            <button type="button" className="button" disabled={busy} onClick={() => send("changes")}>
              Ask for changes
            </button>
          }
        />
      </form>
    </PanelShell>
  );
}

/** Fix pieces that will not come back move from "to fix" to "rejected". */
export function WriteOffForm({ order, run, onClose }: FormProps) {
  const outstanding = Object.fromEntries(order.sizes.map((line) => [line.size, Math.max(0, (line.to_fix ?? 0) - line.fix_shipped)])) as Record<Size, number>;
  const sizes = order.sizes.filter((line) => outstanding[line.size] > 0).map((line) => line.size);
  const [counts, setCounts] = useState<Counts>(blankCounts);
  const [reason, setReason] = useState("");
  const { error, busy, submit } = useSubmit(run);
  const hints = Object.fromEntries(sizes.map((size) => [size, `${outstanding[size]} at the factory`])) as Partial<Record<Size, string>>;

  function problem(): string | null {
    if (unreadable(counts).length) return NOT_WHOLE;
    if (totalOf(counts) <= 0) return "Give the number of pieces to write off.";
    for (const size of sizes) {
      if (whole(counts[size]) > outstanding[size]) return `Size ${size}: only ${outstanding[size]} fix pieces are still at the factory.`;
    }
    return isBlank(reason) ? "Say why they will not come back." : null;
  }

  return (
    <PanelShell
      title="Write off fix pieces"
      intro="Pieces sent back to be fixed that will not come back. They move from to fix to rejected, which changes what the factory is owed."
      onClose={onClose}
    >
      <form
        className="prod-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit(
            problem(),
            () =>
              api.post<OrderAnswer>(`/api/prod/orders/${order.id}/write-off`, {
                sizes: Object.fromEntries(sizes.filter((size) => whole(counts[size]) > 0).map((size) => [size, whole(counts[size])])),
                reason: reason.trim(),
              }),
            "Fix pieces written off.",
          );
        }}
      >
        <SizeInputs legend="Pieces to write off" counts={counts} sizes={sizes} hints={hints} onChange={(size, value) => setCounts({ ...counts, [size]: value })} />
        <TextBox label="Why they will not come back" value={reason} onChange={setReason} wide max={200} />
        <Actions error={error} busy={busy} label="Write them off" working="Saving…" />
      </form>
    </PanelShell>
  );
}

/** Settle with the factory: the figure is frozen and the order closes. */
export function SettleForm({ order, run, onClose }: FormProps) {
  const { error, busy, submit } = useSubmit(run);
  const unexplained = order.deliveries.some((delivery) => delivery.needs_reason);
  return (
    <PanelShell
      title="Settle with the factory"
      intro={
        order.settlement
          ? `The factory is owed ${formatEgp(order.settlement.payable_piastres)} for this order. Settling freezes that figure and closes the order. Nothing on it can change afterwards.`
          : "Settling freezes what the factory is owed and closes the order. Nothing on it can change afterwards."
      }
      onClose={onClose}
    >
      <form
        className="prod-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit(
            unexplained ? "A delivery's counts do not match and have no reason yet. Add the reason first." : null,
            () => api.post<OrderAnswer>(`/api/prod/orders/${order.id}/settle`),
            "Settled and closed.",
          );
        }}
      >
        <Actions error={error} busy={busy} label="Settle and close this order" working="Settling…" />
      </form>
    </PanelShell>
  );
}

/** Reopen the latest finished stage, with a reason. */
export function ReopenForm({ order, run, onClose, stage }: FormProps & { stage: StageKey }) {
  const [reason, setReason] = useState("");
  const { error, busy, submit } = useSubmit(run);
  const label = order.stages.find((candidate) => candidate.key === stage)?.label ?? "the stage";
  return (
    <PanelShell title={`Reopen ${label}`} intro="Only the latest finished stage can be reopened, and the reason is kept in the history." onClose={onClose}>
      <form
        className="prod-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit(
            isBlank(reason) ? "Say why you are reopening it." : null,
            () => api.post<OrderAnswer>(`/api/prod/orders/${order.id}/stages/${stage}/reopen`, { reason: reason.trim() }),
            `${label} reopened.`,
          );
        }}
      >
        <TextBox label="Why" value={reason} onChange={setReason} wide max={500} />
        <Actions error={error} busy={busy} label={`Reopen ${label}`} working="Saving…" />
      </form>
    </PanelShell>
  );
}

/** Cancel the order: it is closed without being settled. */
export function CancelForm({ order, run, onClose }: FormProps) {
  const [reason, setReason] = useState("");
  const { error, busy, submit } = useSubmit(run);
  return (
    <PanelShell title="Cancel this order" intro="A cancelled order cannot be changed afterwards. The reason is kept." onClose={onClose}>
      <form
        className="prod-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit(
            isBlank(reason) ? "Say why it is being cancelled." : null,
            () => api.post<OrderAnswer>(`/api/prod/orders/${order.id}/cancel`, { reason: reason.trim() }),
            `${order.code} cancelled.`,
          );
        }}
      >
        <TextBox label="Why" value={reason} onChange={setReason} wide max={500} />
        <Actions
          error={error}
          busy={busy}
          label="Cancel the order"
          working="Cancelling…"
          extra={
            <button type="button" className="button" onClick={onClose}>
              Keep the order
            </button>
          }
        />
      </form>
    </PanelShell>
  );
}

/** What each part of a piece really cost, typed by the owner. */
export function ActualCostForm({ order, run, onClose }: FormProps) {
  const [typed, setTyped] = useState<CostText>(() => {
    const start = blankCost();
    for (const part of order.cost?.parts ?? []) start[part.part] = part.actual_piastres === null ? "" : egpPlain(part.actual_piastres).replace(/\.00$/, "");
    return start;
  });
  const { error, busy, submit } = useSubmit(run);
  function problem(): string | null {
    for (const part of COST_PARTS) {
      if (isBlank(typed[part])) continue;
      const found = parseEgp(typed[part]);
      if (found === null || found < 0) return "Check the amounts: use figures like 165 or 165.50.";
    }
    return null;
  }
  return (
    <PanelShell
      title="Actual cost per piece"
      intro="Type what each part really cost. A part left empty uses its target."
      onClose={onClose}
    >
      <form
        className="prod-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit(
            problem(),
            () =>
              api.patch<OrderAnswer>(
                `/api/prod/orders/${order.id}`,
                Object.fromEntries(COST_PARTS.map((part) => [`actual_${part}_piastres`, isBlank(typed[part]) ? null : parseEgp(typed[part])])),
              ),
            "Actual cost saved.",
          );
        }}
      >
        <fieldset className="prod-fieldset prod-wide">
          <legend className="field__label">Actual cost per piece, EGP</legend>
          <div className="prod-sizes prod-sizes--five">
            {COST_PARTS.map((part) => {
              const target = order.cost?.parts.find((candidate) => candidate.part === part)?.target_piastres ?? 0;
              return (
                <div key={part} className="prod-size">
                  <label htmlFor={`actual-${part}`}>{COST_LABELS[part]}</label>
                  <input
                    id={`actual-${part}`}
                    className="input"
                    inputMode="decimal"
                    autoComplete="off"
                    value={typed[part]}
                    aria-describedby={`actual-${part}-target`}
                    onChange={(event) => setTyped({ ...typed, [part]: event.target.value })}
                  />
                  <span id={`actual-${part}-target`} className="prod-size__hint">target {formatEgp(target)}</span>
                </div>
              );
            })}
          </div>
        </fieldset>
        <Actions error={error} busy={busy} label="Save the actual cost" working="Saving…" />
      </form>
    </PanelShell>
  );
}

/** Edit the order's basics, plan and target cost. The owner's. */
export function EditForm({ order, run, onClose }: FormProps) {
  const [choices, setChoices] = useState<Choices | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [draft, setDraft] = useState(() => draftFromOrder(order));
  const { error, busy, submit } = useSubmit(run);
  const locked = order.stages.find((stage) => stage.key === "cutting")?.status === "done";

  useEffect(() => {
    api.get<Choices>("/api/prod/choices")
      .then(setChoices)
      .catch((caught) => setLoadError(caught instanceof Error ? caught.message : "The form could not be loaded."));
  }, []);

  return (
    <PanelShell
      title="Edit the order"
      intro="Changing the target date does not move the stages' expected dates; change those on each stage."
      onClose={onClose}
    >
      {loadError && <Problem>{loadError}</Problem>}
      {!choices && !loadError && <p className="loading" role="status">Loading…</p>}
      {choices && (
        <form
          className="prod-form"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            submit(
              draftProblem(draft, false, locked),
              () => api.patch<OrderAnswer>(`/api/prod/orders/${order.id}`, draftBody(draft, locked)),
              "Order changed.",
            );
          }}
        >
          <OrderFields
            draft={draft}
            onChange={setDraft}
            choices={choices}
            lockPlanned={locked}
            lockBuyerAndPrinting={locked}
            held={{ factory: order.factory, printSupplier: order.print_supplier }}
          />
          <Actions error={error} busy={busy} label="Save changes" working="Saving…" />
        </form>
      )}
    </PanelShell>
  );
}

