import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../lib/api";
import type { Affiliate } from "./Affiliates";
import { instapayProblem } from "./Apply";
import "./Payroll.css";
import "./Compensation.css";

type Method = "instapay" | "bank" | "wallet";

const METHOD_LABEL: Record<Method, string> = {
  instapay: "InstaPay",
  bank: "Bank transfer",
  wallet: "Mobile wallet",
};

const FIELD_LABEL: Record<string, string> = {
  instapay_address_url: "InstaPay payment address",
  instapay_phone: "InstaPay number",
  bank_name: "Bank",
  bank_account_holder: "Account holder",
  bank_account_number: "Account number",
  wallet_phone: "Wallet number",
};

type Detail = Affiliate & {
  payout_destination: Record<string, string | null> | null;
  required_payout_fields: Record<string, string[]>;
};

/**
 * Correcting where a model's money goes, on their behalf.
 *
 * **A fallback, and it says so.** §6.4 gives this to the model: it is their
 * money and their screen, and them doing it is the path that needs no trust.
 * This exists for the model who cannot reach that screen — a lost password
 * before payroll, an account that never got set up — because they still have
 * to be paid.
 *
 * It is also, unavoidably, the one place in the platform where one person can
 * move another person's money. What keeps that honest is not a confirmation
 * dialog, which only slows down the person who meant it: it is that **the
 * model is emailed the moment it happens**, masked, with an instruction to
 * reply before the next payment run. The audit record and the seven-day flag
 * on the payment screen were already there; the mail to the owner of the money
 * was the piece missing, and it was added with this screen rather than after.
 *
 * Its own page, per §12.2's Pattern C, for the same reason the compensation
 * screen is: the thing being changed is money, and it should be readable in
 * full before it is committed rather than typed into a corner of another page.
 */
export function AffiliatePayout() {
  const { id = "" } = useParams();
  const navigate = useNavigate();

  const [detail, setDetail] = useState<Detail | null>(null);
  const [method, setMethod] = useState<Method>("instapay");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  useEffect(() => {
    api
      .get<Detail>(`/api/affiliates/${id}`)
      .then((body) => {
        setDetail(body);
        if (body.payout_destination?.method) {
          setMethod(body.payout_destination.method as Method);
        }
      })
      .catch((caught) => setError(caught.message));
  }, [id]);

  const needed = detail?.required_payout_fields[method] ?? [];
  const addressProblem =
    method === "instapay"
      ? instapayProblem(fields.instapay_address_url ?? "")
      : null;
  const missing = needed.some((field) => !(fields[field] ?? "").trim());

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (missing || addressProblem) return;
    setWorking(true);
    setError(null);
    try {
      await api.put(`/api/affiliates/${id}/payout-destination`, {
        method,
        instapay_address_url: fields.instapay_address_url ?? null,
        instapay_phone: fields.instapay_phone ?? null,
        bank_name: fields.bank_name ?? null,
        bank_account_holder: fields.bank_account_holder ?? null,
        bank_account_number: fields.bank_account_number ?? null,
        wallet_phone: fields.wallet_phone ?? null,
      });
      navigate(`/affiliates/${id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save that.");
    } finally {
      setWorking(false);
    }
  }

  if (error && detail === null) {
    return (
      <p className="notice notice--refused" role="alert">
        {error}
      </p>
    );
  }
  if (detail === null) return <p className="empty">Loading…</p>;

  const changing = detail.payout_destination !== null;

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <Link to={`/affiliates/${id}`} className="detail__back">
            {detail.name}
          </Link>
          <h1>Where {detail.name} is paid</h1>
        </div>
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {/*
       * Said before the form, not after it. Somebody who should not be here
       * ought to find that out before they have typed an account number, and
       * somebody who should be here is owed the plain fact that the model will
       * be told.
       */}
      <p className="notice comp__note">
        {changing ? (
          <>
            {detail.name} can change this themselves, and normally should — it
            is their money and their screen. Use this when they cannot reach it.
            <strong> They are emailed as soon as you save</strong>, and the
            payments screen flags the change for seven days.
          </>
        ) : (
          <>
            Nothing is on file yet, so {detail.name} cannot be paid. Setting the
            first one here is not treated as a change and raises no warning —
            normally it arrives with their application.
          </>
        )}
      </p>

      <form onSubmit={submit} className="comp__form">
        <fieldset className="comp__choice">
          <legend className="field__label">How are they paid?</legend>
          {(Object.keys(METHOD_LABEL) as Method[]).map((option) => (
            <label
              key={option}
              className={
                method === option ? "pay__option pay__option--on" : "pay__option"
              }
            >
              <input
                type="radio"
                name="method"
                checked={method === option}
                onChange={() => setMethod(option)}
              />
              <span className="pay__option-body">
                <strong>{METHOD_LABEL[option]}</strong>
              </span>
            </label>
          ))}
        </fieldset>

        {needed.map((field) => (
          <label key={field} className="field comp__field">
            <span className="field__label">{FIELD_LABEL[field] ?? field}</span>
            <input
              className="input"
              value={fields[field] ?? ""}
              onChange={(event) =>
                setFields({ ...fields, [field]: event.target.value })
              }
              required
            />
            {field === "instapay_address_url" && addressProblem && (
              <span className="blocker">{addressProblem}</span>
            )}
          </label>
        ))}

        <div className="payroll__actions">
          <button
            type="button"
            className="button"
            onClick={() => navigate(`/affiliates/${id}`)}
            disabled={working}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="button button--primary"
            disabled={working || missing || addressProblem !== null}
          >
            {working
              ? "Saving…"
              : changing
                ? `Move ${detail.name}'s payments here`
                : "Save it"}
          </button>
        </div>
      </form>
    </>
  );
}
