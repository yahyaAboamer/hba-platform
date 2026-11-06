import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Money } from "../../components/Money";
import { api } from "../../lib/api";
import { egpPlain, formatEgp, formatMonth, monthAdd, parseEgp } from "../../lib/money";
import type { Balance } from "./Payments";
import "./Payments.css";

type Outstanding = { affiliates: Balance[] };

type Kind = "credit" | "writeoff";

/**
 * Settling an overpayment. §11.5, and Pattern C (§12.2).
 *
 * Reaching this page means they have been paid more than the month agreed —
 * usually a rounding split or a fee, or a month reopened before 05B retired
 * reopening. **An agreed month is no longer unmade**: what changes after it is
 * recorded against it as a correction (05C), and this screen settles the
 * difference wherever it came from.
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
  const back = `/affiliates/payments/${month}/${affiliateId}`;
  const first = (balance?.name ?? "").split(" ")[0];

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
      // Back to the month it settles, where the result shows (F-S1).
      navigate(back);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not record it.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <>
      {/* The same head as every other Payments page: back to the month,
       *  the act as the title, who and when under it (F-S1). */}
      <div className="page__head">
        <Link className="button pay__back" to={back}>
          ← {balance?.name ?? "Payment"}
        </Link>
        <div className="page__title">
          <h1>Settle the difference</h1>
          <span className="page__subtitle">
            {balance?.name ? `${balance.name} · ${formatMonth(month)}` : formatMonth(month)}
          </span>
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
              {balance.name} was sent{" "}
              <Money piastres={over} kind="agreed" tone="owed" /> more than{" "}
              {formatMonth(month)} was approved at. This doesn’t take money
              back. It decides where the difference counts.
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
                {/* The same two words as the correction screen, which
                 *  makes the same decision (F-S4). */}
                <strong>Take it off a later payment</strong>
                <span className="detail__note">
                  A later month pays that much less. Best while {first} still
                  works with HBA.
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
                <strong>HBA absorbs it</strong>
                <span className="detail__note">
                  Nothing carries forward. Best for small amounts, or if {first}
                  is leaving.
                </span>
              </span>
            </label>
          </fieldset>

          {kind === "credit" && (
            <label className="field pay__field">
              <span className="field__label">Which month should it come off?</span>
              {/* A month picker, as on the correction screen, instead of
               *  typing `2026-11` by hand (F-S2). */}
              <input
                className="input"
                type="month"
                min={monthAdd(month, 1)}
                value={destination}
                onChange={(event) => setDestination(event.target.value)}
              />
              <span className="detail__note">
                {formatMonth(destination)} will pay{" "}
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
                  ? `More than the ${formatEgp(over)} overpaid.`
                  : `Up to ${formatEgp(over)}.`}
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
              placeholder="A parcel from September came back refused after she was paid."
            />
            <span className="detail__note">
              {first} will see this.
            </span>
          </label>

          {/* The act first and Cancel after it, as on the record form. */}
          <div className="payroll__actions pay__decision-acts">
            <button
              type="submit"
              className="button button--primary"
              disabled={
                working ||
                kind === null ||
                piastres === null ||
                piastres <= 0 ||
                /* ADR 0035. The server refuses this too, and that is the cap
                   that matters - but a button that submits a figure the
                   server will reject teaches somebody the screen is unreliable
                   rather than that the figure is wrong. */
                piastres > over ||
                reason.trim() === ""
              }
            >
              {working
                ? "Recording…"
                : kind === null
                  ? "Choose what happens to it"
                  : kind === "credit"
                    ? `Take ${piastres === null ? "it" : formatEgp(piastres)} off ${formatMonth(destination)}`
                    : `Absorb ${piastres === null ? "it" : formatEgp(piastres)}`}
            </button>
            <Link
              className="button"
              to={back}
              aria-disabled={working || undefined}
              // Not while the decision is being saved: the result shows there.
              onClick={(event) => working && event.preventDefault()}
            >
              Cancel
            </Link>
          </div>
        </form>
      )}
    </>
  );
}
