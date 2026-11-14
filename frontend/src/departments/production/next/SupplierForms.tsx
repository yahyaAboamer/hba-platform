/**
 * The panels on a supplier's page: a payment, the balance brought forward, a correction, a reversal, a
 * void, the dates of a purchase, and the supplier's own details (also the "Add supplier" panel of the
 * list). Each is a form with the checks the server makes, said before anything is sent.
 */
import { useEffect, useMemo, useState } from "react";

import { api } from "../../../lib/api";
import { formatEgp } from "../../../lib/money";
import { cairoToday, shortDay } from "./format";
import { isBlank } from "./logic";
import {
  METHODS,
  PAY_KINDS,
  afterLineSentence,
  afterPaymentSentence,
  lineProblem,
  paymentProblem,
  poundsToPiastres,
  signedPiastres,
} from "./supplierLogic";
import type { Direction, LineDraft, PaymentDraft } from "./supplierLogic";
import type { AccountLine, PayKind, PayMethod, PurchaseView, Section, SupplierList, SupplierView, SupplierAnswer } from "./types";
import { Actions, DateBox, PanelShell, Problem, SelectBox, TextBox, useSubmit } from "./ui";
import type { Run } from "./ui";

type FormProps = { supplier: SupplierView; run: Run<SupplierAnswer>; onClose: () => void };

const MAX_RECEIPT_BYTES = 20 * 1024 * 1024;
export const RECEIPT_TYPES = "image/jpeg,image/png,image/webp,image/gif,application/pdf";

// ── Record a payment ─────────────────────────────────────────────────────────

/** A lump sum paid to the supplier (not to an order); a receipt photo is added right after it is saved. */
export function PaymentForm({ supplier, run, onClose }: FormProps) {
  const today = useMemo(cairoToday, []);
  const owed = supplier.owed_piastres ?? 0;
  const [draft, setDraft] = useState<PaymentDraft>({ amount: "", date: today, method: "bank_transfer", kind: "weekly", note: "" });
  const [receipt, setReceipt] = useState<File | null>(null);
  const [pickerKey, setPickerKey] = useState(0);
  const { error, busy, submit } = useSubmit(run);
  const set = (patch: Partial<PaymentDraft>) => setDraft((before) => ({ ...before, ...patch }));
  const amount = poundsToPiastres(draft.amount);
  const sentence = afterPaymentSentence(owed, amount, supplier.name);

  const problem = (): string | null => {
    const found = paymentProblem(draft, today);
    if (found) return found;
    if (receipt && receipt.size > MAX_RECEIPT_BYTES) return "Files must be 20 MB or smaller.";
    return null;
  };

  return (
    <PanelShell
      title={`Record a payment to ${supplier.name}`}
      intro={`${owed > 0 ? `You owe ${formatEgp(owed)} now.` : owed < 0 ? `${supplier.name} is overpaid by ${formatEgp(-owed)} now.` : "Nothing is owed now."} A payment is a lump sum to the supplier, not to one order.`}
      onClose={onClose}
    >
      <form
        className="prod-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit(
            problem(),
            async () => {
              const answer = await api.post<SupplierAnswer>(`/api/prod/suppliers/${supplier.id}/payments`, {
                amount_piastres: amount,
                paid_on: draft.date,
                method: draft.method,
                kind: draft.kind,
                note: draft.note.trim() || null,
              });
              if (!receipt || answer.entry_id === undefined) return answer;
              try {
                return await api.upload<SupplierAnswer>(`/api/prod/entries/${answer.entry_id}/receipt`, receipt);
              } catch (caught) {
                // The payment is saved; saying "failed" here would invite a second, duplicate payment.
                const why = caught instanceof Error && caught.message ? `${caught.message} ` : "";
                return { ...answer, notice: `Payment recorded, but the receipt photo could not be added. ${why}Add it from the account.` };
              }
            },
            `Payment recorded: ${amount === null ? "" : formatEgp(amount)} to ${supplier.name}.`,
          );
        }}
      >
        <TextBox label="Amount, EGP" value={draft.amount} onChange={(value) => set({ amount: value })} inputMode="decimal" />
        <DateBox label="Date" value={draft.date} onChange={(value) => set({ date: value })} max={today} />
        <SelectBox label="Paid by" value={draft.method} onChange={(value) => set({ method: value as PayMethod })} options={METHODS} />
        <SelectBox label="What it is" value={draft.kind} onChange={(value) => set({ kind: value as PayKind })} options={PAY_KINDS} />
        <TextBox label="Note, optional" value={draft.note} onChange={(value) => set({ note: value })} wide max={500} />
        <div className="prod-field prod-wide">
          <label className="field__label" htmlFor="payment-receipt">
            Receipt photo, optional
          </label>
          <input
            key={pickerKey}
            id="payment-receipt"
            className="input"
            type="file"
            accept={RECEIPT_TYPES}
            onChange={(event) => setReceipt(event.target.files?.[0] ?? null)}
          />
          {receipt && (
            <span className="field__hint">
              {receipt.name}{" "}
              <button
                type="button"
                className="button button--quiet"
                onClick={() => {
                  setReceipt(null);
                  setPickerKey((before) => before + 1);
                }}
              >
                Remove<span className="prod-sr"> the chosen receipt</span>
              </button>
            </span>
          )}
        </div>
        <div className="prod-wide prod-small prod-sentence" aria-live="polite">
          {sentence ?? "Give the amount to see what you will owe after it."}
        </div>
        <Actions error={error} busy={busy} label="Save payment" working="Saving…" />
      </form>
    </PanelShell>
  );
}

