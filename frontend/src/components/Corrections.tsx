import { useCallback, useEffect, useState } from "react";

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
    try {
      await api.post("/api/corrections", {
        affiliate_id: deciding.affiliate_id,
        month: deciding.month,
        choice,
        reason,
        ...(choice === "credit" ? { destination_month: destination } : {}),
      });
      setDeciding(null);
      setReason("");
      setDestination("");
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
              </span>
            </div>
            <span className="corrections__amount">
              <Money piastres={row.recoverable_piastres} tone="owed" />
            </span>
            {can(session, "payments.record") && deciding?.month !== row.month && (
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
            </span>
          </label>

          <div className="corrections__actions">
            <button
              type="button"
              className="button button--primary"
              disabled={!!busy || !reason.trim() || !destination}
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
