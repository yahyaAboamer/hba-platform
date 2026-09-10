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
  /**
   * What this model's month was computed from when the preview was drawn.
   * Handed straight back on the commit so the server can refuse a figure that
   * moved while somebody was reading it (05B).
   */
  source_version: string;
  /** The month moved between the preview and the commit. Reload and look again. */
  stale: boolean;
  note?: string;
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
          /*
           * **Agree the figure that was shown, or agree nothing** (05B).
           *
           * Between drawing this preview and pressing the button a webhook can
           * settle an order, a delivery can fail or a target can be recorded.
           * The old commit recalculated and froze whatever was true at that
           * instant — so the screen said one number and the snapshot said
           * another, and nobody would ever have seen the difference.
           *
           * The server refuses a model whose month has moved and approves the
           * rest, which is why this is a map rather than one value: twenty
           * models are agreed in one act and one moving is not a reason to
           * refuse the other nineteen.
           */
          source_versions: Object.fromEntries(
            (preview?.results ?? []).map((row) => [
              row.affiliate_id,
              row.source_version,
            ]),
          ),
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
        {/*
          * **A stale row is not a blocked row** (05B), and lumping the two
          * together would send somebody hunting for a problem in a month that
          * has nothing wrong with it. The month simply moved between the
          * preview and the button, and looking again is the whole fix.
          */}
        {done.results.some((row) => row.stale) && (
          <p className="notice payroll__note">
            {done.results
              .filter((row) => row.stale)
              .map((row) => row.name)
              .join(", ")}{" "}
            changed while you were looking at{" "}
            {formatMonth(month)}. Nothing was agreed for{" "}
            {done.results.filter((row) => row.stale).length === 1
              ? "her"
              : "them"}
            . Go back, check the figure and agree it again.
          </p>
        )}

        {refused.filter((row) => !row.stale).length > 0 && (
          <p className="notice notice--refused payroll__note">
            Not approved:{" "}
            {refused
              .filter((row) => !row.stale)
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
              From that moment the amount is fixed — later orders land in the
              next month instead. Reopening the month undoes it and keeps both
              versions.
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
