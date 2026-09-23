import { useCallback, useEffect, useRef, useState } from "react";

import { api, can } from "../lib/api";
import type { Session } from "../lib/api";
import { formatMonth } from "../lib/money";
import { Money } from "./Money";
import "./Corrections.css";

type Correction = {
  affiliate_id: number;
  month: string;
  outcome: string;
  agreed_piastres: number;
  now_piastres: number;
  paid_piastres: number;
  recoverable_piastres: number;
  snapshot_version: number;
  /** The whole difference this month has come to, however many orders made it. */
  shortfall_piastres: number;
  /** How much of that has already been carried or absorbed. */
  resolved_piastres: number;
  /** What is left of it — what this row is still about. */
  outstanding_piastres: number;
  /**
   * Why it still needs somebody, when no money can move. Today the only
   * value is `no_transfer_recorded`: the difference is real and nothing was
   * ever sent, so there is nothing to take back.
   */
  review_reason: string | null;
};

type Body = {
  name: string;
  corrections: Correction[];
  outstanding_piastres: number;
};

/**
 * Agreed months whose evidence has moved since, and what to do about them.
 *
 * ## Why this screen exists at all
 *
 * Until 05B, an agreed month that turned out wrong was *reopened*: unmade,
 * recalculated, agreed again. That worked for everything except money already
 * paid against the old figure, which does not un-move. 05B retired it, and
 * this is the replacement — the agreement stands and the difference is
 * recorded against it.
 *
 * ## The platform reports; a person chooses
 *
 * §11.5 is explicit that whether an overpayment is carried into a later month
 * or absorbed by HBA is a judgement about a person they know. Nothing here
 * decides it, and there is no default — the two buttons are equally weighted
 * because the choice is genuinely open.
 *
 * ## No amount to type
 *
 * The figure is computed on the server from the frozen snapshot and a fresh
 * calculation. A box to type it in would let somebody recover more than was
 * ever paid, or recover twice, and the ledger afterwards would say only that
 * they chose that.
 */
