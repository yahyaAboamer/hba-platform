import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Money } from "../components/Money";
import { api } from "../lib/api";
import { describeBlocker, formatMonth } from "../lib/money";
import { STATUS_LABEL } from "./Affiliates";
import type { Affiliate } from "./Affiliates";
import "./AffiliateDetail.css";

type Compensation = {
  start_month: string;
  end_month: string | null;
  compensation_type: "commission" | "fixed_plus_commission" | "base_guarantee";
  commission_rate_bp: number;
  fixed_amount_piastres: number | null;
  base_amount_piastres: number | null;
  expected_customer_discount_bp: number | null;
};

type Destination = {
  method: string;
  bank_name: string | null;
  bank_account_holder: string | null;
  instapay_address_url: string | null;
  instapay_phone: string | null;
  bank_account_number: string | null;
  wallet_phone: string | null;
};

type Code = {
  code: string;
  /** Shopify has been asked and says this code exists. Until then it earns
   *  nothing, however correct it looks. */
  verified: boolean;
  start_month: string;
  end_month: string | null;
};

type Detail = Affiliate & {
  current_month: string;
  codes: Code[];
  compensation: Compensation | null;
  payout_destination: Destination | null;
};

type Earnings = {
  month: string;
  sales: { earned_piastres: number; pending_piastres: number };
  orders: { earned: number; pending: number; void: number };
  payout: { piastres: number; is_provisional: boolean };
  blockers: string[];
  is_payable: boolean;
};

const METHOD: Record<string, string> = {
  instapay: "InstaPay",
  bank: "Bank transfer",
  wallet: "Mobile wallet",
};

const PAY_TYPE: Record<string, string> = {
  commission: "Commission only",
  fixed_plus_commission: "Salary plus commission",
  base_guarantee: "Guaranteed minimum",
};

/**
 * One model, and everything true about her this month.
 *
 * Read-only for now. The pages that *change* what she is paid — her rate, her
 * discount code, where her money goes — each get their own page with a "what
 * this changes" preview, and those are the next screens after this one (§12.2
 * calls them Pattern C: money decisions never happen in a small dialog).
 */