// ── The balance brought forward, and a correction ────────────────────────────

/**
 * `opening`: the balance brought forward, once. `adjustment`: a correction later on, with a note that says
 * why. Both are typed as a positive amount and a direction, so a minus sign is never what decides it.
 */
export function LineForm({ supplier, run, onClose, mode }: FormProps & { mode: "opening" | "adjustment" }) {
  const today = useMemo(cairoToday, []);
  const opening = mode === "opening";
  const [draft, setDraft] = useState<LineDraft>({ amount: "", direction: "more", date: today, note: "" });
  const { error, busy, submit } = useSubmit(run);
  const set = (patch: Partial<LineDraft>) => setDraft((before) => ({ ...before, ...patch }));
  const signed = signedPiastres(draft);
  const sentence = afterLineSentence(supplier.owed_piastres ?? 0, signed);
  const body = () => ({ amount_piastres: signed, happened_on: draft.date, note: draft.note.trim() || null });
  const done = opening ? "Balance brought forward recorded." : "Correction recorded.";

  return (
    <PanelShell
      title={opening ? "Balance brought forward" : "Add a correction"}
      intro={
        opening
          ? `What was owed to ${supplier.name} (or overpaid to it) before this platform kept its account. It can be recorded once.`
          : "A correction is a new line on the account. Nothing already on it is changed or deleted."
      }
      onClose={onClose}
    >
      <form
        className="prod-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          const problem = lineProblem(draft, today, !opening);
          if (opening) {
            submit(problem, () => api.post<SupplierAnswer>(`/api/prod/suppliers/${supplier.id}/opening`, body()), done);
          } else {
            submit(problem, () => api.post<SupplierAnswer>(`/api/prod/suppliers/${supplier.id}/adjustments`, body()), done);
          }
        }}
      >
        <TextBox label="Amount, EGP" value={draft.amount} onChange={(value) => set({ amount: value })} inputMode="decimal" />
        <SelectBox
          label={opening ? "Who owes whom" : "Effect on the account"}
          value={draft.direction}
          onChange={(value) => set({ direction: value as Direction })}
          options={
            opening
              ? [
                  { value: "more", label: "HBA owes the supplier" },
                  { value: "less", label: "HBA has overpaid the supplier" },
                ]
              : [
                  { value: "more", label: "Adds to what HBA owes" },
                  { value: "less", label: "Takes off what HBA owes" },
                ]
          }
        />
        <DateBox label="Date" value={draft.date} onChange={(value) => set({ date: value })} max={today} />
        <TextBox label={opening ? "Note, optional" : "Why, required"} value={draft.note} onChange={(value) => set({ note: value })} wide max={500} />
        <div className="prod-wide prod-small prod-sentence" aria-live="polite">
          {sentence ?? "Give the amount to see what you will owe after it."}
        </div>
        <Actions error={error} busy={busy} label={opening ? "Save the balance" : "Save the correction"} working="Saving…" />
      </form>
    </PanelShell>
  );
}

// ── Reverse a line, void a purchase ──────────────────────────────────────────

/** Undo a line with a reversing one. The reason is required and is kept with it. */
export function ReverseForm({ line, run, onClose }: { line: AccountLine; run: Run<SupplierAnswer>; onClose: () => void }) {
  const [reason, setReason] = useState("");
  const { error, busy, submit } = useSubmit(run);
  return (
    <PanelShell
      title={`Reverse: ${line.what}`}
      intro="The line stays on the account, struck through, and a new line undoes it. The reason is kept with it."
      onClose={onClose}
    >
      <form
        className="prod-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit(
            isBlank(reason) ? "Say why you are reversing it." : null,
            () => api.post<SupplierAnswer>(`/api/prod/entries/${line.id}/reverse`, { reason: reason.trim() }),
            "Line reversed.",
          );
        }}
      >
        <TextBox label="Why, required" value={reason} onChange={setReason} wide max={400} />
        <Actions
          error={error}
          busy={busy}
          label="Reverse this line"
          working="Reversing…"
          extra={
            <button type="button" className="button" onClick={onClose}>
              Keep it
            </button>
          }
        />
      </form>
    </PanelShell>
  );
}

