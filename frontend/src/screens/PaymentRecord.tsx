import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Money } from "../components/Money";
import { api } from "../lib/api";
import { PAYOUT_FIELD_LABEL } from "../lib/payouts";
import { egpPlain, formatEgp, formatMonth, parseEgp } from "../lib/money";
import type { Balance } from "./Payments";
import { paymentRowPresentation, STATE_LABEL } from "./Payments";
import "./Payments.css";

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
export function PaymentRecord() {
  const { month = "", affiliateId = "" } = useParams();
  const navigate = useNavigate();

  const [balance, setBalance] = useState<Balance | null>(null);
  const [revealed, setRevealed] = useState<Revealed | null>(null);
  const [revealing, setRevealing] = useState(false);
  const [amount, setAmount] = useState("");
  const [transferDate, setTransferDate] = useState(cairoToday);
  const [note, setNote] = useState("");
  const [reference, setReference] = useState("");
  const [proof, setProof] = useState<File | null>(null);
  const [proofFileId, setProofFileId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [copyMessage, setCopyMessage] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [operationKey] = useState(() => crypto.randomUUID());

  useEffect(() => {
    setError(null);
    api
      .get<Outstanding>(`/api/payments/${month}`)
      .then((body) => {
        const row = body.affiliates.find(
          (candidate) => String(candidate.affiliate_id) === affiliateId,
        );
        setBalance(row ?? null);
        // §14. Pre-filled with what is owed, and editable, because a partial
        // payment, a transfer limit, a fee and a mistake all have to be
        // recordable as what actually happened.
        if (row) setAmount(egpPlain(row.balance_piastres));
      })
      .catch((caught) => setError(caught.message));
  }, [month, affiliateId]);

  async function reveal() {
    setRevealing(true);
    setError(null);
    try {
      setRevealed(
        await api.post<Revealed>(
          `/api/affiliates/${affiliateId}/payout-destination/reveal`,
        ),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not read it.");
    } finally {
      setRevealing(false);
    }
  }

  async function copy(label: string, value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(label);
      setCopyMessage(`${label} copied.`);
    } catch {
      // Clipboard access can be refused outright. The number is on screen
      // either way, which is the thing that actually matters.
      setCopied(null);
      setCopyMessage(
        `Could not copy ${label.toLocaleLowerCase()}. Select it and copy it instead.`,
      );
    }
  }

  const piastres = parseEgp(amount);
  const owed = balance?.balance_piastres ?? 0;
  const differs = piastres !== null && piastres !== owed;
  const noteMissing = differs && note.trim() === "";

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
      // The append-only history is the receipt. Landing there proves what was
      // recorded and avoids a green toast standing in for persisted evidence.
      navigate(`/affiliates/${affiliateId}/payments`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not record it.");
    } finally {
      setWorking(false);
    }
  }

  const head = (
    <div className="page__head">
      <div className="page__title">
        <Link to="/payments" className="detail__back">
          Payments
        </Link>
        <h1>
          Pay {balance?.name ?? "…"} — {formatMonth(month)}
        </h1>
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

  if (balance.balance_piastres <= 0) {
    const view = paymentRowPresentation(balance);
    return (
      <>
        {head}
        <section className="panel pay__nothing-due">
          <h2 className="panel__title">{view.label}</h2>
          <p className="pay__lead">
            {view.explanation ?? "There is no remaining transfer to record."}
          </p>
          <Link
            className="button"
            to={`/affiliates/${affiliateId}/payments`}
          >
            Open genuine payment history
          </Link>
        </section>
      </>
    );
  }

  return (
    <>
      {head}

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {/*
       * §6.4.5, and the reason it is here rather than buried in the panel
       * below: this is the moment a redirected payout would actually cost
       * money, and the person about to send it is the only one who can tell a
       * model who switched banks from an account somebody else is now holding.
       *
       * It does not block. A destination changing shortly before payday is
       * overwhelmingly the former, and refusing to pay them would be the wrong
       * default by a wide margin.
       */}
      {balance.destination_changed_at && (
        <p className="notice notice--refused pay__changed" role="alert">
          Where {balance.name} is paid changed{" "}
          <strong>{describeWhen(balance.destination_changed_at)}</strong>. If
          you were not expecting that, check with them before sending anything.
        </p>
      )}

      <div className="pay__grid">
        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">What is owed</h2>
            <span className="page__subtitle">
              {STATE_LABEL[balance.state]}
              {balance.version !== undefined && ` · v${balance.version}`}
            </span>
          </div>
          {/*
           * The parts as well as the total. The first question about any
           * outstanding figure is what makes it up, and a balance nobody can
           * take apart is a balance nobody can argue with.
           */}
          <dl className="detail__list">
            <Line label="Agreed" piastres={balance.obligation_piastres} />
            {balance.credited_piastres > 0 && (
              <Line
                label="Carried in from another month"
                piastres={balance.credited_piastres}
              />
            )}
            {balance.paid_piastres > 0 && (
              <Line
                label={
                  (balance.paid_earlier_versions_piastres ?? 0) > 0
                    ? "Already sent, across versions"
                    : "Already sent"
                }
                piastres={-balance.paid_piastres}
              />
            )}
            {balance.adjusted_piastres > 0 && (
              <Line
                label="Credited out or written off"
                piastres={-balance.adjusted_piastres}
              />
            )}
            <div className="detail__row pay__balance">
              <dt className="detail__label">Still owed</dt>
              <dd className="detail__value">
                <Money
                  piastres={balance.balance_piastres}
                  kind="agreed"
                  tone={balance.balance_piastres > 0 ? "owed" : "settled"}
                />
              </dd>
            </div>
          </dl>
        </section>

        {/*
         * Only once a month has been agreed more than once. On an ordinary
         * month there is nothing to reconcile and this would be a panel
         * explaining that nothing happened.
         *
         * It exists because the figure alone could not answer the question
         * somebody actually has on seeing "v2": is this the whole amount, or
         * what is left? Until the balance was corrected it was neither - the
         * screen offered the full new figure to a model who had already been
         * paid most of it.
         */}
        {(balance.versions?.length ?? 0) > 1 && (
          <section className="panel pay__versions">
            <div className="panel__head">
              <h2 className="panel__title">How this month changed</h2>
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>Version</th>
                  <th className="numeric">Agreed</th>
                  <th className="numeric">Paid against it</th>
                </tr>
              </thead>
              <tbody>
                {balance.versions!.map((entry) => (
                  <tr
                    key={entry.version}
                    className={entry.is_current ? undefined : "pay__version--old"}
                  >
                    <td>
                      {entry.version}
                      {!entry.is_current && (
                        <span className="detail__note"> superseded</span>
                      )}
                    </td>
                    <td className="numeric">
                      <Money
                        piastres={entry.obligation_piastres}
                        kind={entry.is_current ? "agreed" : "blocked"}
                      />
                    </td>
                    <td className="numeric">
                      <Money
                        piastres={entry.paid_piastres}
                        kind={entry.is_current ? "agreed" : "blocked"}
                        tone={entry.paid_piastres > 0 ? "settled" : "neutral"}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="pay__versions-note">
              Money stays attached to the version it settled. What is still
              owed is the difference between the current figure and everything
              already sent for this month.
            </p>
          </section>
        )}

        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Where to send it</h2>
          </div>

          {revealed === null ? (
            <>
              <p className="pay__lead">
                These details are shortened everywhere else on purpose. Showing
                them is recorded — who looked, and when.
              </p>
              <button
                type="button"
                className="button"
                onClick={reveal}
                disabled={revealing}
              >
                {revealing ? "Reading…" : "Show where to send it"}
              </button>
            </>
          ) : (
            <PaymentDestination
              revealed={revealed}
              copied={copied}
              copyMessage={copyMessage}
              onCopy={copy}
            />
          )}
        </section>
      </div>

      <form onSubmit={submit} className="pay__form">
        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Record what you sent</h2>
          </div>

          <label className="field pay__field">
            <span className="field__label">Amount sent</span>
            <input
              className="input"
              inputMode="decimal"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              aria-describedby="amount-help"
            />
            {/*
             * **Louder when it is more, quiet when it is less.**
             *
             * Both were the same grey note, and paying under is ordinary -
             * a part payment, recorded on purpose. Paying *over* is the one
             * that has to be reconciled afterwards, and on staging somebody
             * typed the full agreed figure over a correctly pre-filled
             * remainder and sent E£760 twice. The note said so. Nobody read
             * a grey line.
             */}
            <span
              className={
                piastres !== null && piastres > owed
                  ? "detail__note pay__over"
                  : "detail__note"
              }
              id="amount-help"
            >
              {piastres === null
                ? "Type a figure, for example 5512.35"
                : piastres > owed
                  ? `${formatEgp(piastres)} — ${formatEgp(piastres - owed)} more than is owed. This month will be overpaid, and you will have to credit or write off the difference.`
                  : differs
                    ? `${formatEgp(piastres)} — ${formatEgp(owed - piastres)} less than what is owed`
                    : `${formatEgp(piastres)} — exactly what is owed`}
            </span>
          </label>

          {/*
           * §14. The note is what separates a deliberate partial payment from a
           * typo, and only the person recording it knows which. The server
           * refuses the difference without one; asking here means the reason is
           * written while it is still in mind.
           */}
          {differs && (
            <label className="field pay__field">
              <span className="field__label">
                Why is it different from what is owed?
              </span>
              <textarea
                className="input reopen__textarea"
                rows={2}
                maxLength={500}
                required
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder="InstaPay would not send the whole amount in one transfer."
              />
            </label>
          )}

          <label className="field pay__field">
            <span className="field__label">Transfer date</span>
            <input
              className="input"
              type="date"
              required
              value={transferDate}
              onChange={(event) => setTransferDate(event.target.value)}
            />
            <span className="detail__note">
              The day the money moved, which may differ from the day you record it.
            </span>
          </label>

          <label className="field pay__field">
            <span className="field__label">Reference (optional)</span>
            <input
              className="input"
              maxLength={120}
              value={reference}
              onChange={(event) => setReference(event.target.value)}
              placeholder="The transaction number from the confirmation"
            />
          </label>

          <label className="field pay__field">
            <span className="field__label">Confirmation screenshot</span>
            <input
              className="input"
              type="file"
              accept="image/*"
              onChange={(event) => {
                setProof(event.target.files?.[0] ?? null);
                setProofFileId(null);
              }}
            />
            <span className="detail__note">
              {balance.name} sees this, which is what stops the “did you send it?”
              messages. Location data is stripped and the image is compressed
              before it is stored.
            </span>
          </label>

          <div className="payroll__actions">
            <button
              type="button"
              className="button"
              onClick={() => navigate("/payments")}
              disabled={working}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="button button--primary"
              disabled={
                working || piastres === null || piastres <= 0 || noteMissing
              }
            >
              {working
                ? "Recording…"
                : piastres === null || piastres <= 0
                  ? "Enter an amount"
                  : noteMissing
                    ? "Say why it differs"
                    : `Record ${formatEgp(piastres)} as sent`}
            </button>
          </div>
        </section>
      </form>
    </>
  );
}

/**
 * The authorized destination values the payer must act on.
 *
 * Kept as one method-aware component so InstaPay, bank/card and every wallet
 * provider cannot drift into three partial versions. The exact submitted URL
 * is both visible/copyable and the Open target; opening it is deliberately
 * followed by no success state because leaving HBA never proves money moved.
 */
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

function Line({ label, piastres }: { label: string; piastres: number }) {
  return (
    <div className="detail__row">
      <dt className="detail__label">{label}</dt>
      <dd className="detail__value">
        <Money piastres={piastres} kind="agreed" />
      </dd>
    </div>
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
