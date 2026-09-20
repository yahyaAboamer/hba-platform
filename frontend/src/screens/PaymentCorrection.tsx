import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Money } from "../components/Money";
import { api, can } from "../lib/api";
import type { Session } from "../lib/api";
import { formatMonth } from "../lib/money";
import "./PaymentDetail.css";

type Correction = {
  affiliate_id: number;
  month: string;
  agreed_piastres: number;
  now_piastres: number;
  paid_piastres: number;
  recoverable_piastres: number;
  snapshot_version: number;
  /** The month's whole difference, and how much of it is still open. */
  shortfall_piastres: number;
  resolved_piastres: number;
  outstanding_piastres: number;
  review_reason: string | null;
};

type Body = { name: string; corrections: Correction[] };

type Choice = "writeoff" | "credit";

/**
 * A month that changed after it was agreed — `vCorrection` in the export.
 *
 * Left: what the month was agreed at, what was sent, what it is worth now,
 * and the difference that is recoverable. Right: the decision - HBA absorbs
 * it, or it is carried to a later payment - with a month and a reason.
 *
 * **No amount is typed.** The server works the recoverable difference out
 * from the frozen snapshot and a fresh calculation, capped at what was paid
 * (05C); a caller supplying its own could recover more than was ever sent.
 * The agreed month itself is not touched either way: it keeps its approved
 * calculation and its recorded payment.
 *
 * This decision used to be made only from a panel on the model's profile.
 * The export reaches it from the month's payment, where the difference is
 * found, and the profile panel stays where it was.
 */