export function Corrections({
  affiliateId,
  session,
}: {
  affiliateId: string;
  session: Session;
}) {
  const [body, setBody] = useState<Body | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [deciding, setDeciding] = useState<Correction | null>(null);
  const [reason, setReason] = useState("");
  const [destination, setDestination] = useState("");
  // Held in a ref rather than state: it must survive a retry without
  // re-rendering, and a new value on every render would defeat the point.
  const operation = useRef<string | null>(null);

  const load = useCallback(() => {
    api
      .get<Body>(`/api/affiliates/${affiliateId}/corrections`)
      .then(setBody)
      .catch((caught) => setError(caught.message));
  }, [affiliateId]);

  useEffect(load, [load]);

  async function decide(choice: "credit" | "writeoff") {
    if (!deciding) return;
    setBusy(choice);
    setError(null);
    // R2. One name for one decision, kept across retries. A browser that
    // never saw the answer sends this again and is handed the recovery the
    // first attempt made, rather than making a second one.
    const key =
      operation.current ??
      (operation.current = `correction:${deciding.affiliate_id}:${deciding.month}:${crypto.randomUUID()}`);
    try {
      await api.post("/api/corrections", {
        affiliate_id: deciding.affiliate_id,
        month: deciding.month,
        choice,
        reason,
        // What this screen was showing when the choice was made. A settlement
        // can be partial now, so a retried request is no longer harmlessly
        // repeated - sending the figure turns a duplicate into a refusal
        // rather than a second recovery of the same money.
        expected_outstanding_piastres: deciding.outstanding_piastres,
        operation_key: key,
        ...(choice === "credit" ? { destination_month: destination } : {}),
      });
      setDeciding(null);
      setReason("");
      setDestination("");
      operation.current = null;
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Nothing changed.");
    } finally {
      setBusy(null);
    }
  }

  // Nothing outstanding is the ordinary state, and a panel that is always
  // there teaches people to stop seeing it.
  if (!body || body.corrections.length === 0) return null;

  return (
    <section
      className="panel corrections"
      id="corrections"
    >
      <div className="panel__head">
        <h2 className="panel__title">Agreed months that have changed</h2>
        <span className="chip chip--quiet">
          <Money piastres={body.outstanding_piastres} /> outstanding
        </span>
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      <p className="corrections__lead">
        An order from each of these was refused after the month was agreed.
        {" "}
        <strong>The agreed figure stands</strong> — what is recorded here is
        what {body.name} was sent and no longer earned.
      </p>

      <ul className="corrections__list">
        {body.corrections.map((row) => (
          <li key={row.month} className="corrections__row">
            <div className="corrections__facts">
              <span className="corrections__month">
                {formatMonth(row.month)}
              </span>
              <span className="detail__note">
                Agreed <Money piastres={row.agreed_piastres} kind="agreed" />,
                now worth <Money piastres={row.now_piastres} />, sent{" "}
                <Money piastres={row.paid_piastres} />
                {/*
                 * Only where part of it has been dealt with. A month can be
                 * corrected twice - a second parcel fails weeks after the
                 * first was carried - and the row has to say which part of
                 * the difference is still open, or the figure beside it reads
                 * as the whole month a second time.
                 */}
                {row.resolved_piastres > 0 && (
                  <>
                    {" · "}
                    <Money piastres={row.resolved_piastres} /> of{" "}
                    <Money piastres={row.shortfall_piastres} /> already settled
                  </>
                )}
              </span>
              {/*
               * F09. The difference is real and none of it is recoverable,
               * because nothing was ever sent. Said here rather than shown as
               * a recoverable EGP 0.00 beside a button that refuses.
               */}
              {row.review_reason === "no_transfer_recorded" && (
                <span className="corrections__review">
                  No transfer recorded yet, so there is nothing to take back.
                  Record the transfer that was made, or absorb the difference
                  and pay the agreed figure in full.
                </span>
              )}
              {row.review_reason === "difference_exceeds_what_was_sent" && (
                <span className="corrections__review">
                  Everything sent has already been recovered. The rest is a
                  difference against money not yet transferred, and can be
                  recovered once it is.
                </span>
              )}
            </div>
            <span className="corrections__amount">
              <Money piastres={row.outstanding_piastres} tone="owed" />
            </span>
            {/* R4. A month nothing was sent for can still be decided: HBA
                absorbs the difference and pays the agreed figure in full.
                The panel below offers only that, because there is no money
                to carry anywhere. */}
            {can(session, "payments.record") &&
              deciding?.month !== row.month && (
                <button
                  type="button"
                  className="button"
                  onClick={() => setDeciding(row)}
                >
                  Decide
                </button>
              )}
          </li>
        ))}
      </ul>

      {deciding && (
        <div className="corrections__decide">
          <h3 className="corrections__title">
            {formatMonth(deciding.month)} —{" "}
            <Money piastres={deciding.recoverable_piastres} tone="owed" />
          </h3>
          {/* What can be recovered is capped by what was actually sent, so it
              is not always the whole outstanding difference. */}
          {deciding.recoverable_piastres < deciding.outstanding_piastres && (
            <p className="detail__note">
              <Money piastres={deciding.outstanding_piastres} /> is outstanding;
              this is what was sent and can be taken back.
            </p>
          )}

          <label className="field">
            <span className="field__label">Why?</span>
            <textarea
              className="input corrections__reason"
              value={reason}
              rows={2}
              maxLength={500}
              onChange={(event) => setReason(event.target.value)}
              placeholder="The parcel was refused on delivery."
            />
            <span className="detail__note">
              Kept in the record permanently, next to your name.
            </span>
          </label>

          <label className="field">
            <span className="field__label">
              Take it out of (leave empty to absorb it)
            </span>
            <input
              className="input"
              type="month"
              value={destination}
              // R4. Nothing was sent, so there is nothing to take out of a
              // later month. Absorbing is the only act, and the field says so
              // rather than offering a choice the server will refuse.
              disabled={deciding.recoverable_piastres <= 0}
              onChange={(event) => setDestination(event.target.value)}
            />
            {/*
             * D04, 10 September 2026. Said plainly rather than left to be
             * discovered from a payment of nothing: a carried correction takes
             * the whole month, and a model on a guaranteed minimum can be sent
             * nothing in a month she met her targets in. Her own screen
             * explains it to her; this explains it to the person choosing.
             */}
            <span className="detail__note">
              A carried correction takes as much of that month as it needs,
              including a guaranteed minimum. That month can come to nothing.
              {/*
               * F12, and the part somebody choosing needs to know before they
               * press: a month with less in it than the correction takes what
               * it can, and the rest waits for a later one rather than being
               * refused or forgotten.
               */}
              {" "}If it cannot take all of it, what is left stays against{" "}
              {formatMonth(deciding.month)} for a later month.
            </span>
          </label>

          <div className="corrections__actions">
            <button
              type="button"
              className="button button--primary"
              disabled={
                !!busy ||
                !reason.trim() ||
                !destination ||
                deciding.recoverable_piastres <= 0
              }
              onClick={() => decide("credit")}
            >
              {busy === "credit" ? "Saving…" : "Take it out of that month"}
            </button>
            <button
              type="button"
              className="button"
              disabled={!!busy || !reason.trim() || !!destination}
              onClick={() => decide("writeoff")}
            >
              {busy === "writeoff" ? "Saving…" : "HBA absorbs it"}
            </button>
            <button
              type="button"
              className="button"
              disabled={!!busy}
              onClick={() => {
                setDeciding(null);
                setReason("");
                setDestination("");
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
