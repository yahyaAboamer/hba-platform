import { useCallback, useEffect, useRef, useState } from "react";

import { api, can } from "../../lib/api";
import type { Session } from "../../lib/api";
import { formatMonth } from "../../lib/money";
import { Money } from "../../components/Money";
import "./Bonuses.css";

type Bonus = {
  id: number;
  month: string;
  amount_piastres: number;
  amount: string;
  /** Staff only. The portal never receives it. */
  reason: string | null;
  added_by: string | null;
  added_at: string;
  withdrawn_by: string | null;
  withdrawn_at: string | null;
  can_withdraw: boolean;
};

function day(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/**
 * Bonuses HBA added to her months (ADR 0070).
 *
 * The owner, 29 October 2026: a button on every model to add a bonus, with an
 * optional reason only staff see. The amount is the only thing she sees - as
 * its own line on that month, already inside the total.
 *
 * **Only on a month nobody has agreed.** The server refuses an agreed month
 * and says why, so the form does not try to second-guess which months are
 * open; the month field defaults to the one the profile is looking at.
 *
 * `open` is the page head's *Add bonus* button asking for the form.
 */
export function Bonuses({
  affiliateId,
  name,
  month,
  session,
  open,
  onOpened,
  onChanged,
}: {
  affiliateId: string;
  name: string;
  month: string;
  session: Session;
  open: boolean;
  onOpened: () => void;
  onChanged: () => void;
}) {
  const allowed = can(session, "payroll.bonus");
  const [rows, setRows] = useState<Bonus[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [draftMonth, setDraftMonth] = useState(month);
  const [pounds, setPounds] = useState("");
  const [reason, setReason] = useState("");
  // One name for one bonus, kept across retries: a browser that never saw
  // the answer sends it again and is handed the bonus the first attempt made.
  const operation = useRef<string | null>(null);
  const panel = useRef<HTMLElement | null>(null);

  const load = useCallback(() => {
    api
      .get<{ bonuses: Bonus[] }>(`/api/affiliates/${affiliateId}/bonuses`)
      .then((body) => setRows(body.bonuses))
      .catch((caught) => setError(caught.message));
  }, [affiliateId]);

  useEffect(load, [load]);

  function start() {
    setDraftMonth(month);
    setPounds("");
    setReason("");
    setError(null);
    operation.current = null;
    setAdding(true);
  }

  useEffect(() => {
    if (!open || !allowed) return;
    start();
    onOpened();
    panel.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, allowed]);

  // Whole pounds only (ADR 0004 rounds every payout to the pound).
  const whole = /^\d{1,6}$/.test(pounds.trim()) ? Number(pounds.trim()) : null;
  const valid = whole !== null && whole > 0 && /^\d{4}-(0[1-9]|1[0-2])$/.test(draftMonth);

  async function save() {
    if (!valid || whole === null) return;
    setBusy("add");
    setError(null);
    const key = operation.current ?? (operation.current = `bonus:${affiliateId}:${crypto.randomUUID()}`);
    try {
      await api.post(`/api/affiliates/${affiliateId}/bonuses`, {
        month: draftMonth,
        amount_piastres: whole * 100,
        reason: reason.trim() || null,
        operation_key: key,
      });
      setAdding(false);
      operation.current = null;
      load();
      onChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Nothing changed.");
    } finally {
      setBusy(null);
    }
  }

  async function withdraw(row: Bonus) {
    if (!window.confirm(`Withdraw the ${row.amount} bonus from ${formatMonth(row.month)}?`)) return;
    setBusy(`withdraw-${row.id}`);
    setError(null);
    try {
      await api.post(`/api/affiliates/${affiliateId}/bonuses/${row.id}/withdraw`);
      load();
      onChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Nothing changed.");
    } finally {
      setBusy(null);
    }
  }

  const live = (rows ?? []).filter((row) => !row.withdrawn_at);

  return (
    <section className="panel bonuses profile__full" id="bonuses" ref={panel}>
      <div className="panel__head">
        <h2 className="panel__title">Bonuses</h2>
        {allowed && !adding && (
          <button type="button" className="button" onClick={start}>
            Add bonus
          </button>
        )}
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {adding && (
        <div className="bonuses__form">
          <div className="bonuses__fields">
            <label className="field">
              <span className="field__label">Amount (EGP)</span>
              <input
                // The amount is the first thing they need.
                autoFocus
                className="input"
                inputMode="numeric"
                value={pounds}
                placeholder="500"
                onChange={(event) => setPounds(event.target.value.replace(/[^\d]/g, ""))}
              />
            </label>
            <label className="field">
              <span className="field__label">Month</span>
              <input
                className="input"
                type="month"
                value={draftMonth}
                onChange={(event) => setDraftMonth(event.target.value)}
              />
            </label>
          </div>
          <label className="field">
            <span className="field__label">Reason (optional)</span>
            <textarea
              className="input bonuses__reason"
              value={reason}
              rows={2}
              maxLength={500}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Shot the Eid campaign on her day off."
            />
            <span className="detail__note">
              Only staff see this. {name} sees the amount on that month, not the reason.
            </span>
          </label>
          <p className="detail__note">
            Added on top of her pay for {formatMonth(draftMonth || month)}, after any guaranteed minimum.
            Once the month is approved the bonus is part of what was agreed.
          </p>
          <div className="bonuses__actions">
            <button type="button" className="button button--primary" disabled={!valid || !!busy} onClick={save}>
              {busy === "add" ? "Adding…" : whole ? `Add EGP ${whole.toLocaleString("en-US")} bonus` : "Add bonus"}
            </button>
            <button type="button" className="button" disabled={!!busy} onClick={() => setAdding(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {rows === null ? (
        <p className="empty">Loading…</p>
      ) : rows.length === 0 ? (
        !adding && <p className="empty">No bonuses yet.</p>
      ) : (
        <ul className="bonuses__list">
          {rows.map((row) => (
            <li key={row.id} className={`bonuses__row${row.withdrawn_at ? " bonuses__row--withdrawn" : ""}`}>
              <div className="bonuses__facts">
                <span className="bonuses__month">{formatMonth(row.month)}</span>
                <span className="detail__note">
                  Added {day(row.added_at)}{row.added_by && ` by ${row.added_by}`}
                  {row.withdrawn_at && ` · withdrawn ${day(row.withdrawn_at)}${row.withdrawn_by ? ` by ${row.withdrawn_by}` : ""}`}
                </span>
                {row.reason && <span className="bonuses__why">“{row.reason}”</span>}
              </div>
              <span className="bonuses__amount">
                <Money piastres={row.amount_piastres} kind={row.withdrawn_at ? "provisional" : "agreed"} />
              </span>
              {allowed && row.can_withdraw && (
                <button
                  type="button"
                  className="button button--quiet"
                  disabled={!!busy}
                  onClick={() => withdraw(row)}
                >
                  {busy === `withdraw-${row.id}` ? "Withdrawing…" : "Withdraw"}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {live.length > 0 && rows && rows.some((row) => !row.can_withdraw && !row.withdrawn_at) && (
        <p className="detail__note bonuses__foot">A bonus on an approved month stays; reopen the month to change it.</p>
      )}
    </section>
  );
}
