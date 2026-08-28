import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Money } from "../components/Money";
import { api } from "../lib/api";
import { formatMonth } from "../lib/money";
import type { PayrollMonth, PayrollRow } from "./Payroll";
import "./Payroll.css";

/**
 * Reopening an agreed month. Pattern C (§12.2), and the heaviest act in the
 * admin interface — it reaches back into a month somebody may already have
 * been paid for.
 *
 * §12.4 is explicit that this must not be reachable as a one-click button
 * inside the month picker. It is here, on its own page, and it asks for a
 * reason before it will do anything.
 */
export function PayrollReopen() {
  const { month = "" } = useParams();
  const navigate = useNavigate();

  const [data, setData] = useState<PayrollMonth | null>(null);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  useEffect(() => {
    setError(null);
    api
      .get<PayrollMonth>(`/api/payroll/${month}`)
      .then(setData)
      .catch((caught) => setError(caught.message));
  }, [month]);

  const approved = (data?.affiliates ?? []).filter(
    (row): row is PayrollRow => row.calculation_state === "approved",
  );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    try {
      await api.post(`/api/payroll/${month}/reopen`, {
        affiliate_ids: [...chosen],
        reason: reason.trim(),
      });
      navigate("/payroll");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Reopen failed.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <Link to="/payroll" className="detail__back">
            Payroll
          </Link>
          <h1>Reopen {formatMonth(month)}</h1>
        </div>
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {data === null && !error && <p className="empty">Loading…</p>}

      {data && approved.length === 0 && (
        <p className="empty">
          Nothing in {formatMonth(month)} has been agreed yet, so there is
          nothing to reopen.
        </p>
      )}

      {approved.length > 0 && (
        <form onSubmit={submit}>
          <section className="panel approve__summary">
            <h2 className="panel__title">What this changes</h2>
            <p className="approve__lead">
              The agreed figure becomes a working one again and is recalculated
              from what is true now. It may come out higher or lower.
            </p>
            <p className="approve__lead">
              <strong>Nothing is erased.</strong> The version you agreed is kept,
              and any payment made against it stays attached to it. The month
              stays unapproved until you agree it again.
            </p>
          </section>

          <table className="table">
            <thead>
              <tr>
                <th className="payroll__pick" />
                <th>Name</th>
                <th className="payroll__amount">Agreed now</th>
                <th>Version</th>
              </tr>
            </thead>
            <tbody>
              {approved.map((row) => (
                <tr key={row.affiliate_id}>
                  <td className="payroll__pick">
                    <input
                      type="checkbox"
                      checked={chosen.has(row.affiliate_id)}
                      aria-label={`Reopen ${row.name}`}
                      onChange={() =>
                        setChosen((was) => {
                          const next = new Set(was);
                          if (next.has(row.affiliate_id)) {
                            next.delete(row.affiliate_id);
                          } else {
                            next.add(row.affiliate_id);
                          }
                          return next;
                        })
                      }
                    />
                  </td>
                  <td>{row.name}</td>
                  {/* The agreed figure, not the recalculation — the column
                      says "agreed now" and must mean it. */}
                  <td className="payroll__amount">
                    <Money
                      piastres={row.approved_obligation_piastres ?? 0}
                      kind="agreed"
                    />
                  </td>
                  <td className="code">
                    {row.version === null ? "—" : `v${row.version}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/*
           * §11.5 requires a written reason, recorded in the audit log. The
           * server enforces it; asking here means the person writes it while
           * they still remember why, rather than meeting a refusal after
           * choosing everybody.
           */}
          <label className="field reopen__reason">
            <span className="field__label">Why is this being reopened?</span>
            <textarea
              className="input reopen__textarea"
              value={reason}
              maxLength={500}
              rows={3}
              required
              onChange={(event) => setReason(event.target.value)}
              placeholder="An order was refused after the month was agreed."
            />
            <span className="detail__note">
              Kept in the record permanently, next to your name.
            </span>
          </label>

          <div className="payroll__actions">
            <button
              type="button"
              className="button"
              onClick={() => navigate("/payroll")}
              disabled={working}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="button button--danger"
              disabled={working || chosen.size === 0 || reason.trim() === ""}
            >
              {working
                ? "Reopening…"
                : chosen.size === 0
                  ? "Choose who to reopen"
                  : `Reopen ${chosen.size} ${chosen.size === 1 ? "month" : "months"}`}
            </button>
          </div>
        </form>
      )}
    </>
  );
}
