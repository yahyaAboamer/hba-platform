import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Money } from "../components/Money";
import { api, can } from "../lib/api";
import type { Session } from "../lib/api";
import { describeBlocker, formatEgp, formatMonth } from "../lib/money";
import {
  describeDestination,
  destinationHolder,
  PAY_TYPE,
  PAYOUT_FIELD_LABEL,
} from "../lib/payouts";
import type { Balance } from "./Payments";
import { paymentRowPresentation, STATE_PILL } from "./Payments";
import type { Revealed } from "./PaymentRecord";
import "./PaymentDetail.css";

type Statement = {
  affiliate_id: number;
  name: string;
  month: string;
  /** Approved from its snapshot, an estimate worked out live, or a month
   *  paid before the platform. Decides every label on the page. */
  basis: "approved" | "estimate" | "settled_outside";
  version: number | null;
  approved_at: string | null;
  compensation_type: string | null;
  commission_rate_bp: number | null;
  counted_sales_piastres: number;
  commission_piastres: number;
  fixed_piastres: number;
  guarantee_top_up_piastres: number;
  carried_piastres: number;
  total_piastres: number;
  guarantee: { base_amount_piastres: number; target_known: boolean };
  blockers: string[];
  source_version: string | null;
};

type Transfer = {
  id: number;
  amount_piastres: number;
  occurred_at: string;
  reference: string | null;
  note: string | null;
  has_proof: boolean;
  destination: { [field: string]: string | null } | null;
  allocations: {
    month: string;
    snapshot_id: number;
    snapshot_version: number;
    allocated_piastres: number;
  }[];
};

type History = { name: string; payments: Transfer[] };

type Correction = { month: string; resolved: boolean };

