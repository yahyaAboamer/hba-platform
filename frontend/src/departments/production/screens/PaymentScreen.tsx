import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, can } from "../../../lib/api";
import type { Session } from "../../../lib/api";
import { Money } from "../../../components/Money";
import { cairoToday, shortDay } from "./format";
import {
  MAX_PHOTO_BYTES,
  PHOTO_ACCEPT,
  PRESET_LABELS,
  PRESETS,
  payRangeProblem,
  paymentsQuery,
  paymentsSentence,
  presetOf,
  presetRange,
} from "./paymentLogic";
import type { PayRange } from "./paymentLogic";
import { PaymentRecordForm } from "./PaymentRecordForm";
import type { PaymentAnswer, PaymentList, PaymentPhoto, PaymentRow } from "./types";
import { DateBox, Problem, useIsNarrow } from "./ui";

/** What a payment's photo buttons do. */
type PhotoActions = {
  busy: number | null;
  onAdd: (payment: PaymentRow, files: FileList | null) => void;
  onRemove: (payment: PaymentRow, photo: PaymentPhoto, index: number) => void;
};

const payName = (payment: PaymentRow): string => `${payment.kind_label} to ${payment.supplier.name}, ${shortDay(payment.paid_on)}`;

/** A payment's photos: small previews (a "PDF" tile for a PDF), each opening in a new tab. */
function Photos({ payment, actions }: { payment: PaymentRow; actions: PhotoActions }) {
  const picker = useId();
  const busy = actions.busy === payment.id;
  // A reversed payment takes no new photo and loses none: the server refuses both.
  const editable = !payment.reversed;
  return (
    <div className="prod-pay__photos">
      {payment.photos.length > 0 && (
        <ul className="prod-thumbs">
          {payment.photos.map((photo, index) => {
            const url = `/api/prod/receipts/${photo.id}`;
            const label = `Photo ${index + 1} of ${payName(payment)}`;
            return (
              <li key={photo.id} className="prod-thumb">
                <a href={url} target="_blank" rel="noopener noreferrer" aria-label={`${label} (opens in a new tab)`}>
                  {photo.mime_type.startsWith("image/") ? <img src={`/api/prod/receipts/${photo.id}`} alt="" loading="lazy" /> : <span className="prod-thumb__file">PDF</span>}
                </a>
                {editable && (
                  <button
                    type="button"
                    className="prod-thumb__remove"
                    disabled={busy}
                    aria-label={`Remove ${label.charAt(0).toLowerCase()}${label.slice(1)}`}
                    onClick={() => actions.onRemove(payment, photo, index)}
                  >
                    ×
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {editable && (
        <label className="button button--row prod-pay__pick" htmlFor={picker}>
          {busy ? "Saving…" : "Add photos"}
          <span className="prod-sr"> to {payName(payment)}</span>
          <input
            id={picker}
            className="prod-sr"
            type="file"
            multiple
            accept={PHOTO_ACCEPT}
            disabled={busy}
            onChange={(event) => {
              actions.onAdd(payment, event.target.files);
              event.target.value = "";
            }}
          />
        </label>
      )}
    </div>
  );
}

function Amount({ payment }: { payment: PaymentRow }) {
  return payment.reversed ? (
    <span className="prod-pay--reversed">
      <s>
        <Money piastres={payment.amount_piastres} />
      </s>{" "}
      <span className="prod-pill prod-pill--late">Reversed</span>
    </span>
  ) : (
    <Money piastres={payment.amount_piastres} kind="agreed" />
  );
}

function SupplierLink({ payment }: { payment: PaymentRow }) {
  return <Link to={`/production/suppliers/${payment.supplier.id}`}>{payment.supplier.name}</Link>;
}

function PaymentTable({ payments, actions }: { payments: PaymentRow[]; actions: PhotoActions }) {
  return (
    <div className="surface prod-scroll">
      <table className="table prod-pay__table">
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">Supplier</th>
            <th scope="col">What</th>
            <th scope="col">Paid by</th>
            <th scope="col" className="numeric">Amount</th>
            <th scope="col">Note</th>
            <th scope="col">Photos</th>
          </tr>
        </thead>
        <tbody>
          {payments.map((payment) => (
            <tr key={payment.id} className={payment.reversed ? "prod-pay--reversed" : undefined}>
              <td>{shortDay(payment.paid_on)}</td>
              <td>
                <SupplierLink payment={payment} />
              </td>
              <td>{payment.kind_label}</td>
              <td>{payment.method_label}</td>
              <td className="numeric">
                <Amount payment={payment} />
              </td>
              <td className="prod-pay__note">{payment.note ?? ""}</td>
              <td>
                <Photos payment={payment} actions={actions} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PaymentCards({ payments, actions }: { payments: PaymentRow[]; actions: PhotoActions }) {
  return (
    <ul className="prod-cards prod-pay__cards">
      {payments.map((payment) => (
        <li key={payment.id} className={`prod-card${payment.reversed ? " prod-pay--reversed" : ""}`}>
          <div className="prod-pay__top">
            <SupplierLink payment={payment} />
            <Amount payment={payment} />
          </div>
          <div className="prod-small">
            {shortDay(payment.paid_on)} · {payment.kind_label} · {payment.method_label}
          </div>
          {payment.note && <div className="prod-small prod-pay__note">{payment.note}</div>}
          <Photos payment={payment} actions={actions} />
        </li>
      ))}
    </ul>
  );
}

/** `/production/payments`: every payment to every supplier in a period, with its photos. Owner only. */
export function PaymentScreen({ session }: { session: Session }) {
  const isOwner = can(session, "production.owner");
  const narrow = useIsNarrow();
  const today = useMemo(cairoToday, []);
  const [range, setRange] = useState<PayRange>(() => presetRange("month", today));
  const [supplier, setSupplier] = useState("");
  const [data, setData] = useState<PaymentList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const recordButton = useRef<HTMLButtonElement>(null);
  const latest = useRef(0);
  const alive = useRef(true);
  const supplierBox = useId();

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      latest.current += 1;
    };
  }, []);

  const wrongWay = payRangeProblem(range);
  const load = useCallback(() => {
    const mine = ++latest.current;
    if (!isOwner || payRangeProblem(range)) return;
    api.get<PaymentList>(`/api/prod/payments?${paymentsQuery(range, supplier)}`)
      .then((answer) => {
        if (latest.current !== mine) return;
        setData(answer);
        setError(null);
      })
      .catch((caught) => {
        if (latest.current === mine) setError(caught instanceof Error ? caught.message : "The payments could not be loaded.");
      });
  }, [isOwner, range, supplier]);
  useEffect(load, [load]);

  /** Put a payment the server answered with in its place in the list. */
  function replace(payment: PaymentRow) {
    setData((before) => before && { ...before, payments: before.payments.map((row) => (row.id === payment.id ? payment : row)) });
  }

  async function addPhotos(payment: PaymentRow, list: FileList | null) {
    const files = Array.from(list ?? []);
    if (!files.length) return;
    setNotice(null);
    setProblem(null);
    const tooBig = files.filter((file) => file.size > MAX_PHOTO_BYTES);
    if (tooBig.length) {
      setProblem(`Photos must be 20 MB or smaller: ${tooBig.map((file) => file.name).join(", ")}.`);
      return;
    }
    setBusy(payment.id);
    const failed: string[] = [];
    let added = 0;
    for (const file of files) {
      try {
        const answer = await api.upload<PaymentAnswer>(`/api/prod/entries/${payment.id}/photos`, file);
        if (!alive.current) return;
        replace(answer.payment);
        added += 1;
      } catch (caught) {
        failed.push(`${file.name}${caught instanceof Error && caught.message ? ` (${caught.message})` : ""}`);
      }
    }
    if (!alive.current) return;
    setBusy(null);
    if (added) setNotice(`${added === 1 ? "Photo" : `${added} photos`} added to ${payName(payment)}.`);
    if (failed.length) setProblem(`Could not add: ${failed.join(", ")}.`);
  }

  async function removePhoto(payment: PaymentRow, photo: PaymentPhoto, index: number) {
    if (!window.confirm(`Remove photo ${index + 1} from ${payName(payment)}? It cannot be brought back.`)) return;
    setNotice(null);
    setProblem(null);
    setBusy(payment.id);
    try {
      const answer = await api.del<PaymentAnswer>(`/api/prod/receipts/${photo.id}`);
      if (!alive.current) return;
      replace(answer.payment);
      setNotice(`Photo removed from ${payName(payment)}.`);
      // The button pressed is gone: the heading takes focus, and the notice is read.
      heading.current?.focus();
    } catch (caught) {
      if (alive.current) setProblem(caught instanceof Error ? caught.message : "The photo could not be removed.");
    } finally {
      if (alive.current) setBusy(null);
    }
  }

  function closeRecord() {
    setRecording(false);
    queueMicrotask(() => (recordButton.current ?? heading.current)?.focus());
  }

  function recorded(words: string) {
    setNotice(words);
    closeRecord();
    load();
  }

  if (!isOwner) {
    return (
      <>
        <div className="page__head">
          <div className="page__title">
            <h1>Payments</h1>
          </div>
        </div>
        <p className="empty">Payments are for the owner and the production manager.</p>
      </>
    );
  }

  const chosen = presetOf(range, today);
  const actions: PhotoActions = { busy, onAdd: (payment, files) => void addPhotos(payment, files), onRemove: (payment, photo, index) => void removePhoto(payment, photo, index) };

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1 ref={heading} tabIndex={-1}>Payments</h1>
          <span className="page__subtitle">{data && !wrongWay ? paymentsSentence(data.payments.filter((payment) => !payment.reversed).length, data.total_piastres) : "Loading"}</span>
        </div>
        <div className="prod-head-actions">
          <button
            ref={recordButton}
            type="button"
            className="button button--primary"
            disabled={!data}
            onClick={() => {
              setNotice(null);
              setProblem(null);
              setRecording(true);
            }}
          >
            Record payment
          </button>
        </div>
      </div>

      {notice && <p className="notice notice--settled" role="status">{notice}</p>}
      {problem && <Problem>{problem}</Problem>}

      {recording && data && <PaymentRecordForm suppliers={data.suppliers} onSaved={recorded} onClose={closeRecord} />}

      <div className="prod-chips" role="group" aria-label="Period">
        {PRESETS.map((preset) => (
          <button
            key={preset}
            type="button"
            className={`chip${chosen === preset ? " chip--on" : ""}`}
            aria-pressed={chosen === preset}
            onClick={() => setRange(presetRange(preset, today))}
          >
            {PRESET_LABELS[preset]}
          </button>
        ))}
      </div>
      <div className="prod-sectionbar prod-range" role="group" aria-label="Paid between">
        <DateBox label="From" value={range.from} max={range.to || undefined} onChange={(from) => setRange((before) => ({ ...before, from }))} />
        <DateBox label="To" value={range.to} min={range.from || undefined} onChange={(to) => setRange((before) => ({ ...before, to }))} />
        <div className="prod-field">
          <label className="field__label" htmlFor={supplierBox}>
            Supplier
          </label>
          <select id={supplierBox} className="input" value={supplier} onChange={(event) => setSupplier(event.target.value)}>
            <option value="">All suppliers</option>
            {(data?.suppliers ?? []).map((one) => (
              <option key={one.id} value={one.id}>
                {one.name}
              </option>
            ))}
            {supplier && data && !data.suppliers.some((one) => one.id === supplier) && <option value={supplier}>{supplier}</option>}
          </select>
        </div>
      </div>
      {wrongWay && <Problem>{wrongWay}</Problem>}

      {error && (
        <div>
          <Problem>{error}</Problem>
          <button type="button" className="button" onClick={load}>
            Try again
          </button>
        </div>
      )}
      {!error && !wrongWay && data === null && <p className="loading" role="status">Loading payments…</p>}
      {data && !wrongWay && !error && (
        data.payments.length === 0 ? (
          <p className="empty">No payments in this period.</p>
        ) : narrow ? (
          <PaymentCards payments={data.payments} actions={actions} />
        ) : (
          <PaymentTable payments={data.payments} actions={actions} />
        )
      )}
    </>
  );
}
