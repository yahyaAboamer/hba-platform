import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { Money } from "../components/Money";
import { api } from "../lib/api";
import { describeBlocker, formatMonth } from "../lib/money";
import "./Payroll.css";

type Outcome = {
  affiliate_id: number;
  name: string;
  obligation_piastres: number;
  blockers: string[];
  approved: boolean;
  version: number | null;
};

type ApprovalResult = {
  month: string;
  preview: boolean;
  results: Outcome[];
  totals: { approved: number; blocked: number; obligation_piastres: number };
};

/**
 * Approving a month. Pattern C (§12.2): its own page, its own URL, and a
 * mandatory preview of what is about to change.
 *
 * **The preview is the same endpoint as the commit**, with `preview: true`.
 * §11.3 asks to see every model, amount and blocker before committing, and the
 * honest way to show that is to run the code that will run — a separate
 * preview path is a second implementation that drifts, and it drifts silently
 * because nobody compares the two.
 */
export function PayrollApprove() {
  const { month = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const chosen = (location.state as { affiliate_ids?: number[] } | null)
    ?.affiliate_ids;

  const [preview, setPreview] = useState<ApprovalResult | null>(null);
  const [done, setDone] = useState<ApprovalResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  useEffect(() => {
    if (!chosen?.length) return;
    setError(null);
    api
      .post<ApprovalResult>(`/api/payroll/${month}/approve`, {
        affiliate_ids: chosen,
        preview: true,
      })
      .then(setPreview)
      .catch((caught) => setError(caught.message));
  }, [month, chosen]);

  async function commit() {
    setWorking(true);
    setError(null);
    try {
      setDone(
        await api.post<ApprovalResult>(`/api/payroll/${month}/approve`, {
          affiliate_ids: chosen,
          preview: false,
        }),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Approval failed.");
    } finally {
      setWorking(false);
    }
  }

  // Reached directly, or after a reload that dropped the router state. There is
  // nothing to approve and nothing sensible to guess.
  if (!chosen?.length) {
    return (
      <>
        <Head month={month} />
        <p className="empty">
          Nobody was chosen. Pick who to approve on the{" "}
          <Link to="/payroll">payroll screen</Link> first.
        </p>
      </>
    );
  }

  if (done) {
    const approved = done.results.filter((row) => row.approved);
    const refused = done.results.filter((row) => !row.approved);
    return (
      <>
        <Head month={month} />
        <p className="notice notice--settled payroll__note">
          {formatMonth(month)} is agreed for{" "}
          {approved.length === 1 ? "one model" : `${approved.length} models`}.{" "}
          <Money
            piastres={done.totals.obligation_piastres}
            kind="agreed"
            tone="owed"
          />{" "}
          is now owed. Paying it happens on the Payments screen.
        </p>

        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th className="payroll__amount">Agreed</th>
              <th>Version</th>
            </tr>
          </thead>
          <tbody>
            {approved.map((row) => (
              <tr key={row.affiliate_id}>
                <td>{row.name}</td>
                <td className="payroll__amount">
                  <Money piastres={row.obligation_piastres} kind="agreed" />
                </td>
                <td className="code">v{row.version}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/*
         * Bulk approval is all-or-nothing per model, not per run: one blocked
         * row does not refuse the other nineteen. So the ones that did not go
         * through have to be named, or they are silently skipped.
         */}
        {refused.length > 0 && (
          <p className="notice notice--refused payroll__note">
            Not approved:{" "}
            {refused
              .map(
                (row) =>
                  `${row.name} (${row.blockers.map(describeBlocker).join(", ")})`,
              )
              .join("; ")}
            . The rest went through.
          </p>
        )}

        <div className="payroll__actions">
          <Link className="button button--primary" to="/payroll">
            Back to payroll
          </Link>
        </div>
      </>
    );
  }

  const willApprove = preview?.results.filter((row) => !row.blockers.length) ?? [];
  const willNot = preview?.results.filter((row) => row.blockers.length) ?? [];
  const total = willApprove.reduce(
    (sum, row) => sum + row.obligation_piastres,
    0,
  );

  return (
    <>
      <Head month={month} />

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {preview === null && !error && <p className="empty">Working it out…</p>}

      {preview && (
        <>
          <section className="panel approve__summary">
            <h2 className="panel__title">What this changes</h2>
            <p className="approve__lead">
              {willApprove.length === 1
                ? `One model’s ${formatMonth(month)} is agreed at the figure below.`
                : `${willApprove.length} models’ ${formatMonth(month)} is agreed at the figures below.`}{" "}
              From that moment the amount is fixed: later orders and later
              corrections do not change it, they land in the next month instead.
            </p>
            <p className="approve__lead">
              This can be undone by reopening the month, which keeps a record of
              both versions. It is not a quiet edit, which is why it is here on
              its own page and not a button on a row.
            </p>
            <div className="approve__total">
              <Money piastres={total} tone="owed" className="payroll__total" />
              <span className="payroll__figure-label">
                becomes owed across {willApprove.length}{" "}
                {willApprove.length === 1 ? "model" : "models"}
              </span>
            </div>
          </section>

          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th className="payroll__amount">Becomes owed</th>
              </tr>
            </thead>
            <tbody>
              {willApprove.map((row) => (
                <tr key={row.affiliate_id}>
                  <td>{row.name}</td>
                  <td className="payroll__amount">
                    <Money piastres={row.obligation_piastres} tone="owed" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {willNot.length > 0 && (
            <p className="notice notice--refused payroll__note">
              These will be skipped, and everything else still goes through:{" "}
              {willNot
                .map(
                  (row) =>
                    `${row.name} (${row.blockers.map(describeBlocker).join(", ")})`,
                )
                .join("; ")}
            </p>
          )}

          <div className="payroll__actions">
            <button
              type="button"
              className="button button--primary"
              disabled={working || willApprove.length === 0}
              onClick={commit}
            >
              {working
                ? "Agreeing…"
                : `Agree ${formatMonth(month)} for ${willApprove.length} ${
                    willApprove.length === 1 ? "model" : "models"
                  }`}
            </button>
            <button
              type="button"
              className="button"
              onClick={() => navigate("/payroll")}
              disabled={working}
            >
              Cancel
            </button>
          </div>
        </>
      )}
    </>
  );
}

function Head({ month }: { month: string }) {
  return (
    <div className="page__head">
      <div className="page__title">
        <Link to="/payroll" className="detail__back">
          Payroll
        </Link>
        <h1>Approve {formatMonth(month)}</h1>
      </div>
    </div>
  );
}
