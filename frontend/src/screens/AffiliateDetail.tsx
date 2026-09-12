import { useEffect, useState, useRef } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { MonthPicker } from "../components/MonthPicker";
import { Targets } from "./Targets";
import { Money } from "../components/Money";
import { Corrections } from "../components/Corrections";
import { FinancialRulesPreview } from "../components/FinancialRulesPreview";
import { api, can } from "../lib/api";
import { PAYOUT_FIELD_LABEL, PAY_TYPE } from "../lib/payouts";
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

/** Where HBA sends her things (D11). Staff read *and* write it. */
type Shipping = {
  shipping_name: string | null;
  shipping_phone: string | null;
  shipping_line1: string | null;
  shipping_line2: string | null;
  shipping_city: string | null;
  shipping_governorate: string | null;
  shipping_notes: string | null;
};

type WardrobeItem = {
  shopify_product_id: string | null;
  title: string;
  size: string | null;
  state: string;
  image_url: string | null;
  image_thumb_url: string | null;
  shopify_order_id: string;
};

type Detail = Affiliate & {
  shipping: Shipping;
  current_month: string;
  /** Which month `compensation` and `codes` below actually describe. */
  terms_month: string;
  platform_start_month: string;
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
  const [query, setQuery] = useSearchParams();
  const section = ["overview", "wardrobe", "performance", "targets", "payments"].includes(query.get("section") ?? "") ? query.get("section")! : "overview";
  const [month, setMonth] = useState(query.get("month")?.match(/^\d{4}-(0[1-9]|1[0-2])$/) ? query.get("month")! : session.platform.working_month);
  const [wardrobeError, setWardrobeError] = useState<string | null>(null);
  const [wardrobeReload, setWardrobeReload] = useState(0);
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
  /**
   * A draft, not the value. `null` means "not editing" - so the field shows
   * what is recorded until somebody deliberately opens it, and Cancel puts
   * back what the server said rather than what was typed (M03's rule, applied
   * here because it is the same failure either side of the platform).
   */
  const [startDraft, setStartDraft] = useState<string | null>(null);
  /**
   * The address, as a draft. `null` means "not editing", so Cancel puts back
   * what the server said rather than what was typed last time.
   */
  const [shipDraft, setShipDraft] = useState<Shipping | null>(null);
  /** What HBA has sent her. The same records her own screen reads (W08). */
  const [wardrobe, setWardrobe] = useState<{
    received: WardrobeItem[];
    processing: WardrobeItem[];
    failed: WardrobeItem[];
  } | null>(null);

  const loadVersion = useRef(0);
  function load() {
    const version = ++loadVersion.current;
    setEarnings(null);
    setError(null);
    api
      // The selected month goes with the request: terms are dated, and a
      // profile answering March with September's arrangement puts the wrong
      // rate beside March's earnings.
      .get<Detail>(`/api/affiliates/${id}?month=${month}`)
      .then((body) => {
        if (version !== loadVersion.current) return;
        setDetail(body);
        setCorrection("");
        return api.get<Earnings>(
          `/api/affiliates/${id}/earnings/${month}`,
        );
      })
      .then(value => { if (version === loadVersion.current && value) setEarnings(value); })
      .catch((caught) => { if (version === loadVersion.current) setError(caught.message); });
  }

  useEffect(load, [id, month]);

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

  async function saveStartMonth() {
    setWorking("start");
    setError(null);
    setNotice(null);
    try {
      // `_set` distinguishes "clear it" from "not supplied". Sending an empty
      // month without it would be indistinguishable from a request that never
      // mentioned the field, and clearing a recorded start is a real answer.
      await api.patch(`/api/affiliates/${id}`, {
        collaboration_start_month: startDraft?.trim() ? startDraft.trim() : null,
        collaboration_start_month_set: true,
      });
      setStartDraft(null);
      setNotice({
        good: true,
        text: startDraft?.trim()
          ? "Recorded. This is the first month she can open."
          : "Cleared. Her months fall back to her earliest order again.",
      });
      load();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not save that month.",
      );
    } finally {
      setWorking(null);
    }
  }

  useEffect(() => {
    let live = true;
    setWardrobe(null);
    setWardrobeError(null);
    api
      .get<{
        received: WardrobeItem[];
        processing: WardrobeItem[];
        failed: WardrobeItem[];
      }>(`/api/affiliates/${id}/wardrobe`)
      .then((body) => {
        if (live) setWardrobe(body);
      })
      .catch((caught) => { if (live) setWardrobeError(caught.message); });
    return () => {
      live = false;
    };
  }, [id, wardrobeReload]);

  async function saveShipping() {
    if (!shipDraft) return;
    setWorking("shipping");
    setError(null);
    setNotice(null);
    try {
      await api.patch(`/api/affiliates/${id}`, { shipping: shipDraft });
      setShipDraft(null);
      setNotice({ good: true, text: "Saved. This is what goes on her parcels." });
      load();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not save that.",
      );
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
  /**
   * The code she sells under **now** — the open-ended one, or the last
   * registered if every period has closed. A hero that listed every code she
   * has ever held would bury the one an order arriving today would match.
   */
  const current =
    detail.codes.find((entry) => entry.end_month === null) ??
    detail.codes[detail.codes.length - 1];
  const appliedOn = detail.created_at
    ? new Date(detail.created_at).toLocaleDateString("en-GB", {
        day: "numeric",
        month: "long",
        year: "numeric",
      })
    : null;

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <Link to="/affiliates" className="detail__back">
            ← Models
          </Link>
        </div>
      </div>

      {/*
       * The approved profile's hero: who this is, at a glance, before any of
       * the sections. Her initial, her name, the state she is in, and the code
       * an order knows her by — the same four things the roster row carries,
       * so arriving from that row does not feel like arriving somewhere else.
       */}
      <header className="detail__hero">
        <span className="detail__hero-avatar" aria-hidden="true">
          {detail.name.charAt(0).toUpperCase()}
        </span>
        <div className="detail__hero-who">
          <h1>{detail.name}</h1>
          <div className="detail__hero-facts">
            <span className={`state state--${detail.status}`}>
              {STATUS_LABEL[detail.status]}
            </span>
            {/* The code she sells under now. A profile that showed every code
             *  she has ever held would bury the one that matters today. */}
            {current ? (
              <span className="code">{current.code}</span>
            ) : (
              <span className="detail__hero-nocode">No code yet</span>
            )}
            {detail.status === "pending" && appliedOn && (
              <span className="detail__hero-applied">Applied {appliedOn}</span>
            )}
          </div>
        </div>
      </header>

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

      <div className="profile__navigation">
        <nav className="profile__tabs" aria-label="Model sections">
          {["Overview", "Wardrobe", "Performance", "Targets", "Payments"].map(label => <button key={label} type="button"
            className={section === label.toLowerCase() ? "profile__tab profile__tab--active" : "profile__tab"}
            aria-current={section === label.toLowerCase() ? "page" : undefined}
            onClick={() => setQuery(previous => { const next = new URLSearchParams(previous); next.set("section", label.toLowerCase()); next.set("month", month); return next; })}>{label}</button>)}
        </nav>
        {["performance", "targets", "payments"].includes(section) && <MonthPicker value={month} onChange={setMonth} />}
      </div>
      <div className="detail__grid">
        {section === "overview" && <>
        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Contact and shipping</h2>
          </div>
          <dl className="detail__list">
            <Row label="Started with HBA">
              {startDraft === null ? (
                <>
                  {detail.collaboration_start_month ? (
                    <span className="code">
                      {formatMonth(detail.collaboration_start_month)}
                    </span>
                  ) : (
                    <span className="detail__note">Not recorded</span>
                  )}
                  {can(session, "affiliates.manage") && (
                    <button
                      type="button"
                      className="button detail__start-edit"
                      onClick={() =>
                        setStartDraft(detail.collaboration_start_month ?? "")
                      }
                    >
                      {detail.collaboration_start_month ? "Change" : "Record it"}
                    </button>
                  )}
                  {/*
                   * Said plainly rather than left to be inferred from a blank.
                   * An empty month here does not mean she has no history - it
                   * means the platform is guessing from her earliest order,
                   * which is a different fact and is usually but not always
                   * the same one.
                   */}
                  {!detail.collaboration_start_month && (
                    <span className="detail__note">
                      Her months are being worked out from her earliest order.
                      That is a good guess and a different fact — a month she
                      was here for and sold nothing in is missing from it.
                    </span>
                  )}
                </>
              ) : (
                <>
                  <input
                    className="input detail__start-input"
                    type="month"
                    value={startDraft}
                    min={detail.platform_start_month}
                    max={detail.current_month}
                    onChange={(event) => setStartDraft(event.target.value)}
                    aria-label="The month she started with HBA"
                  />
                  <span className="detail__step-action">
                    <button
                      type="button"
                      className="button button--primary"
                      disabled={working === "start"}
                      onClick={saveStartMonth}
                    >
                      {working === "start" ? "Saving…" : "Save"}
                    </button>
                    <button
                      type="button"
                      className="button"
                      disabled={working === "start"}
                      onClick={() => setStartDraft(null)}
                    >
                      Cancel
                    </button>
                  </span>
                  <span className="detail__note">
                    The month she actually started, not when her code was made
                    or when she signed up. Months before it are not offered to
                    her; months after it are, even the ones she sold nothing in.
                  </span>
                </>
              )}
            </Row>
            <Row label="Phone">
              {detail.phone ? (
                <span className="code">{detail.phone}</span>
              ) : (
                <span className="detail__note">Not given</span>
              )}
            </Row>
            {/*
             * **"Signs in with"**, not "Email" (D07, 9 September 2026). She
             * has one address: it is her login and it is how marketing reaches
             * her (A05). Naming it plainly is the whole of what that decision
             * costs - a field called "email" on a profile is one somebody
             * eventually edits as a contact detail, and what they have
             * actually done is move her login.
             */}
            <Row label="Signs in with">
              <span className="code">{detail.email}</span>
            </Row>
            {/*
             * **Staff write this one** (D11), unlike the measurements below.
             * It is what somebody types into an order, and a model who has
             * moved should not be a parcel that cannot be sent.
             *
             * On the profile and not in the directory: a list of twenty models
             * does not need twenty home addresses to render a table of names.
             */}
            <Row label="Parcels go to">
              {shipDraft === null ? (
                <>
                  {detail.shipping.shipping_line1 ? (
                    <span className="detail__address">
                      {[
                        detail.shipping.shipping_name,
                        detail.shipping.shipping_line1,
                        detail.shipping.shipping_line2,
                        detail.shipping.shipping_city,
                        detail.shipping.shipping_governorate,
                      ]
                        .filter(Boolean)
                        .join(", ")}
                      {detail.shipping.shipping_phone && (
                        <>
                          {" · "}
                          <span className="code">
                            {detail.shipping.shipping_phone}
                          </span>
                        </>
                      )}
                    </span>
                  ) : (
                    <span className="detail__note">
                      Not recorded. Without it a parcel sent to her cannot be
                      matched back to her wardrobe.
                    </span>
                  )}
                  {can(session, "affiliates.manage") && (
                    <button
                      type="button"
                      className="button detail__start-edit"
                      onClick={() => setShipDraft({ ...detail.shipping })}
                    >
                      {detail.shipping.shipping_line1 ? "Change" : "Record it"}
                    </button>
                  )}
                </>
              ) : (
                <div className="detail__address-form">
                  {(
                    [
                      ["shipping_name", "Name on the parcel"],
                      ["shipping_phone", "Phone on the parcel"],
                      ["shipping_line1", "Street and number"],
                      ["shipping_line2", "Flat, floor (optional)"],
                      ["shipping_city", "Area"],
                      ["shipping_governorate", "Governorate"],
                      ["shipping_notes", "Anything the courier needs"],
                    ] as [keyof Shipping, string][]
                  ).map(([field, label]) => (
                    <label key={field} className="field">
                      <span className="field__label">{label}</span>
                      <input
                        className="input"
                        value={shipDraft[field] ?? ""}
                        onChange={(event) =>
                          setShipDraft({
                            ...shipDraft,
                            [field]: event.target.value,
                          })
                        }
                      />
                    </label>
                  ))}
                  <span className="detail__step-action">
                    <button
                      type="button"
                      className="button button--primary"
                      disabled={working === "shipping"}
                      onClick={saveShipping}
                    >
                      {working === "shipping" ? "Saving…" : "Save"}
                    </button>
                    <button
                      type="button"
                      className="button"
                      disabled={working === "shipping"}
                      onClick={() => setShipDraft(null)}
                    >
                      Cancel
                    </button>
                  </span>
                </div>
              )}
            </Row>
            {/*
             * Read, never written here. A05 gives these to the model alone,
             * and the enforcement is that no staff route can write them - so
             * there is deliberately no control beside them, not a disabled one.
             */}
          </dl>
        </section>

        {/* Sizing is its own panel in the export, and says plainly why it
         *  cannot be edited here. An absent control only tells somebody that
         *  nothing happens when they look for one. */}
        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Sizing</h2>
          </div>
          <dl className="detail__list">
            <Row label="Height">
              {detail.height_cm
                ? <span className="code">{detail.height_cm} cm</span>
                : <span className="detail__note">Not given</span>}
            </Row>
            <Row label="Weight">
              {detail.weight_kg
                ? <span className="code">{detail.weight_kg} kg</span>
                : <span className="detail__note">Not given</span>}
            </Row>
          </dl>
          <p className="detail__note detail__sizing-note">
            Only the model can change these.
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
        </>}
        {section === "wardrobe" && <div className="profile__wardrobe">
          {wardrobeError && <p className="notice notice--refused" role="alert">{wardrobeError} <button className="button" onClick={() => setWardrobeReload(n => n + 1)}>Retry</button></p>}
          {!wardrobe && !wardrobeError && <p className="empty">Loading wardrobe…</p>}
          {wardrobe && [["Received", wardrobe.received], ["Processing", wardrobe.processing], ["Needs checking", wardrobe.failed]].map(([label, list]) => <section key={label as string} className="profile__wardrobe-group">
            <h2>{label as string} <span className="page__subtitle">{(list as WardrobeItem[]).length}</span></h2>
            {(list as WardrobeItem[]).length === 0 ? <p className="empty">No products.</p> : <div className="profile__products">
              {(list as WardrobeItem[]).map((item, index) => <article className="profile__product" key={`${item.shopify_order_id}-${item.shopify_product_id}-${index}`}>
                {item.image_thumb_url || item.image_url ? <img src={item.image_thumb_url || item.image_url!} alt={item.title} loading="lazy" /> : <div className="profile__product-image">Image unavailable</div>}
                {item.shopify_product_id ? <Link to={`/products/${item.shopify_product_id}`}>{item.title}</Link> : <span>{item.title}</span>}
                <small>Size {item.size || "not recorded"}</small>
              </article>)}
            </div>}
          </section>)}
        </div>}
        {section === "performance" && <>
        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">How the month is going</h2>
            <span className="page__subtitle">
              {formatMonth(month)}
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
          <Link className="button" to={`/orders?month=${month}&affiliate=${id}`}>View attributed orders →</Link>
        </>}
        {section === "targets" && <div className="profile__full"><Targets key={`${id}-${month}`} session={session} affiliateId={Number(id)} initialMonth={month} embedded /></div>}
        {section === "payments" && <>
        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">
              Current terms
              {detail.terms_month !== detail.current_month && (
                <span className="page__subtitle"> {formatMonth(detail.terms_month)}</span>
              )}
            </h2>
            {can(session, "compensation.manage") && <Link className="button" to={`/affiliates/${id}/compensation`}>Compensation history →</Link>}
          </div>
          {detail.compensation === null ? (
            <p className="empty">
              No pay terms for {formatMonth(detail.terms_month)}, so nothing
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
                /* Card number, from the one map that names these (D06). She
                   is asked for the digits on the front of her card; showing
                   them back as an "account number" is how a payer types the
                   wrong thing into a banking app. */
                <Row label={PAYOUT_FIELD_LABEL.bank_account_number}>
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
          {id && <Corrections key={`fix-${id}`} affiliateId={id} session={session} />}
          {id && <FinancialRulesPreview key={`${id}-${month}`} affiliateId={id} currentMonth={detail.current_month}
            firstMonth={detail.collaboration_start_month && detail.collaboration_start_month > detail.platform_start_month ? detail.collaboration_start_month : detail.platform_start_month} />}
          <Link className="button" to={`/payments?month=${month}&affiliate=${id}`}>Open this model in Payments →</Link>
        </>}
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
