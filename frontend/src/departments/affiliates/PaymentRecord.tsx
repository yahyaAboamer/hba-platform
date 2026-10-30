import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";

import { Money } from "../components/Money";
import { api } from "../lib/api";
import {
  NO_DESTINATION_RECORDED,
  PAYOUT_FIELD_LABEL,
  describeDestination,
} from "../lib/payouts";
import { egpPlain, formatMonth, parseEgp } from "../lib/money";
import type { Balance } from "./Payments";
import "./Payments.css";
import "./PaymentDetail.css";

export type Revealed = {
  method: "instapay" | "bank" | "wallet";
  instapay_address_url?: string | null;
  instapay_phone?: string | null;
  bank_name?: string | null;
  bank_account_holder?: string | null;
  bank_account_number?: string | null;
  wallet_provider?: string | null;
  wallet_phone?: string | null;
};

type Outstanding = { affiliates: Balance[] };

type PaymentDraft = {
  operationKey: string;
  affiliateId: number;
  amountPiastres: number;
  payrollSnapshotId?: number;
  transferDate: string;
  reference: string;
  note: string;
  proofFileId?: string;
};

/**
 * The exact external event handed to the append-only payment ledger.
 *
 * Noon UTC preserves the date the payer selected in every timezone. The
 * operation key belongs to the form, not one network attempt, so a timeout
 * can replay the same act without creating another transfer or allocation.
 */
export function paymentRequest(draft: PaymentDraft) {
  return {
    operation_key: draft.operationKey,
    affiliate_id: draft.affiliateId,
    amount_piastres: draft.amountPiastres,
    allocations:
      draft.payrollSnapshotId === undefined
        ? []
        : [
            {
              payroll_snapshot_id: draft.payrollSnapshotId,
              piastres: draft.amountPiastres,
            },
          ],
    occurred_at: `${draft.transferDate}T12:00:00Z`,
    reference: draft.reference.trim() || null,
    note: draft.note.trim() || null,
    proof_file_id: draft.proofFileId ?? null,
  };
}

