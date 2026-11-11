import { useRef, useState } from "react";

import { ApiError, api } from "../../lib/api";
import { formatEgp } from "../../lib/money";
import { OpsIcon, age, dayAndTime, dayMonth, useNow, useOpsTab } from "../../components/OpsSource";
import "./OperationsDashboard.css";

/**
 * Operations → Returns: the customers owed a refund, and whether it has
 * been sent (ADR 0079). It replaces the Google Sheet kept with Bosta.
 *
 * **It records; it never pays.** Each row is added by its Khazenly number;
 * the platform reads Khazenly's tracking every 30 minutes and marks the row
 * received when Khazenly says *Return Completed*. A person sends the money
 * elsewhere and marks it paid here.
 *
 * Grouped by the next act: ready to refund, on the way back, needs
 * attention, paid; each group folds. Viewers see it all; staff, the
 * manager and the admin (`returns.edit`) add, change and mark paid. A
 * refund can be marked paid before it is back when the person confirms it,
 * and carry an optional photo of the payment (ADR 0080).
 *
 * No approved frame exists for this tab; it is drawn from the Operations
 * dashboard's own pieces (heading, cards, panels, expanding rows).
 */

type Step = { step: string; at: string | null; note: string | null };
type Group = "ready" | "on_the_way" | "attention" | "paid";
type Reason =
  | "not_found"
  | "unreadable"
  | "contact_success_manager"
  | "stuck"
  | "unpaid_late"
  | "details_missing";

export type Refund = {
  id: number;
  khazenly_number: string;
  kind: "return" | "exchange";
  merchant_order: string | null;
  order_number: string | null;
  customer_name: string | null;
  customer_phone: string | null;
  amount: string | null;
  method: string | null;
  refund_to: string | null;
  step: string | null;
  step_at: string | null;
  timeline: Step[];
  received_at: string | null;
  checked_at: string | null;
  check_error: string | null;
  paid_on: string | null;
  paid_by: string | null;
  paid_early: boolean;
  proof_url: string | null;
  created_at: string | null;
  group: Group;
  attention: Reason[];
  tracking_url: string;
};

type Method = { value: string; label: string };

export type ReturnsTab = {
  refunds: Refund[];
  totals: {
    owed_now: string;
    owed_count: number;
    owed_missing_amount: number;
    refunded_this_month: string;
    refunded_count: number;
    month: string;
  };
  tracking: { checked_at: string | null; every_minutes: number; khazenly_down: boolean };
  paid_shown: number;
  methods: Method[];
};

type Added = { added: Refund[]; refused: { number: string; reason: string }[] };

const REASON_WORDS: Record<Reason, string> = {
  not_found: "Khazenly doesn't know this number",
  unreadable: "Khazenly didn't answer the last check",
  contact_success_manager: "Khazenly says: contact your success manager",
  stuck: "No movement for 3 days",
  unpaid_late: "Received over 2 days ago, not paid yet",
  details_missing: "Amount or refund details missing",
};

const GROUPS: { key: Group; title: string; empty: string; hint: string }[] = [
  {
    key: "ready",
    title: "Ready to refund",
    empty: "Nothing to refund right now.",
    hint: "Back at Khazenly. Send the money, then mark it paid.",
  },
  {
    key: "on_the_way",
    title: "On the way back",
    empty: "No returns on the way.",
    hint: "Khazenly is checked every 30 minutes.",
  },
  {
    key: "attention",
    title: "Needs attention",
    empty: "Nothing needs a look.",
    hint: "Stuck, unknown to Khazenly, or flagged by them. One paid early can still be recorded.",
  },
  {
    key: "paid",
    title: "Paid",
    empty: "No refund has been marked paid yet.",
    hint: "Locked once paid. Undo needs a reason. One paid early is still checked with Khazenly.",
  },
];

const KIND_WORDS = { return: "Return", exchange: "Exchange" } as const;

function egp(amount: string | null): string {
  if (amount === null) return "—";
  return formatEgp(Math.round(Number(amount) * 100));
}

function methodLabel(methods: Method[], value: string | null): string {
  return methods.find((method) => method.value === value)?.label ?? "—";
}

/** Today in Cairo, as the date input wants it. */
function cairoToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Cairo" }).format(new Date());
}

function monthName(month: string): string {
  const [year, number] = month.split("-").map(Number);
  return new Date(Date.UTC(year, number - 1, 1)).toLocaleString("en-GB", { month: "long", timeZone: "UTC" });
}

