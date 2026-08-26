import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Money } from "../components/Money";
import { api } from "../lib/api";
import { egpPlain, formatEgp, formatMonth, monthAdd, parseEgp } from "../lib/money";
import type { Balance } from "./Payments";
import "./Payments.css";

type Outstanding = { affiliates: Balance[] };

type Kind = "credit" | "writeoff";

/**
 * Settling an overpayment. §11.5, and Pattern C (§12.2).
 *
 * Reaching this page means she has been paid more than the month agreed —
 * usually because it was reopened to a lower figure after the money had gone,
 * sometimes a rounding split or a fee.
 *
 * **The platform reports the overpayment and refuses to decide what to do
 * about it.** Carrying it into next month or absorbing it is a judgement about
 * a person HBA knows and the platform does not, so both options are offered
 * plainly and neither is preselected.
 */
export function PaymentReconcile() {
  const { month = "", affiliateId = "" } = useParams();
  const navigate = useNavigate();

  const [balance, setBalance] = useState<Balance | null>(null);
  const [kind, setKind] = useState<Kind | null>(null);
  const [amount, setAmount] = useState("");
  const [destination, setDestination] = useState(monthAdd(month, 1));
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
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
        // The overpayment is the balance gone negative.
        if (row) setAmount(egpPlain(Math.abs(Math.min(0, row.balance_piastres))));
      })
      .catch((caught) => setError(caught.message));
  }, [month, affiliateId]);

  const piastres = parseEgp(amount);
  const over = Math.abs(Math.min(0, balance?.balance_piastres ?? 0));

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (kind === null || piastres === null || piastres <= 0) return;
    setWorking(true);
    setError(null);
    try {
      await api.post("/api/adjustments", {
        affiliate_id: Number(affiliateId),
        type: kind,
        source_month: month,
        amount_piastres: piastres,
        reason: reason.trim(),
        destination_month: kind === "credit" ? destination : null,
      });
      navigate("/payments");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not record it.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <Link to="/payments" className="detail__back">
            Payments
          </Link>
          <h1>
            Settle the difference — {balance?.name ?? "…"}, {formatMonth(month)}
          </h1>
        </div>
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {balance === null && !error && <p className="empty">Loading…</p>}

      {balance && over === 0 && (
        <p className="empty">
          Nothing to settle — {balance.name} has not been overpaid for{" "}
          {formatMonth(month)}.
        </p>
      )}

      {balance && over > 0 && (
        <form onSubmit={submit}>
          <section className="panel approve__summary">
            <h2 className="panel__title">What happened</h2>
            <p className="approve__lead">
              {balance.name} has been sent{" "}
              <Money piastres={over} kind="agreed" tone="owed" /> more than{" "}
              {formatMonth(month)} agreed. The money is gone, so the only
              question is where it counts.
            </p>
            <p className="approve__lead">
              Either answer is recorded and both are visible to her. Nothing
              here takes money back.
            </p>
          </section>

          <fieldset className="pay__choice">
            <legend className="field__label">What should happen to it?</legend>

            <label
              className={
                kind === "credit" ? "pay__option pay__option--on" : "pay__option"
              }
            >
              <input
                type="radio"
                name="kind"
                checked={kind === "credit"}
                onChange={() => setKind("credit")}
              />
              <span className="pay__option-body">
                <strong>Count it against a later month</strong>
                <span className="detail__note">
                  She keeps it, and next month owes her that much less. Use this
                  when she is still on the programme.
                </span>
              </span>
            </label>

            <label
              className={
                kind === "writeoff"
                  ? "pay__option pay__option--on"
                  : "pay__option"
              }
            >
              <input
                type="radio"
                name="kind"
                checked={kind === "writeoff"}
                onChange={() => setKind("writeoff")}
              />
              <span className="pay__option-body">
                <strong>Absorb it</strong>
                <span className="detail__note">
                  HBA takes the loss and nothing carries forward. Use this for
                  small differences, or when she is leaving.
                </span>
              </span>
            </label>
          </fieldset>

          {kind === "credit" && (
            <label className="field pay__field">
              <span className="field__label">Which month should it count against?</span>
              <input
                className="input code"
                value={destination}
                onChange={(event) => setDestination(event.target.value)}
                placeholder="2026-10"
              />
              <span className="detail__note">
                {formatMonth(destination)} will owe{" "}
                {piastres === null ? "that much" : formatEgp(piastres)} less.
              </span>
            </label>
          )}

          <label className="field pay__field">
            <span className="field__label">How much?</span>
            <input
              className="input"
              inputMode="decimal"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
            <span className="detail__note">
              {piastres === null
                ? "Type a figure, for example 120.00"
                : piastres > over
                  ? `More than the ${formatEgp(over)} she was overpaid.`
                  : `${formatEgp(piastres)} of the ${formatEgp(over)} overpaid.`}
            </span>
          </label>

          <label className="field pay__field">
            <span className="field__label">Why?</span>
            <textarea
              className="input reopen__textarea"
              rows={2}
              maxLength={500}
              required
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="September was reopened lower after a parcel came back refused."
            />
            <span className="detail__note">
              Kept in the record, and shown to her — a credit she cannot see is
              a credit she cannot check.
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
                working ||
                kind === null ||
                piastres === null ||
                piastres <= 0 ||
                reason.trim() === ""
              }
            >
              {working
                ? "Recording…"
                : kind === null
                  ? "Choose what happens to it"
                  : kind === "credit"
                    ? `Count ${piastres === null ? "it" : formatEgp(piastres)} against ${formatMonth(destination)}`
                    : `Absorb ${piastres === null ? "it" : formatEgp(piastres)}`}
            </button>
          </div>
        </form>
      )}
    </>
  );
}
