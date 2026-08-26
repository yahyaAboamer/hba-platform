import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Money } from "../components/Money";
import { api } from "../lib/api";
import { egpPlain, formatEgp, formatMonth, parseEgp } from "../lib/money";
import type { Balance } from "./Payments";
import { STATE_LABEL } from "./Payments";
import "./Payments.css";

type Revealed = {
  method: "instapay" | "bank" | "wallet";
  instapay_address_url?: string | null;
  instapay_phone?: string | null;
  bank_name?: string | null;
  bank_account_holder?: string | null;
  bank_account_number?: string | null;
  wallet_phone?: string | null;
};

type Outstanding = { affiliates: Balance[] };

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
  const [note, setNote] = useState("");
  const [reference, setReference] = useState("");
  const [proof, setProof] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

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
    } catch {
      // Clipboard access can be refused outright. The number is on screen
      // either way, which is the thing that actually matters.
      setCopied(null);
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
      let proofId: string | undefined;
      if (proof) {
        const stored = await api.upload<{ proof_file_id: string }>(
          `/api/affiliates/${affiliateId}/proof`,
          proof,
        );
        proofId = stored.proof_file_id;
      }

      await api.post("/api/payments", {
        affiliate_id: Number(affiliateId),
        amount_piastres: piastres,
        allocations:
          balance.payroll_snapshot_id === undefined
            ? []
            : [
                {
                  payroll_snapshot_id: balance.payroll_snapshot_id,
                  piastres,
                },
              ],
        reference: reference.trim() || null,
        note: note.trim() || null,
        proof_file_id: proofId ?? null,
      });
      navigate("/payments");
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

  return (
    <>
      {head}

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
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
                label="Already sent"
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

        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Where to send it</h2>
          </div>

          {revealed === null ? (
            <>
              <p className="pay__lead">
                Her details are shortened everywhere else on purpose. Showing
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
            <>
              <dl className="detail__list">
                <div className="detail__row">
                  <dt className="detail__label">Method</dt>
                  <dd className="detail__value">
                    {METHOD_LABEL[revealed.method] ?? revealed.method}
                  </dd>
                </div>
                {revealed.bank_name && (
                  <Detail label="Bank" value={revealed.bank_name} />
                )}
                {revealed.bank_account_holder && (
                  <Detail
                    label="Account holder"
                    value={revealed.bank_account_holder}
                  />
                )}
                {revealed.bank_account_number && (
                  <Copyable
                    label="Account number"
                    value={revealed.bank_account_number}
                    copied={copied}
                    onCopy={copy}
                  />
                )}
                {revealed.wallet_phone && (
                  <Copyable
                    label="Wallet number"
                    value={revealed.wallet_phone}
                    copied={copied}
                    onCopy={copy}
                  />
                )}
                {revealed.instapay_phone && (
                  <Copyable
                    label="InstaPay number"
                    value={revealed.instapay_phone}
                    copied={copied}
                    onCopy={copy}
                  />
                )}
              </dl>

              {/*
               * ADR 0028. The link opens the app with her address filled in;
               * the number below it is what you type when it does not open —
               * which on a laptop is always, because there is no app to open.
               */}
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

              <p className="pay__lead">
                Sending the money happens in your bank or in InstaPay, never
                here. Come back and record it once it has gone.
              </p>
            </>
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
            <span className="detail__note" id="amount-help">
              {piastres === null
                ? "Type a figure, for example 5512.35"
                : differs
                  ? `${formatEgp(piastres)} — ${formatEgp(Math.abs(piastres - owed))} ${piastres > owed ? "more than" : "less than"} what is owed`
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
              onChange={(event) => setProof(event.target.files?.[0] ?? null)}
            />
            <span className="detail__note">
              She sees this, which is what stops the “did you send it?”
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