function dateLong(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

/**
 * One model's month at the payments desk — `vPayment` in the approved export.
 *
 * Left: the state, the lines that make up the figure and the total they come
 * to, and anything that needs a decision. Right, in a 320px column: where to
 * send it, the approval, and the transfers already recorded.
 *
 * This route used to be only the form for recording a transfer, reachable
 * once a month had been agreed, with the destination on that form and
 * approving on a separate batch screen. The export puts all three on this one
 * page, because they are the three things somebody does to one model's
 * month, in order. The form itself is now `/record`.
 *
 * **Every figure is the server's.** The lines come from the statement, which
 * reads an agreed month out of its snapshot; the recorded and remaining
 * figures come from the ledger row the desk list shows.
 */
export function PaymentDetail({ session }: { session: Session }) {
  const { month = "", affiliateId = "" } = useParams();
  const [balance, setBalance] = useState<Balance | null | undefined>(undefined);
  const [statement, setStatement] = useState<Statement | null>(null);
  const [transfers, setTransfers] = useState<Transfer[] | null>(null);
  const [corrections, setCorrections] = useState<Correction[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<Revealed | null>(null);
  const [revealing, setRevealing] = useState(false);

  const load = useCallback(() => {
    setError(null);
    Promise.all([
      api.get<{ affiliates: Balance[] }>(`/api/payments/${month}`),
      api.get<Statement>(`/api/payroll/${month}/statement/${affiliateId}`),
      api.get<History>(`/api/affiliates/${affiliateId}/payments`),
      api.get<{ corrections: Correction[] }>(`/api/affiliates/${affiliateId}/corrections`),
    ])
      .then(([desk, found, history, open]) => {
        setBalance(
          desk.affiliates.find((row) => String(row.affiliate_id) === affiliateId) ?? null,
        );
        setStatement(found);
        setTransfers(
          history.payments.filter((payment) =>
            payment.allocations.some((allocation) => allocation.month === month),
          ),
        );
        setCorrections(
          open.corrections.filter((row) => row.month === month && !row.resolved),
        );
      })
      .catch((caught) => setError(caught.message));
  }, [month, affiliateId]);

  useEffect(load, [load]);

  /*
   * **Approve this month**, from here.
   *
   * It commits with the fingerprint the statement handed out, which is the
   * same string the batch approval screen hands back from its preview - so a
   * month whose orders moved while this page was open is refused and
   * reloaded, never agreed at a figure nobody on this screen saw (05B).
   */
  async function approve() {
    if (!statement?.source_version) return;
    setApproving(true);
    setError(null);
    try {
      const result = await api.post<{
        results: { approved: boolean; stale: boolean; blockers: string[] }[];
      }>(`/api/payroll/${month}/approve`, {
        affiliate_ids: [Number(affiliateId)],
        preview: false,
        source_versions: { [affiliateId]: statement.source_version },
      });
      const row = result.results[0];
      if (!row?.approved) {
        setError(
          row?.stale
            ? "This month changed while you were looking at it. It has been reloaded — look again before approving."
            : (row?.blockers ?? []).map(describeBlocker).join(" · ") ||
                "It could not be approved.",
        );
      }
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Approval failed.");
    } finally {
      setApproving(false);
    }
  }

  /*
   * **The real destination, on request** (ADR 0028). The export prints it on
   * this card outright; here it takes one press, because showing it is
   * gated on recording payments and writes an audit row - who looked, and
   * when - and a record made every time the page opens would record
   * browsing rather than intent.
   */
  async function reveal() {
    setRevealing(true);
    setError(null);
    try {
      setRevealed(
        await api.post<Revealed>(`/api/affiliates/${affiliateId}/payout-destination/reveal`),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not read it.");
    } finally {
      setRevealing(false);
    }
  }

  function copy(label: string, value: string) {
    navigator.clipboard?.writeText(value).then(
      () => {
        setCopied(label);
        window.setTimeout(() => setCopied(null), 2000);
      },
      () => setCopied(null),
    );
  }

  const head = (
    <div className="page__head">
      <Link className="button pay__back" to={`/payments?month=${month}`}>
        ← Payments
      </Link>
      <div className="page__title">
        <h1>{statement?.name ?? balance?.name ?? "Payment"}</h1>
        <span className="page__subtitle">{formatMonth(month)}</span>
      </div>
    </div>
  );

  if (balance === undefined || statement === null) {
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

  if (balance === null) {
    return (
      <>
        {head}
        <p className="empty">
          {statement.name} is not part of {formatMonth(month)}’s payments.
        </p>
      </>
    );
  }

  const view = paymentRowPresentation(balance);
  const rate = statement.commission_rate_bp;
  const guaranteed = statement.compensation_type === "base_guarantee";
  const blocked = statement.basis === "estimate" && statement.blockers.length > 0;
  const needsTerms = statement.blockers.some((key) => key.includes("terms"));
  const totalLabel =
    statement.basis === "approved"
      ? "Approved amount"
      : statement.basis === "settled_outside"
        ? "Settled amount"
        : "Estimated amount";
  const destination = balance.destination ?? null;
  const destinationRows: [string, string | null | undefined, boolean][] = revealed
    ? [
        ["InstaPay payment address", revealed.instapay_address_url, true],
        ["InstaPay number", revealed.instapay_phone, true],
        ["Bank", revealed.bank_name, false],
        [PAYOUT_FIELD_LABEL.bank_account_holder, revealed.bank_account_holder, false],
        [PAYOUT_FIELD_LABEL.bank_account_number, revealed.bank_account_number, true],
        ["Wallet provider", revealed.wallet_provider, false],
        ["Wallet number", revealed.wallet_phone, true],
      ]
    : [];

  return (
    <>
      {head}

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      <div className="pay-detail">
        <div className="pay-detail__main">
          <div className="pay-detail__status">
            <span className={`pill pay-detail__pill ${STATE_PILL[view.label] ?? "payments__pill--quiet"}`}>
              {view.label}
            </span>
            <span className="pay-detail__terms">
              {statement.compensation_type
                ? PAY_TYPE[statement.compensation_type] ?? statement.compensation_type
                : "No terms set"}
            </span>
            <Link
              className="pay-detail__link"
              to={`/affiliates/${affiliateId}?section=payments&month=${month}`}
            >
              Open profile →
            </Link>
          </div>

          {blocked && (
            <div className="pay-detail__blocked" role="alert">
              <div>{statement.blockers.map(describeBlocker).join(" · ")}</div>
              <Link
                className="button button--row pay-detail__blocked-act"
                to={needsTerms ? `/affiliates/${affiliateId}/compensation` : `/targets?month=${month}`}
              >
                {needsTerms ? "Set compensation terms" : "Open Targets"}
              </Link>
            </div>
          )}

          <section className="pay-detail__lines" aria-label="How the figure is made up">
            <StatementLine
              label="Counted sales"
              detail={
                statement.basis === "approved"
                  ? "As approved. Failed deliveries excluded."
                  : "Delivered orders. Failed deliveries excluded."
              }
              piastres={statement.counted_sales_piastres}
              tone="quiet"
            />
            <StatementLine
              label={rate !== null ? `Commission at ${rate / 100}%` : "Commission"}
              detail={
                statement.carried_piastres > 0
                  ? `Includes ${formatEgp(statement.carried_piastres)} carried in from earlier months`
                  : null
              }
              piastres={statement.commission_piastres}
            />
            {statement.fixed_piastres > 0 && (
              <StatementLine label="Fixed salary" piastres={statement.fixed_piastres} />
            )}
            {guaranteed &&
              (statement.guarantee_top_up_piastres > 0 ? (
                <StatementLine
                  label="Guarantee top-up"
                  detail={`Targets met, so the month is brought up to ${formatEgp(
                    statement.guarantee.base_amount_piastres,
                  )}`}
                  piastres={statement.guarantee_top_up_piastres}
                  tone="lift"
                />
              ) : (
                <StatementLine
                  label="Guaranteed minimum not applied"
                  detail={
                    statement.guarantee.target_known
                      ? "Targets for this month were not met, or commission already exceeds the minimum"
                      : "Target outcome not recorded yet"
                  }
                  piastres={0}
                  tone="quiet"
                />
              ))}
            <div className="pay-detail__total">
              <span>{totalLabel}</span>
              <Money piastres={statement.total_piastres} kind="agreed" />
            </div>
          </section>

          {balance.credited_piastres > 0 && view.explanation && (
            <p className="pay-detail__note pay-detail__note--owed">{view.explanation}</p>
          )}
          {statement.basis === "approved" &&
            balance.state === "settled" &&
            balance.paid_piastres === 0 &&
            balance.credited_piastres === 0 && (
              <p className="pay-detail__note pay-detail__note--settled">
                Approved with nothing to send. This month is complete.
              </p>
            )}
          {balance.state === "overpaid" && (
            <p className="pay-detail__note pay-detail__note--owed">
              <Money piastres={balance.paid_piastres} kind="agreed" /> was transferred
              against an approved <Money piastres={balance.obligation_piastres} kind="agreed" />.
              The difference stays visible rather than being adjusted away.{" "}
              <Link className="pay-detail__link" to={`/payments/${month}/${affiliateId}/reconcile`}>
                Settle the difference →
              </Link>
            </p>
          )}
          {corrections.map((_, index) => (
            <Link
              key={index}
              className="pay-detail__correction"
              to={`/payments/${month}/${affiliateId}/correction`}
            >
              A difference was found after {formatMonth(month)} was agreed. A
              decision is needed.
              <span className="pay-detail__link">Open the correction →</span>
            </Link>
          ))}
        </div>

        <aside className="pay-detail__side">
          <section className="pay-detail__card">
            <div className="pay-detail__card-head">
              <h2 className="pay-detail__card-title">Where to send it</h2>
              {destination && (
                <span className="pay-detail__muted">{destinationHolder(destination)}</span>
              )}
            </div>
            {!destination ? (
              <>
                <p className="pay-detail__missing">
                  No payout destination is on file for {balance.name}.
                </p>
                <Link className="button button--row" to={`/affiliates/${affiliateId}`}>
                  Open the profile
                </Link>
              </>
            ) : (
              <>
                {/* A destination that changed shortly before a transfer is
                 *  the moment a redirected payout costs money (§6.4.5). */}
                {balance.destination_changed_at && (
                  <p className="pay-detail__missing">
                    Changed {dateLong(balance.destination_changed_at)}. Check with{" "}
                    {balance.name} before sending anything.
                  </p>
                )}
                {revealed === null ? (
                  <>
                    <p className="pay-detail__dest-summary">{describeDestination(destination)}</p>
                    {can(session, "payments.record") ? (
                      <>
                        <button
                          type="button"
                          className="button button--row pay-detail__reveal"
                          disabled={revealing}
                          onClick={reveal}
                        >
                          {revealing ? "Reading…" : "Show where to send it"}
                        </button>
                        <p className="pay-detail__faint">
                          Shortened everywhere else on purpose. Showing it is
                          recorded — who looked, and when.
                        </p>
                      </>
                    ) : (
                      <p className="pay-detail__faint">
                        Only somebody who records payments can see the full details.
                      </p>
                    )}
                  </>
                ) : (
                  <>
                    {destinationRows
                      .filter(([, value]) => value)
                      .map(([label, value, copyable]) => (
                        <div key={label} className="pay-detail__dest">
                          <span className="pay-detail__dest-text">
                            <span className="pay-detail__dest-label">{label}</span>
                            <span className="pay-detail__dest-value">{value}</span>
                          </span>
                          {copyable && (
                            <button
                              type="button"
                              className="button button--quiet"
                              onClick={() => copy(label, value ?? "")}
                            >
                              {copied === label ? "Copied" : "Copy"}
                            </button>
                          )}
                        </div>
                      ))}
                    {revealed.instapay_address_url && (
                      <a
                        className="button pay-detail__instapay"
                        href={revealed.instapay_address_url}
                        target="_blank"
                        rel="noreferrer noopener"
                      >
                        Open InstaPay
                      </a>
                    )}
                  </>
                )}
              </>
            )}
          </section>

          <section className="pay-detail__card">
            <h2 className="pay-detail__card-title">Approval</h2>
            {statement.basis === "approved" && (
              <p className="pay-detail__approved">
                Approved
                {statement.approved_at ? ` ${dateLong(statement.approved_at)}` : ""} ·{" "}
                <Money piastres={statement.total_piastres} kind="agreed" />
                {statement.version && statement.version > 1 ? ` · version ${statement.version}` : ""}
              </p>
            )}
            {statement.basis === "settled_outside" && (
              <p className="pay-detail__muted">
                Paid outside the platform. Nothing is approved or sent here.
              </p>
            )}
            {statement.basis === "estimate" &&
              (!can(session, "payroll.approve") ? (
                <p className="pay-detail__muted">Not approved yet.</p>
              ) : blocked || !statement.source_version ? (
                <p className="pay-detail__muted">
                  It can be approved once what is blocking it is resolved.
                </p>
              ) : (
                <>
                  <p className="pay-detail__muted">
                    Approval freezes this calculation. Recording the transfer is separate.
                  </p>
                  <button
                    type="button"
                    className="button button--primary pay-detail__wide"
                    disabled={approving}
                    onClick={approve}
                  >
                    {approving ? "Approving…" : "Approve this month"}
                  </button>
                </>
              ))}
          </section>

          <section className="pay-detail__card">
            <h2 className="pay-detail__card-title">Transfers</h2>
            <p className="pay-detail__muted pay-detail__summary">
              {balance.paid_piastres > 0 ? (
                <>
                  <Money piastres={balance.paid_piastres} kind="agreed" /> recorded
                </>
              ) : (
                "Nothing recorded yet"
              )}
              {" · "}
              <Money
                piastres={balance.balance_piastres > 0 ? balance.balance_piastres : 0}
                kind="agreed"
              />{" "}
              remaining
            </p>
            {transfers?.map((transfer) => {
              const here = transfer.allocations.find((allocation) => allocation.month === month);
              return (
                <Link
                  key={transfer.id}
                  className="pay-detail__transfer"
                  to={`/payments/${month}/${affiliateId}/receipts/${transfer.id}`}
                >
                  <span className="pay-detail__transfer-top">
                    <Money piastres={here?.allocated_piastres ?? transfer.amount_piastres} kind="agreed" />
                    <span className="pay-detail__link">Receipt →</span>
                  </span>
                  <span className="pay-detail__transfer-meta">
                    {dateLong(transfer.occurred_at)}
                    {transfer.reference ? ` · ${transfer.reference}` : ""}
                  </span>
                  <span className={transfer.has_proof ? "pay-detail__tone--lift" : "pay-detail__tone--owed"}>
                    {transfer.has_proof ? "Receipt attached" : "No receipt attached"}
                  </span>
                </Link>
              );
            })}
            {transfers?.length === 0 && (
              <p className="pay-detail__faint">
                {statement.basis === "settled_outside"
                  ? `No payments recorded here for ${formatMonth(month)}.`
                  : "No transfer has been recorded yet."}
              </p>
            )}
            {can(session, "payments.record") &&
              statement.basis === "approved" &&
              balance.balance_piastres > 0 && (
                <Link
                  className="button pay-detail__wide pay-detail__record"
                  to={`/payments/${month}/${affiliateId}/record`}
                >
                  Record payment
                </Link>
              )}
          </section>
        </aside>
      </div>
    </>
  );
}

function StatementLine({
  label,
  detail = null,
  piastres,
  tone = "ink",
}: {
  label: string;
  detail?: string | null;
  piastres: number;
  tone?: "ink" | "quiet" | "lift";
}) {
  return (
    <div className="pay-detail__line">
      <span>
        <span className="pay-detail__line-label">{label}</span>
        {detail && <span className="pay-detail__line-detail">{detail}</span>}
      </span>
      <span className={`pay-detail__line-value pay-detail__tone--${tone}`}>
        <Money piastres={piastres} kind="agreed" />
      </span>
    </div>
  );
}

/**
 * One recorded transfer — `vReceipt` in the approved export.
 *
 * The amount this transfer settled for the month, when it was recorded, its
 * reference, the destination as it stood at the time, and the confirmation
 * screenshot when there is one. *Recorded by* is left out rather than
 * guessed: the ledger row does not carry it to this screen.
 */
export function PaymentReceipt() {
  const { month = "", affiliateId = "", paymentId = "" } = useParams();
  const [history, setHistory] = useState<History | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<History>(`/api/affiliates/${affiliateId}/payments`)
      .then(setHistory)
      .catch((caught) => setError(caught.message));
  }, [affiliateId]);

  const transfer = history?.payments.find((payment) => String(payment.id) === paymentId);
  const here = transfer?.allocations.find((allocation) => allocation.month === month);
  const back = `/payments/${month}/${affiliateId}`;

  return (
    <>
      <div className="page__head">
        <Link className="button pay__back" to={back}>
          ← {history?.name ?? "Payment"}
        </Link>
        <div className="page__title">
          <h1>Receipt</h1>
          <span className="page__subtitle">{formatMonth(month)}</span>
        </div>
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}
      {!history && !error && <p className="empty">Loading…</p>}
      {history && !transfer && <p className="empty">That transfer is not on record.</p>}

      {transfer && (
        <div className="pay-receipt">
          <section className="pay-receipt__card">
            <div className="pay-detail__muted">{formatMonth(month)}</div>
            <div className="pay-receipt__amount">
              <Money piastres={here?.allocated_piastres ?? transfer.amount_piastres} kind="agreed" />
            </div>
            <dl className="pay-receipt__rows">
              <div>
                <dt>Recorded</dt>
                <dd>{dateLong(transfer.occurred_at)}</dd>
              </div>
              <div>
                <dt>Reference</dt>
                <dd>{transfer.reference || "None given"}</dd>
              </div>
              <div>
                <dt>Destination used at the time</dt>
                <dd>{describeDestination(transfer.destination)}</dd>
              </div>
              <div>
                <dt>Receipt</dt>
                <dd>{transfer.has_proof ? "Attached" : "No receipt attached"}</dd>
              </div>
              {transfer.note && (
                <div>
                  <dt>Note</dt>
                  <dd>{transfer.note}</dd>
                </div>
              )}
            </dl>
            {transfer.has_proof ? (
              <img
                className="pay-receipt__image"
                src={`/api/payments/${transfer.id}/proof`}
                alt="Transfer confirmation"
              />
            ) : (
              <div className="pay-receipt__none">No receipt attached to this transfer</div>
            )}
          </section>
          <Link className="button pay-receipt__back" to={back}>
            Open the month’s payment
          </Link>
        </div>
      )}
    </>
  );
}