/** Void a purchase: it and its deposit are reversed on the account, and it is shown struck through. */
export function VoidForm({ purchase, run, onClose }: { purchase: PurchaseView; run: Run<SupplierAnswer>; onClose: () => void }) {
  const [reason, setReason] = useState("");
  const { error, busy, submit } = useSubmit(run);
  return (
    <PanelShell
      title={`Void the ${purchase.item} purchase`}
      intro="Its price and quantity can't be edited, so a wrong purchase is voided. The purchase and any deposit are reversed on the account, and the reason is kept."
      onClose={onClose}
    >
      <form
        className="prod-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit(
            isBlank(reason) ? "Say why you are voiding it." : null,
            () => api.post<SupplierAnswer>(`/api/prod/purchases/${purchase.id}/void`, { reason: reason.trim() }),
            `Purchase voided: ${purchase.item}.`,
          );
        }}
      >
        <TextBox label="Why, required" value={reason} onChange={setReason} wide max={400} />
        <Actions
          error={error}
          busy={busy}
          label="Void this purchase"
          working="Voiding…"
          extra={
            <button type="button" className="button" onClick={onClose}>
              Keep the purchase
            </button>
          }
        />
      </form>
    </PanelShell>
  );
}

// ── Mark a purchase received, or change its expected date (the QC manager's) ─

/** `receive`: the date the goods arrived. `expected`: the date they are expected. Nothing here touches money. */
export function DatesForm({
  purchase,
  mode,
  run,
  onClose,
}: {
  purchase: PurchaseView;
  mode: "receive" | "expected";
  run: Run<SupplierAnswer>;
  onClose: () => void;
}) {
  const today = useMemo(cairoToday, []);
  const receive = mode === "receive";
  const [date, setDate] = useState(receive ? (purchase.received_on ?? today) : (purchase.expected_on ?? ""));
  const { error, busy, submit } = useSubmit(run);
  const send = (body: { received_on: string | null } | { expected_on: string | null }, done: string, problem: string | null = null) =>
    submit(problem, () => api.patch<SupplierAnswer>(`/api/prod/purchases/${purchase.id}`, body), done);

  return (
    <PanelShell
      title={receive ? (purchase.received_on ? `Change when ${purchase.item} arrived` : `Mark ${purchase.item} received`) : `Change when ${purchase.item} is expected`}
      intro={
        receive
          ? `Expected ${purchase.expected_on ? shortDay(purchase.expected_on) : "on no set date"}. Say the day it really arrived.`
          : "Leave the date empty if nobody can say when it will come."
      }
      onClose={onClose}
    >
      <form
        className="prod-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (receive) {
            send(
              { received_on: date },
              `${purchase.item} marked as received.`,
              !date ? "Give the day it arrived." : date > today ? "The date it arrived can't be in the future." : null,
            );
          } else {
            send({ expected_on: date || null }, date ? `${purchase.item} is now expected ${shortDay(date)}.` : `${purchase.item} no longer has an expected date.`);
          }
        }}
      >
        <DateBox
          label={receive ? "Arrived on" : "Expected on"}
          value={date}
          onChange={setDate}
          max={receive ? today : undefined}
        />
        <Actions
          error={error}
          busy={busy}
          label={receive ? (purchase.received_on ? "Save the date" : "Mark received") : "Save the date"}
          working="Saving…"
          extra={
            receive && purchase.received_on ? (
              <button type="button" className="button" disabled={busy} onClick={() => send({ received_on: null }, `${purchase.item} is marked as not received yet.`)}>
                Not arrived after all
              </button>
            ) : undefined
          }
        />
      </form>
    </PanelShell>
  );
}

// ── The supplier's details (also "Add supplier") ─────────────────────────────

type DetailsDraft = {
  name: string;
  contact_person: string;
  phone: string;
  whatsapp: string;
  city: string;
  notes: string;
  active: boolean;
  sectionIds: number[];
};

const blankDetails = (): DetailsDraft => ({ name: "", contact_person: "", phone: "", whatsapp: "", city: "", notes: "", active: true, sectionIds: [] });