function failure(caught: unknown): string {
  return caught instanceof ApiError ? caught.message : "Couldn't reach the platform. Try again.";
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

// ── Adding ──────────────────────────────────────────────────────────────────

function AddRefund({ methods, onAdded }: { methods: Method[]; onAdded: () => void }) {
  const [numbers, setNumbers] = useState("");
  const [kind, setKind] = useState<"return" | "exchange">("return");
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("instapay");
  const [refundTo, setRefundTo] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Added | null>(null);

  const pasted = numbers.split(/[\s,;]+/).filter(Boolean);
  const many = pasted.length > 1;

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !pasted.length) return;
    setBusy(true);
    setError(null);
    setResult(null);
    const body: Record<string, unknown> = { numbers: [numbers], kind };
    if (!many) {
      if (amount.trim()) body.amount = amount.trim();
      if (refundTo.trim()) {
        body.method = method;
        body.refund_to = refundTo.trim();
      }
      if (name.trim()) body.customer_name = name.trim();
      if (phone.trim()) body.customer_phone = phone.trim();
    }
    api
      .post<Added>("/api/order-ops/returns", body)
      .then((answer) => {
        setResult(answer);
        if (answer.added.length) {
          setNumbers(answer.refused.map((item) => item.number).join("\n"));
          setAmount("");
          setRefundTo("");
          setName("");
          setPhone("");
          onAdded();
        }
      })
      .catch((caught: unknown) => setError(failure(caught)))
      .finally(() => setBusy(false));
  }

  return (
    <section className="panel ops-list" aria-labelledby="ops-rt-add">
      <div className="panel__head ops-kh__head">
        <h2 className="panel__title" id="ops-rt-add">
          Add a refund
        </h2>
        <p className="ops-hint">Khazenly is read at once; the customer comes from the Shopify order.</p>
      </div>
      <form className="ops-rt__form" onSubmit={submit}>
        <label className="field ops-rt__numbers">
          <span className="field__label">Khazenly number</span>
          <textarea
            className="input"
            rows={many ? 3 : 1}
            value={numbers}
            disabled={busy}
            placeholder="KH-HBA-08997921"
            onChange={(event) => setNumbers(event.target.value)}
            required
          />
          <span className="field__hint">Paste several, one a line, to add them together. Up to 20.</span>
        </label>

        <fieldset className="field ops-rt__kind">
          <legend className="field__label">For</legend>
          <span className="seg">
            {(["return", "exchange"] as const).map((value) => (
              <label className="seg-opt" key={value}>
                <input type="radio" name="ops-rt-kind" checked={kind === value} onChange={() => setKind(value)} />
                {KIND_WORDS[value]}
              </label>
            ))}
          </span>
        </fieldset>

        {many ? (
          <p className="ops-hint ops-rt__wide">
            {plural(pasted.length, "number", "numbers")} pasted. Add the amount and refund details to each one after.
          </p>
        ) : (
          <div className="ops-rt__grid ops-rt__wide">
            <label className="field">
              <span className="field__label">Customer phone</span>
              <input className="input" inputMode="tel" value={phone} disabled={busy} autoComplete="off" onChange={(event) => setPhone(event.target.value)} />
            </label>
            <label className="field">
              <span className="field__label">Customer name</span>
              <input className="input" value={name} disabled={busy} autoComplete="off" onChange={(event) => setName(event.target.value)} />
              <span className="field__hint">Leave empty to take it from Shopify.</span>
            </label>
            <label className="field">
              <span className="field__label">Amount to refund (EGP)</span>
              <input className="input" inputMode="decimal" value={amount} disabled={busy} onChange={(event) => setAmount(event.target.value)} />
            </label>
            <label className="field">
              <span className="field__label">Refund by</span>
              <select className="input" value={method} disabled={busy} onChange={(event) => setMethod(event.target.value)}>
                {methods.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field__label">Refund ID</span>
              <input className="input" value={refundTo} disabled={busy} onChange={(event) => setRefundTo(event.target.value)} />
              <span className="field__hint">A mobile number, an …@instapay address or an ipn.eg link.</span>
            </label>
          </div>
        )}

        <div className="ops-kh__actions ops-rt__wide">
          <button type="submit" className="button button--primary" disabled={busy || !pasted.length}>
            {busy ? "Checking Khazenly…" : many ? `Add ${pasted.length} refunds` : "Add refund"}
          </button>
          <p className="ops-hint">The amount and refund ID can wait; a refund needs them before it is marked paid.</p>
        </div>
      </form>

      {error && (
        <p className="notice notice--refused ops-rt__note" role="alert">
          {error}
        </p>
      )}
      {result && (
        <div className="ops-rt__note" role="status">
          {result.added.length > 0 && (
            <p className="notice notice--settled">Added {plural(result.added.length, "refund", "refunds")}.</p>
          )}
          {result.refused.length > 0 && (
            <div className="notice notice--refused">
              <p className="ops-rt__refused-head">Not added:</p>
              <ul className="ops-rt__refused">
                {result.refused.map((item) => (
                  <li key={item.number}>
                    <span className="num">{item.number}</span>: {item.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

// ── One refund, opened ──────────────────────────────────────────────────────

function Timeline({ refund, now }: { refund: Refund; now: number }) {
  return (
    <div className="ops-rt__timeline">
      <h3 className="ops-rt__sub">Khazenly</h3>
      {refund.timeline.length ? (
        <ol>
          {refund.timeline.map((entry, index) => (
            <li key={`${entry.step}-${entry.at ?? index}`} className={index === 0 ? "ops-rt__now" : undefined}>
              <span>{entry.step}</span>
              <small className="num">
                {entry.at ? dayAndTime(entry.at) : "No time given"}
                {entry.note ? ` · ${entry.note}` : ""}
              </small>
            </li>
          ))}
        </ol>
      ) : (
        <p className="ops-hint">Khazenly has no steps for this order yet.</p>
      )}
      <p className="ops-hint">
        {refund.checked_at ? `Checked ${age(refund.checked_at, now)} ago` : "Not checked yet"}
        {refund.check_error ? ` · ${refund.check_error}` : ""}
        {" · "}
        <a className="ops-ext" href={refund.tracking_url} target="_blank" rel="noreferrer">
          Open on Khazenly <OpsIcon name="ext" />
        </a>
      </p>
    </div>
  );
}

function EditForm({ refund, methods, onDone }: { refund: Refund; methods: Method[]; onDone: () => void }) {
  const [kind, setKind] = useState(refund.kind);
  const [amount, setAmount] = useState(refund.amount ?? "");
  const [method, setMethod] = useState(refund.method ?? "instapay");
  const [refundTo, setRefundTo] = useState(refund.refund_to ?? "");
  const [name, setName] = useState(refund.customer_name ?? "");
  const [phone, setPhone] = useState(refund.customer_phone ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    api
      .patch(`/api/order-ops/returns/${refund.id}`, {
        kind,
        amount: amount.trim() || null,
        method: refundTo.trim() ? method : refund.method,
        refund_to: refundTo.trim() || null,
        customer_name: name.trim() || null,
        customer_phone: phone.trim() || null,
      })
      .then(() => {
        setSaved(true);
        onDone();
      })
      .catch((caught: unknown) => setError(failure(caught)))
      .finally(() => setBusy(false));
  }

  const id = `ops-rt-${refund.id}`;
  return (
    <form className="ops-rt__edit" onSubmit={save} aria-labelledby={`${id}-edit`}>
      <h3 className="ops-rt__sub" id={`${id}-edit`}>
        Details
      </h3>
      <div className="ops-rt__grid">
        <fieldset className="field">
          <legend className="field__label">For</legend>
          <span className="seg">
            {(["return", "exchange"] as const).map((value) => (
              <label className="seg-opt" key={value}>
                <input type="radio" name={`${id}-kind`} checked={kind === value} onChange={() => setKind(value)} />
                {KIND_WORDS[value]}
              </label>
            ))}
          </span>
        </fieldset>
        <label className="field">
          <span className="field__label">Customer phone</span>
          <input className="input" inputMode="tel" value={phone} autoComplete="off" onChange={(event) => setPhone(event.target.value)} />
        </label>
        <label className="field">
          <span className="field__label">Customer name</span>
          <input className="input" value={name} autoComplete="off" onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="field">
          <span className="field__label">Amount to refund (EGP)</span>
          <input className="input" inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} />
        </label>
        <label className="field">
          <span className="field__label">Refund by</span>
          <select className="input" value={method} onChange={(event) => setMethod(event.target.value)}>
            {methods.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Refund ID</span>
          <input className="input" value={refundTo} onChange={(event) => setRefundTo(event.target.value)} />
        </label>
      </div>
      <div className="ops-kh__actions">
        <button type="submit" className="button" disabled={busy}>
          {busy ? "Saving…" : "Save details"}
        </button>
        {saved && !error && <p className="ops-hint" role="status">Saved.</p>}
      </div>
      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

const PHOTO_TYPES = "image/jpeg,image/png,image/webp";

function PayForm({
  refund,
  methods,
  onDone,
  onNotice,
}: {
  refund: Refund;
  methods: Method[];
  onDone: () => void;
  onNotice: (text: string) => void;
}) {
  // Not back at Khazenly yet: paying now is early, and must be confirmed.
  const early = refund.received_at === null;
  const [confirmed, setConfirmed] = useState(false);
  const [photo, setPhoto] = useState<File | null>(null);
  const [paidOn, setPaidOn] = useState(cairoToday());
  const [amount, setAmount] = useState(refund.amount ?? "");
  const [method, setMethod] = useState(refund.method ?? "instapay");
  const [refundTo, setRefundTo] = useState(refund.refund_to ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function pay(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    api
      .post(`/api/order-ops/returns/${refund.id}/paid`, {
        paid_on: paidOn,
        amount: amount.trim() || null,
        method,
        refund_to: refundTo.trim() || null,
        early,
      })
      .then(async () => {
        if (photo) {
          try {
            await api.upload(`/api/order-ops/returns/${refund.id}/proof`, photo);
          } catch (caught: unknown) {
            onNotice(`Recorded as paid, but the photo didn't save: ${failure(caught)} Add it again below.`);
          }
        }
        onDone();
      })
      .catch((caught: unknown) => {
        setError(failure(caught));
        setBusy(false);
      });
  }

  const id = `ops-rt-${refund.id}-pay`;
  return (
    <form className="ops-rt__pay" onSubmit={pay} aria-labelledby={id}>
      <h3 className="ops-rt__sub" id={id}>
        {early ? "Mark as paid early" : "Mark as paid"}
      </h3>
      <p className="ops-hint">This records the refund you sent. It sends nothing.</p>
      {early && (
        <label className="ops-rt__early">
          <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
          <span>
            I paid it before Khazenly said the return was back.
            <small>It moves to Paid and is still checked with Khazenly until the return is completed.</small>
          </span>
        </label>
      )}
      <div className="ops-rt__grid">
        <label className="field">
          <span className="field__label">Sent on</span>
          <input className="input" type="date" value={paidOn} max={cairoToday()} onChange={(event) => setPaidOn(event.target.value)} required />
        </label>
        <label className="field">
          <span className="field__label">Amount sent (EGP)</span>
          <input className="input" inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} required />
        </label>
        <label className="field">
          <span className="field__label">Sent by</span>
          <select className="input" value={method} onChange={(event) => setMethod(event.target.value)}>
            {methods.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Refund ID</span>
          <input className="input" value={refundTo} onChange={(event) => setRefundTo(event.target.value)} required />
        </label>
        <label className="field ops-rt__photo">
          <span className="field__label">
            Photo of the payment <span className="ops-muted">(optional)</span>
          </span>
          <input
            className="input"
            type="file"
            accept={PHOTO_TYPES}
            onChange={(event) => setPhoto(event.target.files?.[0] ?? null)}
          />
          <span className="field__hint">A screenshot of the transfer. JPG, PNG or WebP, up to 10 MB.</span>
        </label>
      </div>
      <div className="ops-kh__actions">
        <button type="submit" className="button button--primary" disabled={busy || (early && !confirmed)}>
          {busy
            ? "Recording…"
            : `Record ${amount.trim() ? egp(amount.trim()) : "the refund"} as paid${early ? " early" : ""}`}
        </button>
      </div>
      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

function Proof({ refund, canEdit, onDone }: { refund: Refund; canEdit: boolean; onDone: () => void }) {
  const picker = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function run(request: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    request()
      .then(onDone)
      .catch((caught: unknown) => setError(failure(caught)))
      .finally(() => setBusy(false));
  }

  // The server's address carries a version, so a replaced photo is never
  // the old one from the browser's cache.
  const version = refund.proof_url?.split("v=")[1] ?? "";
  if (!refund.proof_url && !canEdit) return null;
  return (
    <div className="ops-rt__proof">
      <h3 className="ops-rt__sub">Payment photo</h3>
      {refund.proof_url ? (
        <a
          className="ops-rt__proofimg"
          href={`/api/order-ops/returns/${refund.id}/proof?v=${version}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          <img
            src={`/api/order-ops/returns/${refund.id}/proof?v=${version}`}
            alt={`Payment photo for ${refund.khazenly_number}`}
            loading="lazy"
          />
          <span>Open full size</span>
        </a>
      ) : (
        <p className="ops-hint">None yet. It's optional.</p>
      )}
      {canEdit && (
        <div className="ops-kh__actions">
          <input
            ref={picker}
            type="file"
            accept={PHOTO_TYPES}
            hidden
            aria-label={refund.proof_url ? "Replace the payment photo" : "Add a payment photo"}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) run(() => api.upload(`/api/order-ops/returns/${refund.id}/proof`, file));
            }}
          />
          <button type="button" className="button button--row" disabled={busy} onClick={() => picker.current?.click()}>
            {busy ? "Saving…" : refund.proof_url ? "Replace photo" : "Add a photo"}
          </button>
          {refund.proof_url && (
            <button type="button" className="button button--row" disabled={busy} onClick={() => run(() => api.del(`/api/order-ops/returns/${refund.id}/proof`))}>
              Remove photo
            </button>
          )}
        </div>
      )}
      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function PaidActions({ refund, onDone }: { refund: Refund; onDone: () => void }) {
  const [undoing, setUndoing] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function undo(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    api
      .post(`/api/order-ops/returns/${refund.id}/unpaid`, { reason })
      .then(onDone)
      .catch((caught: unknown) => {
        setError(failure(caught));
        setBusy(false);
      });
  }

  function check() {
    setBusy(true);
    setError(null);
    api
      .post(`/api/order-ops/returns/${refund.id}/check`)
      .then(onDone)
      .catch((caught: unknown) => setError(failure(caught)))
      .finally(() => setBusy(false));
  }

  if (!undoing) {
    return (
      <>
        <div className="ops-kh__actions">
          {refund.received_at === null && (
            <button type="button" className="button button--row" disabled={busy} onClick={check}>
              {busy ? "Checking…" : "Check Khazenly now"}
            </button>
          )}
          <button type="button" className="button button--row" onClick={() => setUndoing(true)}>
            Undo paid
          </button>
        </div>
        {error && (
          <p className="notice notice--refused" role="alert">
            {error}
          </p>
        )}
      </>
    );
  }
  return (
    <form className="ops-rt__undo" onSubmit={undo}>
      <label className="field">
        <span className="field__label">Why is it no longer paid?</span>
        <input className="input" value={reason} onChange={(event) => setReason(event.target.value)} required minLength={3} maxLength={300} autoFocus />
        <span className="field__hint">Kept in the activity log.</span>
      </label>
      <div className="ops-kh__actions">
        <button type="submit" className="button button--danger" disabled={busy || reason.trim().length < 3}>
          {busy ? "Undoing…" : "Undo paid"}
        </button>
        <button type="button" className="button" onClick={() => setUndoing(false)} disabled={busy}>
          Keep it paid
        </button>
      </div>
      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

function RowActions({ refund, onDone }: { refund: Refund; onDone: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function run(request: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    request()
      .then(onDone)
      .catch((caught: unknown) => setError(failure(caught)))
      .finally(() => setBusy(false));
  }

  return (
    <>
      <div className="ops-kh__actions">
        {refund.received_at === null && (
          <button
            type="button"
            className="button button--row"
            disabled={busy}
            onClick={() => run(() => api.post(`/api/order-ops/returns/${refund.id}/check`))}
          >
            {busy && !confirming ? "Checking…" : "Check Khazenly now"}
          </button>
        )}
        {confirming ? (
          <>
            <button
              type="button"
              className="button button--row button--danger"
              disabled={busy}
              onClick={() => run(() => api.del(`/api/order-ops/returns/${refund.id}`))}
            >
              Delete {refund.khazenly_number}
            </button>
            <button type="button" className="button button--row" onClick={() => setConfirming(false)}>
              Keep it
            </button>
          </>
        ) : (
          <button type="button" className="button button--row" onClick={() => setConfirming(true)}>
            Delete…
          </button>
        )}
      </div>
      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

function RefundRow({
  refund,
  methods,
  canEdit,
  now,
  onChanged,
}: {
  refund: Refund;
  methods: Method[];
  canEdit: boolean;
  now: number;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [payingEarly, setPayingEarly] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const id = `ops-rt-row-${refund.id}`;
  const flags = refund.attention;
  const paid = refund.group === "paid";
  // Paid early and not back yet: its Khazenly step still shows (ADR 0080).
  const stillComing = paid && refund.received_at === null;
  const tags = [
    ...(refund.paid_early ? ["Paid before it was back"] : []),
    ...(stillComing ? [`Khazenly: ${refund.step ?? "not read yet"}`] : []),
    ...(refund.proof_url ? ["Photo"] : []),
  ];

  return (
    <li className="ops-rt__row">
      <button
        type="button"
        className="ops-rt__summary"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen(!open)}
      >
        <span className="ops-rt__who">
          <span className="num ops-rt__kh">{refund.khazenly_number}</span>
          <small>
            {KIND_WORDS[refund.kind]}
            {refund.order_number ? ` · Shopify ${refund.order_number}` : ""}
          </small>
        </span>
        <span className="ops-rt__customer">
          <span>{refund.customer_name ?? <span className="ops-muted">No name</span>}</span>
          <small className="num">{refund.customer_phone ?? "No phone"}</small>
        </span>
        <span className="ops-rt__money">
          <span className="num">{egp(refund.amount)}</span>
          <small>
            {refund.refund_to ? `${methodLabel(methods, refund.method)} · ${refund.refund_to}` : "No refund ID yet"}
          </small>
        </span>
        <span className="ops-rt__state">
          <span>
            {paid ? `Paid ${dayMonth(refund.paid_on!)}` : (refund.step ?? "Not read yet")}
          </span>
          <small>
            {paid
              ? refund.paid_by
                ? `By ${refund.paid_by}`
                : "By someone no longer here"
              : refund.step_at
                ? dayAndTime(refund.step_at)
                : ""}
          </small>
          {(flags.length > 0 || tags.length > 0) && (
            <span className="ops-rt__flags">
              {flags.map((flag) => (
                <span key={flag} className={flag === "details_missing" ? "ops-tag" : "ops-tag ops-rt__flag"}>
                  {REASON_WORDS[flag]}
                </span>
              ))}
              {tags.map((tag) => (
                <span key={tag} className="ops-tag">
                  {tag}
                </span>
              ))}
            </span>
          )}
        </span>
        <OpsIcon name={open ? "up" : "down"} />
      </button>
      {open && (
        <div className="ops-rt__open" id={id}>
          <Timeline refund={refund} now={now} />
          {(canEdit || paid) && (
            <div className="ops-rt__work">
              {notice && (
                <p className="notice notice--refused" role="alert">
                  {notice}
                </p>
              )}
              {paid && <Proof refund={refund} canEdit={canEdit} onDone={onChanged} />}
              {canEdit && !paid && refund.received_at === null && !payingEarly && (
                <div className="ops-kh__actions">
                  <button type="button" className="button button--row" onClick={() => setPayingEarly(true)}>
                    Paid it already? Record it
                  </button>
                </div>
              )}
              {canEdit && !paid && (refund.received_at !== null || payingEarly) && (
                // Keyed on the saved details: saving new ones beside it
                // refreshes what this form will send.
                <PayForm
                  key={`${refund.amount}|${refund.method}|${refund.refund_to}`}
                  refund={refund}
                  methods={methods}
                  onDone={() => {
                    setPayingEarly(false);
                    onChanged();
                  }}
                  onNotice={setNotice}
                />
              )}
              {canEdit &&
                (paid ? (
                  <PaidActions refund={refund} onDone={onChanged} />
                ) : (
                  <>
                    <EditForm refund={refund} methods={methods} onDone={onChanged} />
                    <RowActions refund={refund} onDone={onChanged} />
                  </>
                ))}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

// ── Finding and sorting ─────────────────────────────────────────────────────

export type SortKey = "added" | "khazenly" | "customer" | "amount" | "status";
export type Sort = { key: SortKey; dir: "asc" | "desc" };

const DEFAULT_SORT: Sort = { key: "added", dir: "desc" };

/** The columns, as the rows draw them, and how each first sorts. */
const COLUMNS: { key: Exclude<SortKey, "added">; label: string; first: Sort["dir"] }[] = [
  { key: "khazenly", label: "Khazenly order", first: "asc" },
  { key: "customer", label: "Customer", first: "asc" },
  { key: "amount", label: "Amount", first: "desc" },
  { key: "status", label: "Status", first: "desc" },
];

/** The phone's menu: every column both ways, in words. */
const SORT_CHOICES: { value: string; label: string }[] = [
  { value: "added:desc", label: "Newest added" },
  { value: "added:asc", label: "Oldest added" },
  { value: "status:desc", label: "Latest Khazenly step" },
  { value: "status:asc", label: "Oldest Khazenly step" },
  { value: "amount:desc", label: "Amount, highest first" },
  { value: "amount:asc", label: "Amount, lowest first" },
  { value: "customer:asc", label: "Customer, A to Z" },
  { value: "customer:desc", label: "Customer, Z to A" },
  { value: "khazenly:asc", label: "Khazenly number, lowest first" },
  { value: "khazenly:desc", label: "Khazenly number, highest first" },
];

function digits(value: string | null): string {
  return (value ?? "").replace(/\D/g, "");
}

/** A phone as its last ten digits: 01060910507, +201060910507 and
 *  1060910507 are one number. */
function phoneKey(value: string | null): string {
  return digits(value).slice(-10);
}

/**
 * Whether a refund matches what was typed: the customer's name, their
 * phone, the Shopify order (with or without #) or the Khazenly number, in
 * part. Spaces and case do not matter.
 */
export function matches(refund: Refund, raw: string): boolean {
  const query = raw.trim().toLowerCase();
  if (!query) return true;
  const words = query.replace(/\s+/g, " ");
  const name = (refund.customer_name ?? "").toLowerCase().replace(/\s+/g, " ");
  if (name.includes(words)) return true;
  const compact = query.replace(/[\s#]/g, "");
  if (refund.khazenly_number.toLowerCase().includes(compact)) return true;
  if ((refund.merchant_order ?? "").toLowerCase().replace("#", "").includes(compact)) return true;
  const typed = digits(query);
  // Numbers only from here: at least three digits, so "1" finds nothing.
  if (typed.length < 3 || typed.length !== compact.replace(/[-+()]/g, "").length) return false;
  if (digits(refund.order_number).includes(typed)) return true;
  const phone = phoneKey(refund.customer_phone);
  const typedPhone = typed.length >= 10 ? phoneKey(typed) : typed.replace(/^0/, "");
  return phone.length > 0 && typedPhone.length > 0 && phone.includes(typedPhone);
}

function sortValue(refund: Refund, key: SortKey): string | number | null {
  switch (key) {
    case "khazenly":
      return Number(digits(refund.khazenly_number)) || refund.khazenly_number;
    case "customer":
      return refund.customer_name?.trim().toLowerCase() || null;
    case "amount":
      return refund.amount === null ? null : Number(refund.amount);
    case "status": {
      const when = refund.paid_on ?? refund.step_at;
      return when ? new Date(when).getTime() : null;
    }
    default:
      return refund.created_at ? new Date(refund.created_at).getTime() : refund.id;
  }
}

/** Sorted by one column; a row missing that value always goes last. */
export function sortRefunds(rows: Refund[], sort: Sort): Refund[] {
  const sign = sort.dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const left = sortValue(a, sort.key);
    const right = sortValue(b, sort.key);
    if (left === null && right === null) return b.id - a.id;
    if (left === null) return 1;
    if (right === null) return -1;
    const order =
      typeof left === "number" && typeof right === "number"
        ? left - right
        : String(left).localeCompare(String(right), "en", { numeric: true });
    return order === 0 ? b.id - a.id : order * sign;
  });
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="11" cy="11" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="M16 16l4.5 4.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function FindBar({
  query,
  onQuery,
  sort,
  onSort,
  found,
  paidShown,
}: {
  query: string;
  onQuery: (value: string) => void;
  sort: Sort;
  onSort: (sort: Sort) => void;
  found: number | null;
  paidShown: number;
}) {
  return (
    <section className="panel ops-list ops-rt__find" aria-label="Find and sort refunds">
      <div className="ops-rt__search">
        <SearchIcon />
        <input
          className="input"
          type="search"
          value={query}
          placeholder="Name, phone or order number"
          aria-label="Search refunds"
          autoComplete="off"
          enterKeyHint="search"
          onChange={(event) => onQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") onQuery("");
          }}
        />
        {query && (
          <button type="button" className="ops-rt__clear" aria-label="Clear the search" onClick={() => onQuery("")}>
            ×
          </button>
        )}
      </div>
      <label className="ops-rt__sortby">
        <span>Sort by</span>
        <select
          className="input"
          value={`${sort.key}:${sort.dir}`}
          onChange={(event) => {
            const [key, dir] = event.target.value.split(":") as [SortKey, Sort["dir"]];
            onSort({ key, dir });
          }}
        >
          {SORT_CHOICES.map((choice) => (
            <option key={choice.value} value={choice.value}>
              {choice.label}
            </option>
          ))}
        </select>
      </label>
      <p className="ops-hint ops-rt__found" role="status">
        {found === null
          ? `Customer name or phone, Shopify order or Khazenly number. Searches every unpaid refund and the latest ${paidShown} paid.`
          : `${found === 0 ? "No refunds match" : found === 1 ? "1 refund matches" : `${found} refunds match`}.`}
      </p>
    </section>
  );
}

/** The columns' heads, each sorting the rows below (on a laptop; a phone
 *  sorts from the menu beside the search). */
function SortHeader({ sort, onSort, paid }: { sort: Sort; onSort: (sort: Sort) => void; paid: boolean }) {
  return (
    <div className="ops-rt__heads">
      {COLUMNS.map((column) => {
        const on = sort.key === column.key;
        const label = column.key === "status" && paid ? "Paid on" : column.label;
        const next: Sort = on
          ? { key: column.key, dir: sort.dir === "asc" ? "desc" : "asc" }
          : { key: column.key, dir: column.first };
        return (
          <button
            key={column.key}
            type="button"
            className={on ? "ops-rt__head ops-rt__head--on" : "ops-rt__head"}
            aria-label={`Sort by ${label}${on ? `, now ${sort.dir === "asc" ? "ascending" : "descending"}` : ""}`}
            aria-pressed={on}
            onClick={() => onSort(next)}
          >
            {label}
            <span aria-hidden="true" className="ops-rt__arrow">
              {on ? (sort.dir === "asc" ? "↑" : "↓") : "↕"}
            </span>
          </button>
        );
      })}
      <span aria-hidden="true" />
    </div>
  );
}

// ── The tab ─────────────────────────────────────────────────────────────────

type Folds = Record<Group, boolean>;

/** Which groups start open: the two that ask for something to be done. */
export const DEFAULT_FOLDS: Folds = { ready: true, attention: true, on_the_way: false, paid: false };
const FOLDS_KEY = "hba.ops.returns.open";

function readFolds(): Folds {
  try {
    const kept = JSON.parse(window.localStorage.getItem(FOLDS_KEY) ?? "null");
    if (kept && typeof kept === "object") {
      return Object.fromEntries(
        GROUPS.map(({ key }) => [key, typeof kept[key] === "boolean" ? kept[key] : DEFAULT_FOLDS[key]]),
      ) as Folds;
    }
  } catch {
    // A private window or blocked storage: the defaults serve.
  }
  return DEFAULT_FOLDS;
}

function keepFolds(folds: Folds): void {
  try {
    window.localStorage.setItem(FOLDS_KEY, JSON.stringify(folds));
  } catch {
    // Not kept; the page works the same.
  }
}

export function OperationsReturns({ canEdit }: { canEdit: boolean }) {
  const now = useNow();
  const { tab, failed, reload } = useOpsTab(() => api.get<ReturnsTab>("/api/order-ops/returns"));

  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>(DEFAULT_SORT);
  const [folds, setFolds] = useState<Folds>(readFolds);

  function toggle(key: Group) {
    const next = { ...folds, [key]: !folds[key] };
    setFolds(next);
    keepFolds(next);
  }

  const grouped = (key: Group) => tab?.refunds.filter((refund) => refund.group === key) ?? [];
  const searching = query.trim().length > 0;
  const found = tab?.refunds.filter((refund) => matches(refund, query)) ?? [];

  return (
    <>
      <header className="page__head">
        <div className="page__title">
          <h1>Returns</h1>
          <span className="page__subtitle">Refunds owed to customers</span>
        </div>
        {tab && (
          <p className="ops-fresh">
            <OpsIcon name="clock" />
            {tab.tracking.checked_at
              ? `Khazenly checked ${age(tab.tracking.checked_at, now)} ago · every ${tab.tracking.every_minutes} minutes`
              : `Khazenly is checked every ${tab.tracking.every_minutes} minutes`}
          </p>
        )}
      </header>

      {failed && (
        <p className="notice notice--refused" role="alert">
          Couldn't load this tab.{" "}
          <button type="button" className="ops-linkbtn" onClick={reload}>
            Try again
          </button>
        </p>
      )}

      {!tab && !failed && <p className="loading">Loading…</p>}

      {tab?.tracking.khazenly_down && (
        <div className="ops-banner ops-banner--failed" role="alert">
          <OpsIcon name="alert" />
          <div>
            Khazenly's tracking isn't answering.
            <small>
              The steps below are the last ones read. Refunds can still be added once it answers, and marked paid as
              usual.
            </small>
          </div>
        </div>
      )}

      {tab && (
        <>
          <div className="ops-tiles">
            <div className="ops-tile ops-tile--zero ops-rt__tile ops-rt__tile--money">
              <span className="ops-tile__label">Owed now</span>
              <span className="ops-tile__value num">{egp(tab.totals.owed_now)}</span>
              <span className="ops-tile__note">
                {plural(tab.totals.owed_count, "refund", "refunds")} back at Khazenly, not paid
                {tab.totals.owed_missing_amount > 0 ? ` · ${tab.totals.owed_missing_amount} without an amount` : ""}
              </span>
            </div>
            <div className="ops-tile ops-tile--zero ops-rt__tile ops-rt__tile--money">
              <span className="ops-tile__label">Refunded in {monthName(tab.totals.month)}</span>
              <span className="ops-tile__value num">{egp(tab.totals.refunded_this_month)}</span>
              <span className="ops-tile__note">{plural(tab.totals.refunded_count, "refund", "refunds")} marked paid</span>
            </div>
            <div className="ops-tile ops-tile--zero ops-rt__tile">
              <span className="ops-tile__label">On the way back</span>
              <span className="ops-tile__value num">{grouped("on_the_way").length}</span>
              <span className="ops-tile__note">Not at Khazenly yet</span>
            </div>
            <div className="ops-tile ops-tile--zero ops-rt__tile">
              <span className="ops-tile__label">Needs attention</span>
              <span className={grouped("attention").length ? "ops-tile__value num ops-rt__warn" : "ops-tile__value num"}>
                {grouped("attention").length}
              </span>
              <span className="ops-tile__note">Stuck or flagged by Khazenly</span>
            </div>
          </div>

          {canEdit && <AddRefund methods={tab.methods} onAdded={reload} />}

          <FindBar
            query={query}
            onQuery={setQuery}
            sort={sort}
            onSort={setSort}
            found={searching ? found.length : null}
            paidShown={tab.paid_shown}
          />

          {searching && found.length === 0 && (
            <p className="empty ops-list">
              No refund matches “{query.trim()}”. Search by the customer's name or phone, the Shopify order or the
              Khazenly number.
            </p>
          )}

          {GROUPS.map((group) => {
            const all = grouped(group.key);
            const rows = sortRefunds(
              all.filter((refund) => matches(refund, query)),
              sort,
            );
            // While searching, a group with nothing found steps aside.
            if (searching && rows.length === 0) return null;
            const headingId = `ops-rt-${group.key}`;
            const bodyId = `ops-rt-${group.key}-rows`;
            // A search opens every group it found something in.
            const expanded = searching || folds[group.key];
            const count = searching
              ? `${rows.length} of ${all.length}`
              : group.key === "paid" && rows.length >= tab.paid_shown
                ? `latest ${rows.length}`
                : rows.length;
            return (
              <section key={group.key} className="panel ops-list" aria-labelledby={headingId}>
                <div className="panel__head ops-kh__head">
                  <h2 className="panel__title" id={headingId}>
                    <button
                      type="button"
                      className="ops-rt__fold"
                      aria-expanded={expanded}
                      aria-controls={expanded ? bodyId : undefined}
                      disabled={searching}
                      onClick={() => toggle(group.key)}
                    >
                      <span>
                        {group.title} · {count}
                      </span>
                      <OpsIcon name={expanded ? "up" : "down"} />
                    </button>
                  </h2>
                  {expanded && <p className="ops-hint">{group.hint}</p>}
                </div>
                {expanded && (
                  <div id={bodyId}>
                    {rows.length > 1 && <SortHeader sort={sort} onSort={setSort} paid={group.key === "paid"} />}
                    {rows.length ? (
                      <ul className="ops-rt__rows">
                        {rows.map((refund) => (
                          <RefundRow
                            key={refund.id}
                            refund={refund}
                            methods={tab.methods}
                            canEdit={canEdit}
                            now={now}
                            onChanged={reload}
                          />
                        ))}
                      </ul>
                    ) : (
                      <p className="empty">{group.empty}</p>
                    )}
                  </div>
                )}
              </section>
            );
          })}
        </>
      )}
    </>
  );
}
