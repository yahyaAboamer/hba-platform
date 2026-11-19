import { useId, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";

import { api } from "../../../lib/api";
import { formatEgp } from "../../../lib/money";
import { cairoToday } from "./format";
import { MAX_PHOTO_BYTES, PHOTO_ACCEPT, photoFailures } from "./paymentLogic";
import { METHODS, PAY_KINDS, oldestDay, paymentProblem, poundsToPiastres } from "./supplierLogic";
import type { PaymentDraft } from "./supplierLogic";
import type { PayKind, PayMethod, SupplierAnswer } from "./types";
import { Actions, DateBox, PanelShell, SelectBox, TextBox } from "./ui";

/**
 * Record a payment to any supplier, with photos. The payment is saved first (the supplier's own payment
 * route), then each photo is added to it; a photo that fails is named and the payment stays recorded, so
 * nobody records it twice.
 */
export function PaymentRecordForm({
  suppliers,
  onSaved,
  onClose,
}: {
  suppliers: readonly { id: string; name: string }[];
  /** `words` is what the screen says once the panel is closed. */
  onSaved: (words: string) => void;
  onClose: () => void;
}) {
  const id = useId();
  const today = useMemo(cairoToday, []);
  const [supplierId, setSupplierId] = useState("");
  const [draft, setDraft] = useState<PaymentDraft>({ amount: "", date: today, method: "bank_transfer", kind: "weekly", note: "" });
  const [photos, setPhotos] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const flying = useRef(false);
  const set = (patch: Partial<PaymentDraft>) => setDraft((before) => ({ ...before, ...patch }));

  function addFiles(list: FileList | null) {
    const chosen = Array.from(list ?? []);
    if (chosen.length) setPhotos((before) => [...before, ...chosen]);
  }

  function problem(): string | null {
    if (!supplierId) return "Choose the supplier.";
    const found = paymentProblem(draft, today);
    if (found) return found;
    if (photos.some((photo) => photo.size > MAX_PHOTO_BYTES)) return "Photos must be 20 MB or smaller.";
    return null;
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (flying.current) return;
    const found = problem();
    if (found) {
      setError(found);
      return;
    }
    const amount = poundsToPiastres(draft.amount);
    const supplier = suppliers.find((one) => one.id === supplierId);
    flying.current = true;
    setError(null);
    setBusy(true);
    let entryId: number | undefined;
    try {
      const answer = await api.post<SupplierAnswer>(`/api/prod/suppliers/${supplierId}/payments`, {
        amount_piastres: amount,
        paid_on: draft.date,
        method: draft.method,
        kind: draft.kind,
        note: draft.note.trim() || null,
      });
      entryId = answer.entry_id;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The payment could not be saved.");
      setBusy(false);
      flying.current = false;
      return;
    }
    const failed: { name: string; why: string }[] = [];
    for (const photo of photos) {
      if (entryId === undefined) {
        failed.push({ name: photo.name, why: "" });
        continue;
      }
      try {
        await api.upload(`/api/prod/entries/${entryId}/photos`, photo);
      } catch (caught) {
        failed.push({ name: photo.name, why: caught instanceof Error ? caught.message : "" });
      }
    }
    const recorded = `Payment recorded: ${amount === null ? "" : formatEgp(amount)} to ${supplier?.name ?? "the supplier"}.`;
    const missing = photoFailures(failed);
    onSaved(missing ? `${recorded} ${missing}` : recorded);
  }

  return (
    <PanelShell title="Record payment" intro="A lump sum to a supplier, not to one order. Photos are added once it is saved." onClose={onClose}>
      <form className="prod-form" onSubmit={save} noValidate>
        <div className="prod-field">
          <label className="field__label" htmlFor={`${id}-supplier`}>
            Supplier
          </label>
          <select id={`${id}-supplier`} className="input" value={supplierId} onChange={(event) => setSupplierId(event.target.value)}>
            <option value="">Choose the supplier…</option>
            {suppliers.map((supplier) => (
              <option key={supplier.id} value={supplier.id}>
                {supplier.name}
              </option>
            ))}
          </select>
        </div>
        <TextBox label="Amount, EGP" value={draft.amount} onChange={(value) => set({ amount: value })} inputMode="decimal" />
        <DateBox label="Date" value={draft.date} onChange={(value) => set({ date: value })} min={oldestDay(today)} max={today} />
        <SelectBox label="Paid by" value={draft.method} onChange={(value) => set({ method: value as PayMethod })} options={METHODS} />
        <SelectBox label="What it is" value={draft.kind} onChange={(value) => set({ kind: value as PayKind })} options={PAY_KINDS} />
        <TextBox label="Note, optional" value={draft.note} onChange={(value) => set({ note: value })} wide max={500} />
        <fieldset className="prod-fieldset prod-wide">
          <legend className="field__label">Photos, optional</legend>
          <div className="prod-pay__pickers">
            <label className="button button--row prod-pay__pick">
              Choose photos
              <input
                className="prod-sr"
                type="file"
                multiple
                accept={PHOTO_ACCEPT}
                onChange={(event) => {
                  addFiles(event.target.files);
                  event.target.value = "";
                }}
              />
            </label>
            <label className="button button--row prod-pay__pick">
              Take a photo
              <input
                className="prod-sr"
                type="file"
                accept="image/*"
                capture="environment"
                onChange={(event) => {
                  addFiles(event.target.files);
                  event.target.value = "";
                }}
              />
            </label>
            <span className="field__hint">Photos or PDFs, up to 20 MB each.</span>
          </div>
          {photos.length > 0 && (
            <ul className="prod-filelist">
              {photos.map((photo, index) => (
                <li key={`${photo.name}-${index}`}>
                  {photo.name}{" "}
                  <button
                    type="button"
                    className="button button--quiet"
                    onClick={() => setPhotos((before) => before.filter((_, at) => at !== index))}
                  >
                    Remove<span className="prod-sr"> {photo.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </fieldset>
        <Actions error={error} busy={busy} label="Save payment" working="Saving…" />
      </form>
    </PanelShell>
  );
}