const detailsFrom = (supplier: SupplierView): DetailsDraft => ({
  name: supplier.name,
  contact_person: supplier.contact_person ?? "",
  phone: supplier.phone ?? "",
  whatsapp: supplier.whatsapp ?? "",
  city: supplier.city ?? "",
  notes: supplier.notes ?? "",
  active: supplier.active,
  sectionIds: supplier.sections.map((section) => section.id),
});

/**
 * Add a supplier (`supplier` absent) or change one's details, its sections and whether it is active
 * (`production.suppliers`). `sections` is the list to choose from; left out, the form reads it itself.
 */
export function SupplierForm({
  supplier,
  sections,
  run,
  onClose,
}: {
  supplier?: SupplierView;
  sections?: Section[];
  run: Run<SupplierAnswer>;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<DetailsDraft>(() => (supplier ? detailsFrom(supplier) : blankDetails()));
  const [choices, setChoices] = useState<Section[] | null>(sections ?? null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const { error, busy, submit } = useSubmit(run);
  const set = (patch: Partial<DetailsDraft>) => setDraft((before) => ({ ...before, ...patch }));

  useEffect(() => {
    if (sections) return;
    let current = true;
    api.get<SupplierList>("/api/prod/suppliers")
      .then((answer) => current && setChoices(answer.sections))
      .catch((caught) => {
        if (!current) return;
        setChoices([]);
        setLoadError(caught instanceof Error ? caught.message : "The sections could not be loaded.");
      });
    return () => {
      current = false;
    };
  }, [sections]);

  const text = (value: string) => value.trim() || null;
  const body = () => ({
    name: draft.name.trim(),
    contact_person: text(draft.contact_person),
    phone: text(draft.phone),
    whatsapp: text(draft.whatsapp),
    city: text(draft.city),
    notes: text(draft.notes),
    section_ids: draft.sectionIds,
  });
  const toggle = (id: number, on: boolean) =>
    set({ sectionIds: on ? [...draft.sectionIds, id] : draft.sectionIds.filter((other) => other !== id) });

  return (
    <PanelShell
      title={supplier ? `Edit ${supplier.name}` : "Add supplier"}
      intro={supplier ? "A supplier is never deleted: make it inactive when you stop using it." : "It gets the next supplier code by itself."}
      onClose={onClose}
    >
      <form
        className="prod-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          const problem = isBlank(draft.name) ? "Give the supplier's name." : null;
          if (supplier) {
            submit(
              problem,
              () => api.patch<SupplierAnswer>(`/api/prod/suppliers/${supplier.id}`, { ...body(), active: draft.active }),
              `${draft.name.trim()} saved.`,
            );
          } else {
            submit(problem, () => api.post<SupplierAnswer>("/api/prod/suppliers", body()), `Added ${draft.name.trim()}.`);
          }
        }}
      >
        <TextBox label="Name" value={draft.name} onChange={(value) => set({ name: value })} wide max={400} />
        <TextBox label="Contact person, optional" value={draft.contact_person} onChange={(value) => set({ contact_person: value })} max={400} />
        <TextBox label="City, optional" value={draft.city} onChange={(value) => set({ city: value })} max={400} />
        <TextBox label="Phone, optional" value={draft.phone} onChange={(value) => set({ phone: value })} inputMode="tel" max={400} />
        <TextBox label="WhatsApp, optional" value={draft.whatsapp} onChange={(value) => set({ whatsapp: value })} inputMode="tel" max={400} />
        <TextBox label="Notes, optional" value={draft.notes} onChange={(value) => set({ notes: value })} area wide max={4000} />
        <fieldset className="prod-fieldset prod-wide">
          <legend className="field__label">Sections</legend>
          {choices === null && !loadError && <p className="loading" role="status">Loading sections…</p>}
          {loadError && <Problem>{loadError}</Problem>}
          {choices !== null && choices.length === 0 && !loadError && <p className="prod-small">There are no sections yet. Add one from the Suppliers list.</p>}
          {(choices ?? []).map((section) => (
            <label key={section.id} className="prod-check">
              <input type="checkbox" checked={draft.sectionIds.includes(section.id)} onChange={(event) => toggle(section.id, event.target.checked)} />
              {section.name}
            </label>
          ))}
        </fieldset>
        {supplier && (
          <label className="prod-check prod-wide">
            <input type="checkbox" checked={draft.active} onChange={(event) => set({ active: event.target.checked })} />
            Active (untick to stop using this supplier; its history stays)
          </label>
        )}
        <Actions error={error} busy={busy} label={supplier ? "Save changes" : "Add supplier"} working="Saving…" />
      </form>
    </PanelShell>
  );
}