export function PaymentCorrection({ session }: { session: Session }) {
  const { month = "", affiliateId = "" } = useParams();
  const [body, setBody] = useState<Body | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [choice, setChoice] = useState<Choice>("credit");
  const [destination, setDestination] = useState("");
  const [reason, setReason] = useState("");
  const [working, setWorking] = useState(false);
  const [decided, setDecided] = useState<{ choice: Choice; destination: string; reason: string } | null>(null);
  // R2. One name for one decision, kept across retries rather than minted per
  // render - a new value on every attempt would be a new decision each time.
  const operation = useRef(`correction:${affiliateId}:${month}:${crypto.randomUUID()}`);

  useEffect(() => {
    api
      .get<Body>(`/api/affiliates/${affiliateId}/corrections`)
      .then(setBody)
      .catch((caught) => setError(caught.message));
  }, [affiliateId]);

  const row = body?.corrections.find((candidate) => candidate.month === month) ?? null;
  const back = `/payments/${month}/${affiliateId}`;

  async function save() {
    if (!row) return;
    setWorking(true);
    setError(null);
    try {
      await api.post("/api/corrections", {
        affiliate_id: row.affiliate_id,
        month: row.month,
        choice,
        reason: reason.trim(),
        // What this screen was showing. A settlement can be partial now, so a
        // repeated submission must not recover twice.
        expected_outstanding_piastres: row.outstanding_piastres,
        // R2. One name for one decision, held across retries: a request that
        // arrives again is answered with the recovery the first one made.
        operation_key: operation.current,
        ...(choice === "credit" ? { destination_month: destination } : {}),
      });
      setDecided({ choice, destination, reason: reason.trim() });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Nothing changed.");
    } finally {
      setWorking(false);
    }
  }

  // R4. Nothing was sent, so there is nothing to carry into a later month -
  // but HBA can still absorb the difference and pay the agreed figure in
  // full, which is a decision and is recorded as one. Only the carry is out
  // of reach here.
  const recoverable = (row?.recoverable_piastres ?? 0) > 0;
  const ready =
    reason.trim() !== "" &&
    (choice === "writeoff" ? true : recoverable && destination !== "");

  return (
    <>
      <div className="page__head">
        <Link className="button pay__back" to={back}>
          ← {body?.name ?? "Payment"}
        </Link>
        <div className="page__title">
          <h1>Correction</h1>
          <span className="page__subtitle">{formatMonth(month)}</span>
        </div>
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}
      {!body && !error && <p className="empty">Loading…</p>}
      {body && !row && !decided && (
        <p className="empty">
          Nothing in {formatMonth(month)} is waiting for a decision.
        </p>
      )}

      {body && (row || decided) && (
        <div className="pay-detail">
          <div className="pay-detail__main">
            {row && (
              <section className="pay-detail__card">
                <div className="pay-fix__lead">
                  {body.name} · {formatMonth(month)} changed after it was agreed
                </div>
                <dl className="pay-receipt__rows">
                  <div>
                    <dt>Approved for {formatMonth(month)}</dt>
                    <dd><Money piastres={row.agreed_piastres} kind="agreed" /></dd>
                  </div>
                  <div>
                    <dt>Transferred</dt>
                    <dd><Money piastres={row.paid_piastres} kind="agreed" /></dd>
                  </div>
                  <div>
                    <dt>What the month is worth now</dt>
                    <dd><Money piastres={row.now_piastres} kind="agreed" /></dd>
                  </div>
                  {/* Only where part of it has already been dealt with - a
                      second failure against a month that was carried once. */}
                  {row.resolved_piastres > 0 && (
                    <div>
                      <dt>Already carried or absorbed</dt>
                      <dd><Money piastres={row.resolved_piastres} kind="agreed" /></dd>
                    </div>
                  )}
                  <div>
                    <dt>Difference still open</dt>
                    <dd><Money piastres={row.outstanding_piastres} kind="agreed" tone="owed" /></dd>
                  </div>
                  <div>
                    <dt>Recoverable</dt>
                    <dd><Money piastres={row.recoverable_piastres} kind="agreed" tone="owed" /></dd>
                  </div>
                </dl>
                {/*
                 * F09. The difference is real and nothing was sent, so there
                 * is nothing to take back - said here rather than left to be
                 * read off a recoverable zero.
                 */}
                {row.review_reason === "no_transfer_recorded" && (
                  <p className="pay-detail__faint">
                    No transfer is recorded against {formatMonth(month)}, so
                    there is nothing to recover from it. Record the transfer
                    that was made, or leave the agreed figure to be paid in
                    full.
                  </p>
                )}
                <p className="pay-detail__faint">
                  {formatMonth(month)} keeps its approved calculation and its
                  recorded payment. Only its sales performance reflects the change.
                </p>
                <Link className="pay-detail__link" to={back}>
                  Open the {formatMonth(month)} calculation →
                </Link>
              </section>
            )}

            {decided && (
              <div className="pay-fix__decided">
                <div>
                  {decided.choice === "credit"
                    ? `Carried to ${formatMonth(decided.destination)}`
                    : "HBA absorbed this"}
                  {decided.reason ? ` · ${decided.reason}` : ""}
                </div>
                {decided.choice === "credit" && (
                  <Link
                    className="pay-detail__link"
                    to={`/payments?month=${decided.destination}`}
                  >
                    Open the destination month in Payments →
                  </Link>
                )}
              </div>
            )}
          </div>

          {row && !decided && (
            <aside className="pay-detail__side">
              <section className="pay-detail__card">
                <h2 className="pay-detail__card-title">Decision</h2>
                {!can(session, "payments.record") ? (
                  <p className="pay-detail__muted">
                    Only somebody who records payments can decide this.
                  </p>
                ) : (
                  <>
                    <div className="pay-fix__options" role="radiogroup" aria-label="Decision">
                      <button
                        type="button"
                        role="radio"
                        aria-checked={choice === "writeoff"}
                        className={choice === "writeoff" ? "pay-fix__option pay-fix__option--on" : "pay-fix__option"}
                        onClick={() => setChoice("writeoff")}
                      >
                        HBA absorbs it
                      </button>
                      <button
                        type="button"
                        role="radio"
                        aria-checked={choice === "credit"}
                        className={choice === "credit" ? "pay-fix__option pay-fix__option--on" : "pay-fix__option"}
                        onClick={() => setChoice("credit")}
                      >
                        Carry to a later payment
                      </button>
                    </div>

                    {/*
                      * F2. Two sentences the operator has to be able to tell
                      * apart before pressing either button, because they used
                      * to be the same row type and therefore looked alike.
                      *
                      * Absorbing takes the **whole** remaining difference —
                      * there is no partial version, since absorbing recovers
                      * nothing either way — and leaves what she is still owed
                      * exactly where the agreement put it. Carrying recovers
                      * only what actually moved, and only from the month it is
                      * carried to.
                      */}
                    <p className="pay-fix__note">
                      {choice === "writeoff" ? (
                        <>
                          HBA takes the whole remaining difference of{" "}
                          <Money piastres={row.outstanding_piastres} kind="agreed" />. The
                          agreed total for {formatMonth(month)} does not change,
                          and neither does anything still to be sent for it.
                        </>
                      ) : (
                        <>
                          <Money piastres={row.recoverable_piastres} kind="agreed" /> is
                          recovered from the month you choose, which is paid that
                          much less. What {formatMonth(month)} is still owed does
                          not change.
                        </>
                      )}
                    </p>

                    {choice === "credit" && (
                      <label className="pay-fix__field">
                        <span>Destination month</span>
                        <input
                          className="input pay-fix__input"
                          type="month"
                          min={month}
                          value={destination}
                          onChange={(event) => setDestination(event.target.value)}
                        />
                      </label>
                    )}

                    <label className="pay-fix__field">
                      <span>Reason</span>
                      <input
                        className="input pay-fix__input"
                        maxLength={500}
                        value={reason}
                        onChange={(event) => setReason(event.target.value)}
                        placeholder="Short note for the record"
                      />
                    </label>

                    <button
                      type="button"
                      className="button button--primary pay-detail__wide"
                      disabled={working || !ready}
                      onClick={save}
                    >
                      {working
                        ? "Saving…"
                        : choice === "writeoff"
                          ? "HBA absorbs this"
                          : destination
                            ? `Carry to ${formatMonth(destination)}`
                            : "Carry to a later payment"}
                    </button>
                  </>
                )}
              </section>
            </aside>
          )}
        </div>
      )}
    </>
  );
}
