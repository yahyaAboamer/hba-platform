import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Money } from "../components/Money";
import { api, can } from "../lib/api";
import type { Session } from "../lib/api";
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
 * One model, and everything true about them this month.
 *
 * Read-only for now. The pages that *change* what they are paid — their rate, their
 * discount code, where their money goes — each get their own page with a "what
 * this changes" preview, and those are the next screens after this one (§12.2
 * calls them Pattern C: money decisions never happen in a small dialog).
 */
export function AffiliateDetail({ session }: { session: Session }) {
  const { id } = useParams();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [earnings, setEarnings] = useState<Earnings | null>(null);
  const [error, setError] = useState<string | null>(null);
  // A message and whether it is good news. The two used to be separate, and
  // the news was always rendered green - so "Shopify has never heard of this
  // code", which is the worst answer the check can give, arrived in the colour
  // reserved for something having gone right.
  const [notice, setNotice] = useState<{ text: string; good: boolean } | null>(
    null,
  );
  const [working, setWorking] = useState<string | null>(null);
  const [correction, setCorrection] = useState("");

  function load() {
    setError(null);
    api
      .get<Detail>(`/api/affiliates/${id}`)
      .then((body) => {
        setDetail(body);
        setCorrection("");
        return api.get<Earnings>(
          `/api/affiliates/${id}/earnings/${body.current_month}`,
        );
      })
      .then(setEarnings)
      .catch((caught) => setError(caught.message));
  }

  useEffect(load, [id]);

  /**
   * §10.4's gate, from the maintainer's side. Asks Shopify whether the code
   * this model applied with actually exists.
   *
   * A typo is corrected here rather than anywhere else: `recheck-code`
   * rewrites the unverified period instead of opening a second one, because
   * a code Shopify never confirmed attributed nothing, and leaving the wrong
   * one behind would keep it holding ownership that blocks the right person
   * from claiming it.
   */
  async function verifyCode() {
    setWorking("code");
    setError(null);
    setNotice(null);
    try {
      const result = await api.post<{ verified: boolean; code: string }>(
        `/api/affiliates/${id}/recheck-code`,
        correction.trim() ? { code: correction.trim() } : {},
      );
      setNotice({
        good: result.verified,
        text: result.verified
          ? `Shopify knows ${result.code}. You can approve now.`
          : `Shopify has never heard of ${result.code}. Check it against the shop.`,
      });
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not check it.");
    } finally {
      setWorking(null);
    }
  }

  async function approve() {
    setWorking("approve");
    setError(null);
    setNotice(null);
    try {
      await api.patch(`/api/affiliates/${id}`, { status: "active" });
      setNotice({
        good: true,
        text: "Approved. Sales on this code are being counted.",
      });
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not approve.");
    } finally {
      setWorking(null);
    }
  }

  // **Only a failure to load replaces the page.** An action that fails - a
  // Shopify check against a shop that is not configured, an approval the
  // server refuses - used to hit this same branch and wipe the record the
  // person was looking at, leaving them to navigate back and find them again.
  // A failed action is reported in place, with everything it failed against
  // still on screen.
  if (error && !detail) {
    return (
      <p className="notice notice--refused" role="alert">
        {error}
      </p>
    );
  }

  if (!detail) return <p className="empty">Loading…</p>;

  const verified = detail.codes.some((entry) => entry.verified);

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
      {/*
       * Only where the panel below is not already saying it. On a pending
       * affiliate the *Before they can earn* list carries the same fact with
       * the button to fix it attached, and saying it twice - once at length -
       * was the first thing the business objected to on this page.
       */}
      {detail.status !== "archived" &&
        detail.status !== "pending" &&
        !detail.codes.some((entry) => entry.verified) && (
          <p className="notice notice--refused detail__warning">
            {detail.codes.length === 0
              ? `No discount code registered. Orders using one will belong to nobody.`
              : "Shopify has not confirmed this code exists."}
          </p>
        )}

      {error && (
        <p className="notice notice--refused detail__warning" role="alert">
          {error}
        </p>
      )}

      {/*
       * **A refusal must not outlive the thing it refused.**
       *
       * `notice` is state that survives until something replaces it; `verified`
       * is read from the record every time it reloads. So a red "Shopify has
       * never heard of HBA15" could still be on screen while the checklist
       * below it said "Shopify knows HBA15" - the platform contradicting
       * itself in two places a centimetre apart, caught in the M1 walkthrough.
       *
       * The record wins. A bad notice is dropped the moment the code is
       * actually verified; a good one stays, because it is the confirmation
       * somebody just asked for.
       */}
      {notice && !(verified && !notice.good) && (
        <p
          className={
            notice.good
              ? "notice notice--settled detail__warning"
              : "notice notice--refused detail__warning"
          }
        >
          {notice.text}
        </p>
      )}

      {/*
       * §13 step 4. The maintainer's side of an application: what is still
       * missing before they can earn, and the action for each.
       *
       * Deliberately **not** a separate Applications list. The Affiliates
       * screen already answers "who is waiting" and flags exactly these two
       * gaps on their row; a second list would be the same question asked twice
       * and one more place to keep in step. This is the page somebody already
       * lands on from there.
       */}
      {detail.status === "pending" && can(session, "affiliates.manage") && (
        <section className="panel detail__review">
          <div className="panel__head">
            <h2 className="panel__title">Before {detail.name} can earn</h2>
          </div>

          <ol className="detail__steps">
            <li className={verified ? "detail__step--done" : undefined}>
              <div>
                <strong>Check the code against Shopify</strong>
                <span className="detail__note">
                  {verified
                    ? `Shopify knows ${detail.codes[0]?.code}.`
                    : "A code the shop has never heard of earns nothing, silently."}
                </span>
              </div>
              {!verified && (
                <div className="detail__step-action">
                  <input
                    className="input detail__correction"
                    value={correction}
                    onChange={(event) => setCorrection(event.target.value)}
                    placeholder={detail.codes[0]?.code ?? "Discount code"}
                    aria-label="Correct the code before checking"
                  />
                  <button
                    type="button"
                    className="button"
                    onClick={verifyCode}
                    disabled={working !== null}
                  >
                    {working === "code" ? "Asking Shopify…" : "Check it"}
                  </button>
                </div>
              )}
            </li>

            <li className={detail.compensation ? "detail__step--done" : undefined}>
              <div>
                <strong>Set what {detail.name} is paid</strong>
                <span className="detail__note">
                  {detail.compensation
                    ? "The arrangement is recorded."
                    : "Payroll stays blocked until this is set."}
                </span>
              </div>
              <Link className="button" to={`/affiliates/${detail.id}/compensation`}>
                {detail.compensation ? "Change it" : "Set it"}
              </Link>
            </li>

            <li>
              <div>
                <strong>Set the targets</strong>
                <span className="detail__note">
                  {detail.compensation?.compensation_type === "base_guarantee" ? (
                    <>
                      The{" "}
                      <Link
                        to="/glossary#guaranteed-minimum"
                        className="glossary-link"
                      >
                        guaranteed minimum
                      </Link>{" "}
                      applies only in a month where these are met and confirmed.
                    </>
                  ) : (
                    <>
                      Recorded only. Targets change pay on a{" "}
                      <Link
                        to="/glossary#guaranteed-minimum"
                        className="glossary-link"
                      >
                        guaranteed minimum
                      </Link>
                      .
                    </>
                  )}
                </span>
              </div>
              <Link className="button" to="/targets">
                Open targets
              </Link>
            </li>
          </ol>

          {/*
           * The gate is `set_status`, server-side, and it raises on an
           * unverified code. Showing it here means the maintainer sees why
           * before pressing rather than meeting a refusal after.
           */}
          <div className="payroll__actions">
            <button
              type="button"
              className="button button--primary"
              onClick={approve}
              disabled={working !== null || !verified}
            >
              {working === "approve"
                ? "Approving…"
                : verified
                  ? `Approve ${detail.name}`
                  : "Check the code first"}
            </button>
          </div>
        </section>
      )}

      <div className="detail__grid">
        {/*
         * Not before they are approved. A pending affiliate has no terms, so
         * this panel could only ever show zero owed and "no pay terms for this
         * month" - an answer to a question nobody is asking yet, on a page
         * whose whole job at that point is the list of things still to do.
         *
         * The business put it plainly: *what creates the model is setting her
         * up, not her registering.* Quoted as said; it is true of any model.
         */}
        {detail.status !== "pending" && (
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

        )}

        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">How {detail.name} is paid</h2>
          </div>
          {detail.compensation === null ? (
            <p className="empty">
              No pay terms for {formatMonth(detail.current_month)}, so nothing
              can be calculated. Sales are still recorded.
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
                    Applies only when targets are met and confirmed
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
            <h2 className="panel__title">What has been paid</h2>
            <Link className="button" to={`/affiliates/${detail.id}/payments`}>
              Open the history
            </Link>
          </div>
          {/*
           * Deliberately a link and not a summary. "What has this person ever
           * been sent" is asked rarely and answered at length - every payment,
           * its reference, where it went and the screenshot - and putting the
           * first two rows here would answer it wrongly more often than it
           * answered it at all.
           */}
          <p className="empty">
            Every payment and adjustment, with the screenshots.
          </p>
        </section>

        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Discount codes</h2>
          </div>
          {detail.codes.length === 0 ? (
            <p className="empty">
              None registered for {formatMonth(detail.current_month)}.
            </p>
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

          {can(session, "affiliates.manage") && (
            <CodeForm
              affiliateId={detail.id}
              held={detail.codes}
              onDone={load}
            />
          )}
        </section>

        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Where the money goes</h2>
            {can(session, "affiliates.manage") && (
              <Link
                className="button"
                to={`/affiliates/${detail.id}/payout-destination`}
              >
                {detail.payout_destination ? "Correct it" : "Set it"}
              </Link>
            )}
          </div>
          {detail.payout_destination === null ? (
            <p className="empty">
              Nothing on file. {detail.name} cannot be paid yet.
            </p>
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
                  ? "Shortened on purpose. Pay from Payments, which opens InstaPay with the address filled in."
                  : "Shortened on purpose. Pay from Payments, where the full number is shown."}
              </p>
            </dl>
          )}
        </section>
      </div>
    </>
  );
}

/**
 * Giving a model a code, and moving them onto a different one.
 *
 * **Two acts that produce the same typing and mean opposite things.** Adding
 * leaves the old code earning; moving ends it the month before the new one
 * began. Get it wrong in the *adding* direction and a retired code keeps
 * collecting orders it should not; wrong in the *moving* direction and months
 * of real sales stop belonging to anybody. Neither is recoverable by guessing
 * later, so the screen asks - and asks only when there is something to move
 * away from.
 *
 * **No month is asked for anywhere here, deliberately.** There is exactly one
 * right answer - the later of the platform's data horizon and the code's
 * creation on Shopify - so offering a person the choice can only produce a
 * wrong one. Typing today's month would orphan every order the code had
 * already earned, and nobody would notice until the model asked why their
 * dashboard was empty.
 */
function CodeForm({
  affiliateId,
  held,
  onDone,
}: {
  affiliateId: number;
  held: Code[];
  onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [moving, setMoving] = useState(true);
  const [replaces, setReplaces] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  const first = held.length === 0;
  // `replaces` only disambiguates. With one code there is nothing to choose
  // between, and asking would be noise.
  const mustChoose = moving && held.length > 1;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    try {
      if (!first && moving) {
        await api.post(`/api/affiliates/${affiliateId}/replace-code`, {
          code: code.trim(),
          replaces: mustChoose ? replaces : null,
        });
      } else {
        await api.post(`/api/affiliates/${affiliateId}/codes`, {
          code: code.trim(),
        });
      }
      setCode("");
      setOpen(false);
      onDone();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save that.");
    } finally {
      setWorking(false);
    }
  }

  if (!open) {
    return (
      <div className="detail__step-action">
        <button type="button" className="button" onClick={() => setOpen(true)}>
          {first ? "Register a code" : "Register or change a code"}
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="detail__code-form">
      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {!first && (
        <fieldset className="comp__choice">
          <legend className="field__label">Which is this?</legend>
          <label className={moving ? "pay__option pay__option--on" : "pay__option"}>
            <input
              type="radio"
              name="code-act"
              checked={moving}
              onChange={() => setMoving(true)}
            />
            <span className="pay__option-body">
              <strong>They changed their code on Shopify</strong>
              <span className="detail__note">
                The old one ends the month before this one started. Their
                earlier months keep showing it, and the orders it earned stay
                theirs.
              </span>
            </span>
          </label>
          <label className={!moving ? "pay__option pay__option--on" : "pay__option"}>
            <input
              type="radio"
              name="code-act"
              checked={!moving}
              onChange={() => setMoving(false)}
            />
            <span className="pay__option-body">
              <strong>They sell under this one as well</strong>
              <span className="detail__note">
                Both codes stay live and both earn.
              </span>
            </span>
          </label>
        </fieldset>
      )}

      {mustChoose && (
        <label className="field comp__field">
          <span className="field__label">Which code are they leaving?</span>
          <select
            className="input"
            value={replaces}
            onChange={(event) => setReplaces(event.target.value)}
            required
          >
            <option value="">Choose one</option>
            {held.map((entry) => (
              <option key={entry.code} value={entry.code}>
                {entry.code}
              </option>
            ))}
          </select>
        </label>
      )}

      <label className="field comp__field">
        <span className="field__label">The code</span>
        <input
          className="input"
          value={code}
          onChange={(event) => setCode(event.target.value)}
          placeholder="NOUR10"
          required
        />
        <span className="detail__note">
          Shopify is asked about it now. That one answer settles both whether it
          exists and which month it starts earning from, so no month is asked
          for here. A code Shopify has never heard of is still recorded - it
          just cannot be approved until Shopify has it.
        </span>
      </label>

      <div className="payroll__actions">
        <button
          type="button"
          className="button"
          onClick={() => {
            setOpen(false);
            setError(null);
          }}
          disabled={working}
        >
          Cancel
        </button>
        <button
          type="submit"
          className="button button--primary"
          disabled={working || code.trim() === "" || (mustChoose && replaces === "")}
        >
          {working
            ? "Asking Shopify…"
            : first || !moving
              ? "Register it"
              : "Move them onto it"}
        </button>
      </div>
    </form>
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
