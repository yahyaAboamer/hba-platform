import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Money } from "../components/Money";
import { MonthPicker } from "../components/MonthPicker";
import { api } from "../lib/api";
import { egpPlain, formatMonth, parseEgp } from "../lib/money";
import type { Affiliate } from "./Affiliates";
import "./Payroll.css";
import "./Compensation.css";

type Compensation = {
  start_month: string;
  end_month: string | null;
  compensation_type: Kind;
  commission_rate_bp: number;
  fixed_amount_piastres: number | null;
  base_amount_piastres: number | null;
  expected_customer_discount_bp: number | null;
};

type Detail = Affiliate & {
  current_month: string;
  compensation: Compensation | null;
};

type Kind = "commission" | "fixed_plus_commission" | "base_guarantee";

const KIND_LABEL: Record<Kind, string> = {
  commission: "Commission only",
  fixed_plus_commission: "Salary plus commission",
  base_guarantee: "Guaranteed minimum",
};

const KIND_MEANING: Record<Kind, string> = {
  commission: "A share of what the code sells, and nothing else.",
  fixed_plus_commission:
    "A fixed amount every month, and commission on top of it.",
  base_guarantee:
    "Whichever is larger — commission, or the guaranteed amount. Never both. The guarantee only applies in a month where targets were met and confirmed.",
};

/**
 * Setting what an affiliate is paid on. §12.2's Pattern C: its own page, its
 * own URL, and a mandatory "what this changes" preview.
 *
 * This is the one screen in the platform that had no interface at all until
 * now — the endpoint has existed since Phase 3 and nothing called it, so a
 * model could be approved and then sit on the payroll screen blocked on
 * *no pay terms* forever, with no way to resolve it.
 *
 * **A rate change is a new period, never an edit.** The database refuses two
 * periods that overlap, so the months they were on 8% cannot later become months
 * they were on 10%. That is enforced server-side; this page exists to make it
 * legible before it is committed.
 */