export function AffiliateDetail() {
  const { id } = useParams();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [earnings, setEarnings] = useState<Earnings | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    api
      .get<Detail>(`/api/affiliates/${id}`)
      .then((body) => {
        setDetail(body);
        return api.get<Earnings>(
          `/api/affiliates/${id}/earnings/${body.current_month}`,
        );
      })
      .then(setEarnings)
      .catch((caught) => setError(caught.message));
  }, [id]);

  if (error) {
    return (
      <p className="notice notice--refused" role="alert">
        {error}
      </p>
    );
  }

  if (!detail) return <p className="empty">Loading…</p>;

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <Link to="/affiliates" className="detail__back">
            Affiliates
          </Link>
          <h1>{detail.name}</h1>
          <span className={`state state--${detail.status}`}>
            {STATUS_LABEL[detail.status]}
          </span>
        </div>
      </div>

      {/*
       * The one thing that is genuinely wrong rather than merely absent: an
       * active model with no confirmed code earns nothing, silently, until
       * somebody notices the sales are missing (§10.4).
       */}
      {detail.status !== "archived" &&
        !detail.codes.some((entry) => entry.verified) && (
          <p className="notice notice--refused detail__warning">
            {detail.codes.length === 0
              ? `No discount code is registered for ${formatMonth(detail.current_month)}. Orders placed with one will belong to nobody until there is.`
              : "Shopify has not confirmed this code exists. Orders that carry it are still attributed — the risk is that it was mistyped or never created there, in which case no order ever will, and nothing looks wrong until somebody asks why the sales are missing."}
          </p>
        )}

      <div className="detail__grid">
        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">How the month is going</h2>
            <span className="page__subtitle">
              {formatMonth(detail.current_month)}
            </span>
          </div>
          <dl className="detail__list">
            <Row label="Sales that count">
              {earnings ? (
                <Money piastres={earnings.sales.earned_piastres} />
              ) : (
                "—"
              )}
            </Row>
            <Row label="Still travelling">
              {earnings ? (
                <Money piastres={earnings.sales.pending_piastres} />
              ) : (
                "—"
              )}
              {earnings && earnings.orders.pending > 0 && (
                <span className="detail__note">
                  {earnings.orders.pending} order
                  {earnings.orders.pending === 1 ? "" : "s"} on the way
                </span>
              )}
            </Row>
            <Row label="Would be paid">
              {/*
               * A blocked figure is **not** owed, and must not be coloured as
               * if it were. Somebody scanning for what to pay should be able
               * to trust that orange means payable; the reason it is blocked
               * sits in the row directly below (ADR 0027).
               */}
              {earnings ? (
                <Money
                  piastres={earnings.payout.piastres}
                  kind={earnings.blockers.length > 0 ? "blocked" : "provisional"}
                  tone={
                    earnings.blockers.length === 0 && earnings.payout.piastres > 0
                      ? "owed"
                      : "neutral"
                  }
                />
              ) : (
                "—"
              )}
            </Row>
            {earnings && earnings.blockers.length > 0 && (
              <Row label="Waiting on">
                <ul className="detail__blockers">
                  {earnings.blockers.map((key) => (
                    <li key={key} className="blocker">
                      {describeBlocker(key)}
                    </li>
                  ))}
                </ul>
              </Row>
            )}
          </dl>
        </section>

        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">How she is paid</h2>
          </div>
          {detail.compensation === null ? (
            <p className="empty">
              No pay terms for this month, so nothing can be calculated. Her
              sales are still recorded.
            </p>
          ) : (
            <dl className="detail__list">
              <Row label="Arrangement">
                {PAY_TYPE[detail.compensation.compensation_type]}
              </Row>
              <Row label="Commission">
                <span className="code">
                  {detail.compensation.commission_rate_bp / 100}%
                </span>
              </Row>
              {detail.compensation.fixed_amount_piastres !== null && (
                <Row label="Salary">
                  <Money piastres={detail.compensation.fixed_amount_piastres} />
                </Row>
              )}
              {detail.compensation.base_amount_piastres !== null && (
                <Row label="Guaranteed minimum">
                  <Money piastres={detail.compensation.base_amount_piastres} />
                  <span className="detail__note">
                    Applies only when her targets are met and confirmed
                  </span>
                </Row>
              )}
              <Row label="In force from">
                <span className="code">
                  {formatMonth(detail.compensation.start_month)}
                </span>
                {detail.compensation.end_month && (
                  <span className="detail__note">
                    to {formatMonth(detail.compensation.end_month)}
                  </span>
                )}
              </Row>
            </dl>
          )}
        </section>

        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Discount codes</h2>
            <span className="page__subtitle">
              {formatMonth(detail.current_month)}
            </span>
          </div>
          {detail.codes.length === 0 ? (
            <p className="empty">None registered for this month.</p>
          ) : (
            <ul className="detail__codes">
              {detail.codes.map((entry) => (
                <li key={entry.code} className="detail__code-row">
                  <span className="code detail__code">{entry.code}</span>
                  {!entry.verified && (
                    <span className="blocker">not confirmed by Shopify</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Where her money goes</h2>
          </div>
          {detail.payout_destination === null ? (
            <p className="empty">Nothing on file. She cannot be paid yet.</p>
          ) : (
            <dl className="detail__list">
              <Row label="Method">
                {METHOD[detail.payout_destination.method] ??
                  detail.payout_destination.method}
              </Row>
              {detail.payout_destination.bank_name && (
                <Row label="Bank">{detail.payout_destination.bank_name}</Row>
              )}
              {detail.payout_destination.bank_account_holder && (
                <Row label="Account holder">
                  {detail.payout_destination.bank_account_holder}
                </Row>
              )}
              {detail.payout_destination.instapay_address_url && (
                <Row label="Address">
                  <span className="code">
                    {detail.payout_destination.instapay_address_url}
                  </span>
                </Row>
              )}
              {detail.payout_destination.bank_account_number && (
                <Row label="Account number">
                  <span className="code">
                    {detail.payout_destination.bank_account_number}
                  </span>
                </Row>
              )}
              {detail.payout_destination.instapay_phone && (
                <Row label="InstaPay number">
                  <span className="code">
                    {detail.payout_destination.instapay_phone}
                  </span>
                  <span className="detail__note">
                    Used when the app does not open
                  </span>
                </Row>
              )}
              {detail.payout_destination.wallet_phone && (
                <Row label="Wallet number">
                  <span className="code">
                    {detail.payout_destination.wallet_phone}
                  </span>
                </Row>
              )}
              {/*
               * §6.4.4 and ADR 0028. Shortened here on purpose — this is the
               * screen somebody leaves open while doing something else, and a
               * page of full account numbers is a different object from a page
               * of masked ones. The number needed to actually send money is
               * revealed on the payment screen, one at a time and recorded.
               */}
              <p className="detail__masked">
                {detail.payout_destination.method === "instapay"
                  ? "Shortened on purpose. Paying opens InstaPay with her address filled in, and shows her number beside it for when the app does not open."
                  : "Shortened on purpose. The full number is shown on the payment screen, when you are about to send the money."}
              </p>
            </dl>
          )}
        </section>
      </div>
    </>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="detail__row">
      <dt className="detail__label">{label}</dt>
      <dd className="detail__value">{children}</dd>
    </div>
  );
}