function cairoToday(): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Africa/Cairo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}`;
}

/** "2 days ago", in the words §6.4.5 uses. */
function describeWhen(iso: string): string {
  const days = Math.floor(
    (Date.now() - new Date(iso).getTime()) / (1000 * 60 * 60 * 24),
  );
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

const METHOD_LABEL: Record<string, string> = {
  instapay: "InstaPay",
  bank: "Bank transfer",
  wallet: "Mobile wallet",
};

/**
 * Recording a payment. Pattern C (§12.2) — its own page, per model.
 *
 * **Nothing here sends money.** §14's first line, and it governs the whole
 * screen: the platform must never record a payment that may not have happened.
 * So the order is fixed — see where the money goes, send it yourself, then
 * come back and record what you sent with the screenshot that proves it.
 *
 * The proof is uploaded *before* the payment rather than attached after,
 * because `payment_transaction` is append-only. Attaching later would mean
 * updating a row the database refuses, and carving out one column is how a
 * table stops being append-only in practice while still claiming to be.
 */
/**
 * *Record payment* — `vRecord` in the approved export.
 *
 * What is outstanding, then one column of fields: the amount, the date, the
 * destination used, a reference and the receipt, with *Record payment* and
 * *Cancel* under them. It returns to the month's payment view, where the new
 * transfer appears under *Transfers*.
 *
 * Where to send the money is no longer on this page. The export puts it on
 * the payment view beside the approval, which is where somebody reads it
 * before they open their banking app; this page is for afterwards.
 *
 * Kept from before, because each of them is a safeguard rather than a
 * layout: one operation key for every retry of the same transfer, the proof
 * uploaded before the ledger row so a failed record does not create a second
 * image, a written reason whenever the amount differs from what is
 * outstanding, and the warning when her destination changed recently.
 */
export function PaymentRecord() {
  const { month = "", affiliateId = "" } = useParams();
  const navigate = useNavigate();

  const [balance, setBalance] = useState<Balance | null>(null);
  const [amount, setAmount] = useState("");
  const [transferDate, setTransferDate] = useState(cairoToday);
  const [note, setNote] = useState("");
  const [reference, setReference] = useState("");
  const [proof, setProof] = useState<File | null>(null);
  const [proofFileId, setProofFileId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [operationKey] = useState(() => crypto.randomUUID());
  const back = `/payments/${month}/${affiliateId}`;

  useEffect(() => {
    setError(null);
    api
      .get<Outstanding>(`/api/payments/${month}`)
      .then((body) => {
        const row = body.affiliates.find(
          (candidate) => String(candidate.affiliate_id) === affiliateId,
        );
        setBalance(row ?? null);
        // §14. Pre-filled with what is outstanding, and editable, because a
        // partial payment, a transfer limit, a fee and a mistake all have to
        // be recordable as what actually happened.
        if (row) setAmount(egpPlain(row.balance_piastres));
      })
      .catch((caught) => setError(caught.message));
  }, [month, affiliateId]);

  const piastres = parseEgp(amount);
  const owed = balance?.balance_piastres ?? 0;
  const differs = piastres !== null && piastres !== owed;
  const noteMissing = differs && note.trim() === "";
  const over = piastres !== null && piastres > owed;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (piastres === null || piastres <= 0 || balance === null) return;
    setWorking(true);
    setError(null);
    try {
      // Proof first: the payment row cannot be updated once written.
      let proofId = proofFileId ?? undefined;
      if (proof && !proofId) {
        const stored = await api.upload<{ proof_file_id: string }>(
          `/api/affiliates/${affiliateId}/proof`,
          proof,
        );
        proofId = stored.proof_file_id;
        // Keep the successful upload across a failed record request. Retrying
        // the form should retry the ledger write, not create another proof.
        setProofFileId(proofId);
      }

      await api.post(
        "/api/payments",
        paymentRequest({
          operationKey,
          affiliateId: Number(affiliateId),
          amountPiastres: piastres,
          payrollSnapshotId: balance.payroll_snapshot_id,
          transferDate,
          reference,
          note,
          proofFileId: proofId,
        }),
      );
      navigate(back);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not record it.");
    } finally {
      setWorking(false);
    }
  }

  const head = (
    <div className="page__head">
      <Link className="button pay__back" to={back}>
        ← {balance?.name ?? "Payment"}
      </Link>
      <div className="page__title">
        <h1>Record payment</h1>
        {/* The export's subtitle: `{name} · {month}` (Admin line 2365). */}
        <span className="page__subtitle">
          {balance?.name ? `${balance.name} · ${formatMonth(month)}` : formatMonth(month)}
        </span>
      </div>
    </div>
  );

  if (balance === null) {
    return (
      <>
        {head}
        {error ? (
          <p className="notice notice--refused" role="alert">
            {error}
          </p>
        ) : (
          <p className="empty">Loading…</p>
        )}
      </>
    );
  }

  // Nothing outstanding: there is no transfer to record, and the payment view
  // says why.
  if (balance.balance_piastres <= 0) return <Navigate to={back} replace />;

  return (
    <>
      {head}
      <form className="pay-record" onSubmit={submit}>
        <p className="pay-record__due">
          <Money piastres={owed} kind="agreed" /> outstanding for {formatMonth(month)}
        </p>

        {balance.destination_changed_at && (
          <p className="pay-record__warn" role="alert">
            Where {balance.name} is paid changed{" "}
            <strong>{describeWhen(balance.destination_changed_at)}</strong>. If you
            were not expecting that, check with them before sending anything.
          </p>
        )}

        <label className="pay-record__field">
          <span>Amount transferred, EGP</span>
          <input
            className="input pay-record__input"
            inputMode="decimal"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
        </label>

        <label className="pay-record__field">
          <span>Transfer date</span>
          <input
            className="input pay-record__input"
            type="date"
            required
            value={transferDate}
            onChange={(event) => setTransferDate(event.target.value)}
          />
        </label>

        <label className="pay-record__field">
          <span>Destination used</span>
          <select className="input pay-record__input" value="current" disabled>
            {/* *No destination recorded* is what the admin says; *Nothing on
             *  file yet* is what the portal says to the model herself. This
             *  is an admin screen and it was borrowing her sentence. */}
            <option value="current">
              {balance.destination
                ? describeDestination(balance.destination)
                : NO_DESTINATION_RECORDED}
            </option>
          </select>
        </label>

        <label className="pay-record__field">
          <span>Reference</span>
          <input
            className="input pay-record__input"
            maxLength={120}
            value={reference}
            onChange={(event) => setReference(event.target.value)}
            placeholder="From the transfer confirmation"
          />
        </label>

        <div className="pay-record__field">
          <span>Receipt</span>
          <label className={proof ? "pay-record__drop pay-record__drop--on" : "pay-record__drop"}>
            <input
              type="file"
              accept="image/*"
              className="pay-record__file"
              onChange={(event) => {
                setProof(event.target.files?.[0] ?? null);
                setProofFileId(null);
              }}
            />
            {proof
              ? `${proof.name} attached · choose another to replace it`
              : "Attach the transfer receipt"}
          </label>
        </div>

        {differs && (
          <label className="pay-record__field">
            <span>Why is it different from what is outstanding?</span>
            <textarea
              className="input pay-record__input"
              rows={2}
              maxLength={500}
              required
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="InstaPay would not send the whole amount in one transfer."
            />
          </label>
        )}

        {amount.trim() !== "" && (piastres === null || piastres <= 0) && (
          <p className="pay-record__error" role="alert">
            Enter the amount that was actually transferred.
          </p>
        )}
        {over && (
          <p className="pay-record__warn">
            That is more than the outstanding <Money piastres={owed} kind="agreed" />.
            It will be recorded as transferred and the difference stays visible on
            the payment.
          </p>
        )}
        {error && (
          <p className="pay-record__error" role="alert">
            {error}
          </p>
        )}

        <div className="pay-record__acts">
          <button
            type="submit"
            className="button button--primary pay-record__big"
            disabled={working || piastres === null || piastres <= 0 || noteMissing}
          >
            {working ? "Recording…" : "Record payment"}
          </button>
          <Link className="button pay-record__big" to={back}>
            Cancel
          </Link>
        </div>

        <p className="pay-record__note">
          Saving records a transfer that finance already made outside this
          dashboard.
        </p>
      </form>
    </>
  );
}

export function PaymentDestination({
  revealed,
  copied,
  copyMessage,
  onCopy,
}: {
  revealed: Revealed;
  copied: string | null;
  copyMessage: string | null;
  onCopy: (label: string, value: string) => void;
}) {
  return (
    <>
      <dl className="detail__list">
        <div className="detail__row">
          <dt className="detail__label">Method</dt>
          <dd className="detail__value">
            {METHOD_LABEL[revealed.method] ?? revealed.method}
          </dd>
        </div>
        {revealed.bank_name && (
          <Detail
            label="Bank"
            value={revealed.bank_name}
          />
        )}
        {revealed.bank_account_holder && (
          <Detail
            label={PAYOUT_FIELD_LABEL.bank_account_holder}
            value={revealed.bank_account_holder}
          />
        )}
        {revealed.bank_account_number && (
          /* **This is the screen the digits are copied from**, so of
             everywhere the label mattered it mattered most here. D06: it is
             the number on the front of her card. Calling it an account number
             to the one person about to paste it into a banking app was the
             whole risk. */
          <Copyable
            label={PAYOUT_FIELD_LABEL.bank_account_number}
            value={revealed.bank_account_number}
            copied={copied}
            onCopy={onCopy}
          />
        )}
        {revealed.wallet_provider && (
          <Detail
            label="Wallet provider"
            value={revealed.wallet_provider}
          />
        )}
        {revealed.wallet_phone && (
          <Copyable
            label="Wallet number"
            value={revealed.wallet_phone}
            copied={copied}
            onCopy={onCopy}
          />
        )}
        {revealed.instapay_address_url && (
          <Copyable
            label="InstaPay payment address"
            value={revealed.instapay_address_url}
            copied={copied}
            onCopy={onCopy}
          />
        )}
        {revealed.instapay_phone && (
          <Copyable
            label="InstaPay number"
            value={revealed.instapay_phone}
            copied={copied}
            onCopy={onCopy}
          />
        )}
      </dl>

      {revealed.method === "instapay" && revealed.instapay_address_url && (
        <a
          className="button button--primary pay__instapay"
          href={revealed.instapay_address_url}
          target="_blank"
          rel="noreferrer noopener"
        >
          Open InstaPay
        </a>
      )}

      {copyMessage && (
        <p
          className="pay__copy-message"
          role={copied ? "status" : "alert"}
        >
          {copyMessage}
        </p>
      )}

      <p className="pay__lead">
        Sending the money happens in your bank or in InstaPay, never here. Come
        back and record it once it has gone.
      </p>
    </>
  );
}


function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail__row">
      <dt className="detail__label">{label}</dt>
      <dd className="detail__value">{value}</dd>
    </div>
  );
}

function Copyable({
  label,
  value,
  copied,
  onCopy,
}: {
  label: string;
  value: string;
  copied: string | null;
  onCopy: (label: string, value: string) => void;
}) {
  return (
    <div className="detail__row">
      <dt className="detail__label">{label}</dt>
      <dd className="detail__value pay__copyable">
        <span className="code">{value}</span>
        <button
          type="button"
          className="pay__copy"
          onClick={() => onCopy(label, value)}
        >
          {copied === label ? "Copied" : "Copy"}
        </button>
      </dd>
    </div>
  );
}