export function Compensation() {
  const { id = "" } = useParams();
  const navigate = useNavigate();

  const [detail, setDetail] = useState<Detail | null>(null);
  const [kind, setKind] = useState<Kind>("commission");
  const [rate, setRate] = useState("10");
  const [fixed, setFixed] = useState("");
  const [base, setBase] = useState("");
  const [discount, setDiscount] = useState("");
  const [startMonth, setStartMonth] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  useEffect(() => {
    api
      .get<Detail>(`/api/affiliates/${id}`)
      .then((body) => {
        setDetail(body);
        setStartMonth(body.current_month);
        if (body.compensation) {
          setKind(body.compensation.compensation_type);
          setRate(String(body.compensation.commission_rate_bp / 100));
          if (body.compensation.fixed_amount_piastres !== null) {
            setFixed(egpPlain(body.compensation.fixed_amount_piastres));
          }
          if (body.compensation.base_amount_piastres !== null) {
            setBase(egpPlain(body.compensation.base_amount_piastres));
          }
          if (body.compensation.expected_customer_discount_bp !== null) {
            setDiscount(String(body.compensation.expected_customer_discount_bp / 100));
          }
        }
      })
      .catch((caught) => setError(caught.message));
  }, [id]);

  // Percentages are held as basis points, never as a float. 10% is 1000, and
  // 12.5% is 1250 - the multiply happens on a string, so a rate can never
  // arrive as 1249.9999 (ADR 0002).
  const rateBp = toBasisPoints(rate);
  const discountBp = discount.trim() === "" ? null : toBasisPoints(discount);
  const fixedPiastres = fixed.trim() === "" ? null : parseEgp(fixed);
  const basePiastres = base.trim() === "" ? null : parseEgp(base);

  const problem =
    rateBp === null
      ? "The commission rate needs to be a percentage, like 10 or 12.5."
      : rateBp <= 0 || rateBp > 10_000
        ? "The commission rate has to be above 0% and at most 100%."
        : kind === "fixed_plus_commission" && !fixedPiastres
          ? "A salary-plus-commission arrangement needs a salary."
          : kind === "base_guarantee" && !basePiastres
            ? "A guaranteed minimum needs an amount."
            : discount.trim() !== "" && discountBp === null
              ? "The customer discount needs to be a percentage, like 10."
              : null;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (problem) return;
    setWorking(true);
    setError(null);
    try {
      await api.post(`/api/affiliates/${id}/compensation`, {
        start_month: startMonth,
        compensation_type: kind,
        commission_rate_bp: rateBp,
        fixed_amount_piastres: kind === "fixed_plus_commission" ? fixedPiastres : null,
        base_amount_piastres: kind === "base_guarantee" ? basePiastres : null,
        expected_customer_discount_bp: discountBp,
      });
      navigate(`/affiliates/${id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save that.");
    } finally {
      setWorking(false);
    }
  }

  const head = (
    <div className="page__head">
      <div className="page__title">
        <Link to={`/affiliates/${id}`} className="detail__back">
          {detail?.name ?? "Affiliate"}
        </Link>
        <h1>How {detail?.name ?? "this model"} is paid</h1>
      </div>
    </div>
  );

  if (detail === null) {
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

  return (
    <>
      {head}

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      <form onSubmit={submit} className="comp__form">
        <fieldset className="comp__choice">
          <legend className="field__label">What is the arrangement?</legend>
          {(Object.keys(KIND_LABEL) as Kind[]).map((option) => (
            <label
              key={option}
              className={
                kind === option ? "pay__option pay__option--on" : "pay__option"
              }
            >
              <input
                type="radio"
                name="kind"
                checked={kind === option}
                onChange={() => setKind(option)}
              />
              <span className="pay__option-body">
                <strong>{KIND_LABEL[option]}</strong>
                <span className="detail__note">{KIND_MEANING[option]}</span>
              </span>
            </label>
          ))}
        </fieldset>

        <label className="field comp__field">
          <span className="field__label">Commission rate</span>
          <span className="comp__suffixed">
            <input
              className="input"
              inputMode="decimal"
              value={rate}
              onChange={(event) => setRate(event.target.value)}
            />
            <span className="comp__suffix">%</span>
          </span>
          <span className="detail__note">Of what the code sells, after shipping and tax.</span>
        </label>

        {kind === "fixed_plus_commission" && (
          <label className="field comp__field">
            <span className="field__label">Salary, every month</span>
            <input
              className="input"
              inputMode="decimal"
              value={fixed}
              onChange={(event) => setFixed(event.target.value)}
              placeholder="5000.00"
            />
          </label>
        )}

        {kind === "base_guarantee" && (
          <label className="field comp__field">
            <span className="field__label">Guaranteed minimum</span>
            <input
              className="input"
              inputMode="decimal"
              value={base}
              onChange={(event) => setBase(event.target.value)}
              placeholder="8000.00"
            />
            <span className="detail__note">
              Only applies in a month where targets are met and confirmed.
            </span>
          </label>
        )}

        <label className="field comp__field">
          <span className="field__label">Customer discount (optional)</span>
          <span className="comp__suffixed">
            <input
              className="input"
              inputMode="decimal"
              value={discount}
              onChange={(event) => setDiscount(event.target.value)}
              placeholder="10"
            />
            <span className="comp__suffix">%</span>
          </span>
          <span className="detail__note">
            What the code takes off for the customer. Recorded for reference; it
            does not change what is paid.
          </span>
        </label>

        {/*
         * A month, chosen from a calendar. It was a text box accepting any
         * string, which is how "2026-9" or a typed sentence gets as far as the
         * server - and the business asked for the picker every other screen
         * already uses.
         *
         * It also needed saying what it means. *In force from* is when this
         * arrangement starts applying, not when their orders start counting:
         * orders are counted from the month their code was registered, which may
         * be long before. Setting it to September does not hide their August
         * sales; it means August is paid on whatever they were on in August.
         */}
        <div className="field comp__field">
          <span className="field__label">
            {detail.compensation ? "New rate applies from" : "Applies from"}
          </span>
          <MonthPicker value={startMonth} onChange={setStartMonth} />
          <span className="detail__note">
            {detail.compensation
              ? "The months before this keep the current arrangement."
              : "Sales are counted from the month the code was registered, whichever month you choose here."}
          </span>
        </div>

        {/*
         * §12.2 requires this, and it is the reason the page exists rather
         * than a dialog: the figures below are what somebody is actually
         * agreeing to, and they should be readable before the button is
         * pressed rather than inferred from four inputs.
         */}
        <section className="panel approve__summary">
          <h2 className="panel__title">What this changes</h2>

          {problem ? (
            <p className="blocker">{problem}</p>
          ) : (
            <>
              <p className="approve__lead">
                From <strong>{formatMonth(startMonth)}</strong> onwards,{" "}
                {detail.name} is paid{" "}
                <strong>{KIND_LABEL[kind].toLowerCase()}</strong>.
              </p>
              <p className="approve__lead">{KIND_MEANING[kind]}</p>

              <dl className="detail__list comp__summary">
                <Row label="Commission">
                  <span className="code">{(rateBp ?? 0) / 100}%</span> of sales
                </Row>
                {kind === "fixed_plus_commission" && fixedPiastres !== null && (
                  <Row label="Salary">
                    <Money piastres={fixedPiastres} kind="agreed" /> every month
                  </Row>
                )}
                {kind === "base_guarantee" && basePiastres !== null && (
                  <Row label="Guaranteed minimum">
                    <Money piastres={basePiastres} kind="agreed" />
                  </Row>
                )}
                <Row label="On E£10,000 of sales">
                  {/*
                   * A worked example, because a rate is abstract and a figure
                   * is not. This is the number somebody checks the rate
                   * against when they are not sure they typed it right.
                   */}
                  <Money piastres={exampleOn(1_000_000, kind, rateBp, fixedPiastres, basePiastres)} />
                  <span className="detail__note">
                    {kind === "base_guarantee"
                      ? "the larger of commission and the guarantee, if targets were met"
                      : "in a month with no other adjustments"}
                  </span>
                </Row>
              </dl>
            </>
          )}
        </section>

        {detail.compensation && (
          <p className="notice comp__note">
            {detail.name} is currently on{" "}
            <strong>{KIND_LABEL[detail.compensation.compensation_type].toLowerCase()}</strong>{" "}
            at {detail.compensation.commission_rate_bp / 100}%, from{" "}
            {formatMonth(detail.compensation.start_month)}. Saving this ends
            that arrangement and starts a new one — the months already on the
            old rate keep it.
          </p>
        )}

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
            disabled={working || problem !== null}
          >
            {working
              ? "Saving…"
              : `Pay ${detail.name} this from ${formatMonth(startMonth)}`}
          </button>
        </div>
      </form>
    </>
  );
}

/**
 * `"12.5"` → `1250` basis points. Integer arithmetic on the text, never
 * `parseFloat(x) * 100` — that is `1249.9999999999998` for some inputs, and a
 * rate is money by another name (ADR 0002).
 */
function toBasisPoints(text: string): number | null {
  const cleaned = text.trim().replace(/%$/, "").trim();
  if (!/^\d*(\.\d{1,2})?$/.test(cleaned) || cleaned === "" || cleaned === ".") {
    return null;
  }
  const [whole = "0", fraction = ""] = cleaned.split(".");
  return Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
}

function exampleOn(
  salesPiastres: number,
  kind: Kind,
  rateBp: number | null,
  fixedPiastres: number | null,
  basePiastres: number | null,
): number {
  const commission = Math.round((salesPiastres * (rateBp ?? 0)) / 10_000);
  if (kind === "fixed_plus_commission") return commission + (fixedPiastres ?? 0);
  if (kind === "base_guarantee") return Math.max(commission, basePiastres ?? 0);
  return commission;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="detail__row">
      <dt className="detail__label">{label}</dt>
      <dd className="detail__value">{children}</dd>
    </div>
  );
}
