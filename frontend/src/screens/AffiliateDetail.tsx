import { useEffect, useState, useRef } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { MonthPicker } from "../components/MonthPicker";
import { Money } from "../components/Money";
import { Corrections } from "../components/Corrections";
import { FinancialRulesPreview } from "../components/FinancialRulesPreview";
import { api, can } from "../lib/api";
import { DestinationDetails } from "../components/DestinationDetails";
import type { DestinationCard } from "../lib/payouts";
import { describeDestination, PAY_TYPE } from "../lib/payouts";
import type { Session } from "../lib/api";
import { formatEgp, formatMonth } from "../lib/money";
import { ROSTER_STATUS } from "./Affiliates";
import type { Affiliate } from "./Affiliates";
import "./PaymentDetail.css";
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
  /**
   * The full destination, or `null` where the reader may not send money.
   * ADR 0042: the server decides, on `payments.record`, and this screen only
   * draws what it is given.
   */
  payout_destination_card?: DestinationCard | null;
};

type Earnings = {
  month: string;
  sales: { earned_piastres: number; pending_piastres: number };
  orders: { earned: number; pending: number; void: number };
  payout: { piastres: number; is_provisional: boolean };
  blockers: string[];
  is_payable: boolean;
};


/**
 * One model, and everything true about them this month.
 *
 * Read-only for now. The pages that *change* what they are paid — their rate, their
 * discount code, where their money goes — each get their own page with a "what
 * this changes" preview, and those are the next screens after this one (§12.2
 * calls them Pattern C: money decisions never happen in a small dialog).
 */
/** One of her orders, as her own orders screen reads it (`my_orders`). */
type ProfileOrder = {
  shopify_order_id: string;
  order_number: string;
  placed_at: string;
  base_piastres: number;
  placed_piastres: number | null;
  state: "earned" | "pending" | "void";
  commission_piastres: number | null;
};

/** One month of her content record (`my_targets`). */
type TargetMonth = {
  month: string;
  required_videos: number | null;
  required_stories: number | null;
  actual_videos: number | null;
  actual_stories: number | null;
  achieved: boolean | null;
  recorded_at: string | null;
};

/** One agreed month and what was paid against it (`my_payments`). */
type StatementMonth = {
  month: string;
  state: string;
  obligation_piastres: number;
  paid_piastres: number;
};

type ProfileRecord = { targets: TargetMonth[]; statements: StatementMonth[] };

type Tone = { label: string; tone: string };

/** The export's three order states, by what they mean for money. */
const ORDER_STATE: Record<string, Tone> = {
  earned: { label: "Delivered", tone: "approved" },
  pending: { label: "Pending", tone: "owed" },
  void: { label: "Failed delivery", tone: "refused" },
};

/** An agreed month's state, in the words the Payments list uses. */
const STATEMENT_STATE: Record<string, Tone> = {
  unpaid: { label: "Approved", tone: "approved" },
  partially_paid: { label: "Partly paid", tone: "owed" },
  settled: { label: "Fully paid", tone: "lift" },
  overpaid: { label: "More sent than due", tone: "refused" },
  settled_externally: { label: "Paid outside the platform", tone: "quiet" },
};

function dateDay(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "long" });
}

/**
 * How a month's content record ended, in the export's words. *No record yet*
 * is the one that holds a month up, so it is the one coloured; a month that
 * was recorded and fell short is an ordinary outcome and is not.
 */
function targetState(row: TargetMonth): Tone {
  if (row.achieved === null && row.actual_videos === null) return { label: "No record yet", tone: "owed" };
  if (row.achieved) return { label: "Target met", tone: "lift" };
  if (row.actual_videos === 0 && row.actual_stories === 0) return { label: "Recorded zero", tone: "quiet" };
  return { label: "Below target", tone: "quiet" };
}

export function AffiliateDetail({ session }: { session: Session }) {
  const { id } = useParams();
  const [query, setQuery] = useSearchParams();
  const section = ["overview", "wardrobe", "performance", "targets", "payments"].includes(query.get("section") ?? "") ? query.get("section")! : "overview";
  const [month, setMonth] = useState(query.get("month")?.match(/^\d{4}-(0[1-9]|1[0-2])$/) ? query.get("month")! : session.platform.working_month);
  const [wardrobeError, setWardrobeError] = useState<string | null>(null);
  const [wardrobeReload, setWardrobeReload] = useState(0);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [earnings, setEarnings] = useState<Earnings | null>(null);
  /** Her content record and agreed months, and her orders for the month -
   *  the same records her own screens read. */
  const [record, setRecord] = useState<ProfileRecord | null>(null);
  const [orders, setOrders] = useState<ProfileOrder[] | null>(null);
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
    setOrders(null);
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
        return Promise.all([
          api.get<Earnings>(`/api/affiliates/${id}/earnings/${month}`),
          api.get<ProfileRecord>(`/api/affiliates/${id}/record`),
          api.get<{ orders: ProfileOrder[] }>(`/api/affiliates/${id}/orders/${month}`),
        ]);
      })
      .then(value => {
        if (version !== loadVersion.current || !value) return;
        setEarnings(value[0]);
        setRecord(value[1]);
        setOrders(value[2].orders);
      })
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
  const status = ROSTER_STATUS[detail.status] ?? ROSTER_STATUS.inactive;
  const terms = detail.compensation;
  const termLine = terms
    ? [
        PAY_TYPE[terms.compensation_type] ?? terms.compensation_type,
        `${terms.commission_rate_bp / 100}% commission`,
        terms.fixed_amount_piastres !== null ? `${formatEgp(terms.fixed_amount_piastres)} salary` : null,
        terms.base_amount_piastres !== null ? `${formatEgp(terms.base_amount_piastres)} minimum` : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : "No terms set";
  const contentRow = record?.targets.find((row) => row.month === month) ?? null;
  const statement = record?.statements.find((row) => row.month === month) ?? null;
  const statementState = statement
    ? STATEMENT_STATE[statement.state] ?? { label: statement.state, tone: "quiet" }
    : null;

  return (
    <>
      <div className="page__head">
        <Link className="button profile__back" to="/affiliates">
          ← Models
        </Link>
        <div className="page__title">
          <h1>{detail.name}</h1>
        </div>
      </div>

      {/*
       * The approved profile's hero: who this is, at a glance, before any of
       * the sections. Her initial, her name, the state she is in, and the code
       * an order knows her by — the same four things the roster row carries,
       * so arriving from that row does not feel like arriving somewhere else.
       */}
      {/*
       * The approved profile's hero: her initial, the state she is in and the
       * code an order knows her by - the same things her roster row carries,
       * in the export's words and tones. Her name is the page title above.
       */}
      <header className="profile__hero">
        <span className="profile__avatar" aria-hidden="true">
          {detail.name.charAt(0).toUpperCase()}
        </span>
        <span className="profile__facts">
          <span className={`pill profile__tone--${status.tone}`}>{status.label}</span>
          <span className="profile__code">{current ? current.code : "No code yet"}</span>
        </span>
        {detail.status === "pending" && appliedOn && (
          <span className="profile__applied">Applied {appliedOn}</span>
        )}
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
        <div className="detail__application">
          {/*
           * **What she sent us**, beside what somebody here still has to do —
           * the export's two columns, and the reason for them: approving an
           * application means reading her answers, and they were nowhere on
           * this panel. They were two taps away under Overview.
           *
           * Read-only. Her details are hers to correct (A05, D11); this card
           * is for checking them, not editing them.
           */}
          <section className="pay-detail__card detail__submitted">
            <h2 className="pay-detail__card-title">Submitted information</h2>
            <dl className="detail__facts">
              <div><dt>Signs in with</dt><dd>{detail.email ?? "—"}</dd></div>
              <div><dt>Phone</dt><dd>{detail.phone ?? "Not given"}</dd></div>
              <div>
                <dt>Discount code</dt>
                <dd>{detail.codes[0]?.code ?? "None yet"}</dd>
              </div>
              <div>
                <dt>Where to send things</dt>
                <dd>
                  {[detail.shipping.shipping_line1, detail.shipping.shipping_city, detail.shipping.shipping_governorate]
                    .filter(Boolean)
                    .join(", ") || "Not given"}
                </dd>
              </div>
              <div>
                <dt>Height and weight</dt>
                <dd>
                  {detail.height_cm || detail.weight_kg
                    ? `${detail.height_cm ? `${detail.height_cm} cm` : "no height"} · ${detail.weight_kg ? `${detail.weight_kg} kg` : "no weight"}`
                    : "Not given — they are optional"}
                </dd>
              </div>
              {/* Masked, as it is everywhere else (ADR 0028). Recognising the
                  account is all this row has to do. */}
              <div>
                <dt>Paid to</dt>
                <dd>{describeDestination(detail.payout_destination)}</dd>
              </div>
            </dl>
          </section>

          <div className="detail__setup">
          <section className="pay-detail__card">
          <h2 className="pay-detail__card-title">Setup before approval</h2>

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
          </section>

          {/*
           * The gate is `set_status`, server-side, and it raises on an
           * unverified code. Saying so on the button means the maintainer sees
           * why before pressing rather than meeting a refusal after.
           */}
          <button
            type="button"
            className="button button--primary detail__approve"
            onClick={approve}
            disabled={working !== null || !verified}
          >
            {working === "approve"
              ? "Approving…"
              : verified
                ? "Approve this application"
                : "Check the code first"}
          </button>
          </div>
        </div>
      )}

      <div className="profile__navigation">
        <nav className="profile__tabs" aria-label="Model sections">
          {["Overview", "Wardrobe", "Performance", "Targets", "Payments"].map(label => {
            const key = label.toLowerCase();
            return <button key={label} type="button"
              className={section === key ? "profile__tab profile__tab--active" : "profile__tab"}
              aria-current={section === key ? "page" : undefined}
              onClick={() => setQuery(previous => { const next = new URLSearchParams(previous); next.set("section", key); next.set("month", month); return next; })}>
              {key === "overview" && detail.status === "pending" ? "Application" : label}
            </button>;
          })}
        </nav>
        {/* The export keeps the month beside the sections on every one of
         *  them: the figures on Overview are that month's too. */}
        <span className="profile__month"><MonthPicker value={month} onChange={setMonth} /></span>
      </div>
      <div className="detail__grid">
        {section === "overview" && <>
        <div className="profile__stats profile__full">
          <section className="pay-detail__card profile__stat">
            <span className="profile__stat-label">{formatMonth(month)} sales</span>
            <span className="profile__stat-value">
              {earnings ? <Money piastres={earnings.sales.earned_piastres} kind="agreed" /> : "—"}
            </span>
          </section>
          <section className="pay-detail__card profile__stat">
            <span className="profile__stat-label">Content recorded</span>
            <span className="profile__stat-text">
              {!contentRow || contentRow.actual_videos === null
                ? "No update yet"
                : `${contentRow.actual_videos}/${contentRow.required_videos ?? 0} videos · ${contentRow.actual_stories ?? 0}/${contentRow.required_stories ?? 0} stories`}
            </span>
          </section>
          <section className="pay-detail__card profile__stat">
            <span className="profile__stat-label">{formatMonth(month)} payment</span>
            {/* An agreed month shows what was agreed; an open one shows the
             *  estimate and says it is one, never under a paid-sounding word. */}
            <span className="profile__stat-value">
              {statement ? (
                <Money piastres={statement.obligation_piastres} kind="agreed" />
              ) : earnings ? (
                <Money piastres={earnings.payout.piastres} kind="agreed" />
              ) : "—"}
            </span>
            <span className={`profile__stat-state profile__tone--${statementState ? statementState.tone : earnings && earnings.blockers.length > 0 ? "refused" : "owed"}`}>
              {statementState
                ? statementState.label
                : earnings && earnings.blockers.length > 0
                  ? "Not payable yet"
                  : "Estimated"}
            </span>
          </section>
        </div>
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
        <section className="pay-detail__card profile__card">
          <h2 className="pay-detail__card-title">Current terms</h2>
          <p className="profile__card-line">{termLine}</p>
          {can(session, "compensation.manage") && (
            <Link className="pay-detail__link profile__card-link" to={`/affiliates/${id}/compensation`}>
              Compensation history →
            </Link>
          )}
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
        {section === "wardrobe" && <div className="profile__wardrobe profile__full">
          {wardrobeError && <p className="notice notice--refused" role="alert">{wardrobeError} <button className="button" onClick={() => setWardrobeReload(n => n + 1)}>Retry</button></p>}
          {!wardrobe && !wardrobeError && <p className="empty">Loading wardrobe…</p>}
          {wardrobe && <>
            <div className="profile__subhead">
              <h2>Received</h2>
              <span>{wardrobe.received.length} {wardrobe.received.length === 1 ? "piece" : "pieces"}</span>
            </div>
            {wardrobe.received.length === 0 ? (
              <div className="surface"><p className="empty">Nothing received yet.</p></div>
            ) : (
              <div className="profile__pieces">
                {wardrobe.received.map((item, index) => {
                  const body = <>
                    {item.image_thumb_url || item.image_url
                      ? <img className="profile__piece-image" src={item.image_thumb_url || item.image_url!} alt="" loading="lazy" />
                      : <span className="profile__piece-image profile__piece-image--none">image</span>}
                    <span className="profile__piece-text">
                      <span className="profile__piece-name">{item.title}</span>
                      <span className="profile__piece-size">Size {item.size || "not recorded"}</span>
                    </span>
                  </>;
                  return item.shopify_product_id
                    ? <Link key={`${item.shopify_order_id}-${index}`} className="profile__piece" to={`/products/${item.shopify_product_id}`}>{body}</Link>
                    : <div key={`${item.shopify_order_id}-${index}`} className="profile__piece">{body}</div>;
                })}
              </div>
            )}
            {wardrobe.processing.length + wardrobe.failed.length > 0 && <>
              <div className="profile__subhead profile__subhead--gap">
                <h2>Not received yet</h2>
                <span>{wardrobe.processing.length + wardrobe.failed.length} not yet owned</span>
              </div>
              <div className="surface">
                <ul className="profile__pending">
                  {wardrobe.processing.map((item, index) => (
                    <li key={`p-${item.shopify_order_id}-${index}`}>
                      <span>{item.title}<span className="profile__piece-size">Size {item.size || "not recorded"}</span></span>
                      <span className="profile__tone--owed">Processing</span>
                    </li>
                  ))}
                  {wardrobe.failed.map((item, index) => (
                    <li key={`f-${item.shopify_order_id}-${index}`}>
                      <span>{item.title}<span className="profile__piece-size">Size {item.size || "not recorded"}</span></span>
                      <span className="profile__tone--refused">Needs checking</span>
                    </li>
                  ))}
                </ul>
              </div>
            </>}
            <div className="profile__catalogue">
              <span>What HBA has not sent {detail.name} yet is in the catalogue.</span>
              <Link className="pay-detail__link" to="/products">Open the catalogue →</Link>
            </div>
          </>}
        </div>}
        {section === "performance" && <div className="profile__full">
          <div className="surface">
            {orders === null ? (
              <p className="empty">Loading…</p>
            ) : orders.length === 0 ? (
              <p className="empty">
                {current
                  ? `No orders were placed with ${current.code} in ${formatMonth(month)}.`
                  : `No orders in ${formatMonth(month)}.`}
              </p>
            ) : (
              <table className="table profile__orders">
                <thead>
                  <tr>
                    <th className="profile__ref">Order</th>
                    <th>Date</th>
                    <th className="profile__state">Status</th>
                    <th className="profile__money">Net sales</th>
                    <th className="profile__money">Commission</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((order) => {
                    const state = ORDER_STATE[order.state] ?? ORDER_STATE.pending;
                    return (
                      <tr key={order.shopify_order_id}>
                        <td className="profile__ref">
                          <Link to={`/orders/${encodeURIComponent(order.shopify_order_id)}`}>{order.order_number}</Link>
                        </td>
                        <td className="profile__muted">{dateDay(order.placed_at)}</td>
                        <td className={`profile__state profile__tone--${state.tone}`}>{state.label}</td>
                        <td className="profile__money">
                          <Money piastres={order.placed_piastres ?? order.base_piastres} kind="agreed" />
                        </td>
                        <td className="profile__money">
                          {order.commission_piastres === null
                            ? "—"
                            : <Money piastres={order.commission_piastres} kind="agreed" />}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>}
        {section === "targets" && <div className="profile__full">
          <div className="profile__subhead">
            <h2>Recorded content</h2>
            <Link className="pay-detail__link" to={`/targets?month=${month}`}>Open Targets →</Link>
          </div>
          <div className="surface">
            {!record ? (
              <p className="empty">Loading…</p>
            ) : record.targets.length === 0 ? (
              <p className="empty">Nothing has been asked of {detail.name} yet.</p>
            ) : (
              <table className="table profile__history">
                <thead>
                  <tr>
                    <th>Month</th>
                    <th className="profile__count">Videos</th>
                    <th className="profile__count">Stories</th>
                    <th className="profile__state">Recorded</th>
                    <th className="profile__state">Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {record.targets.map((row) => {
                    const state = targetState(row);
                    return (
                      <tr key={row.month}>
                        <td>{formatMonth(row.month)}</td>
                        <td className="profile__count">
                          {row.actual_videos === null ? "—" : `${row.actual_videos} / ${row.required_videos ?? 0}`}
                        </td>
                        <td className="profile__count">
                          {row.actual_stories === null ? "—" : `${row.actual_stories} / ${row.required_stories ?? 0}`}
                        </td>
                        <td className={`profile__state profile__tone--${state.tone}`}>{state.label}</td>
                        <td className="profile__state profile__muted">
                          {row.recorded_at ? dateDay(row.recorded_at) : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>}
        {section === "payments" && <>
        <div className="profile__cards profile__full">
          <section className="pay-detail__card profile__card">
            <h2 className="pay-detail__card-title">Terms</h2>
            <p className="profile__card-line">{termLine}</p>
            {detail.terms_month !== detail.current_month && (
              <p className="pay-detail__faint">For {formatMonth(detail.terms_month)}</p>
            )}
            {can(session, "compensation.manage") && (
              <Link className="pay-detail__link profile__card-link" to={`/affiliates/${id}/compensation`}>
                Edit terms →
              </Link>
            )}
          </section>
          <section className="pay-detail__card profile__card">
            <h2 className="pay-detail__card-title">Where to send it</h2>
            {detail.payout_destination === null ? (
              <p className="pay-detail__missing">
                {detail.name} has not submitted payment details, so nothing can be sent yet.
              </p>
            ) : detail.payout_destination_card ? (
              /* **The whole destination, here too** (ADR 0042). The export
               *  draws the same card on this tab as on the payments desk,
               *  and it is the same question asked from a different screen:
               *  somebody looking at her profile with a banking app open
               *  cannot type `…291` any more than somebody on the desk can.
               *  The server sends the card only where `payments.record`
               *  holds; marketing still gets the shortened sentence. */
              <DestinationDetails card={detail.payout_destination_card} />
            ) : (
              <p className="profile__card-line">{describeDestination(detail.payout_destination)}</p>
            )}
            {can(session, "affiliates.manage") && (
              <Link className="pay-detail__link profile__card-link" to={`/affiliates/${detail.id}/payout-destination`}>
                {detail.payout_destination ? "Correct it →" : "Set it →"}
              </Link>
            )}
            {/* Masking still governs every *record* (ADR 0028, as amended by
             *  0042): audit rows, logs, notices and the confirmation shown
             *  when a destination changes. This line is about neither - it
             *  says an old transfer is not rewritten by a new destination. */}
            <p className="pay-detail__faint">Earlier transfers keep the destination they were sent to.</p>
          </section>
        </div>
        <div className="surface profile__full">
          {!record ? (
            <p className="empty">Loading…</p>
          ) : record.statements.length === 0 ? (
            <p className="empty">No month has been agreed for {detail.name} yet.</p>
          ) : (
            <table className="table profile__history">
              <thead>
                <tr>
                  <th>Month</th>
                  <th className="profile__money">Amount</th>
                  <th className="profile__state">State</th>
                  <th className="profile__recorded">Recorded</th>
                </tr>
              </thead>
              <tbody>
                {record.statements.map((row) => {
                  const state = STATEMENT_STATE[row.state] ?? { label: row.state, tone: "quiet" };
                  return (
                    <tr key={row.month}>
                      <td>
                        <Link to={`/payments/${row.month}/${detail.id}`}>{formatMonth(row.month)}</Link>
                      </td>
                      <td className="profile__money">
                        <Money piastres={row.obligation_piastres} kind="agreed" />
                      </td>
                      <td className={`profile__state profile__tone--${state.tone}`}>{state.label}</td>
                      <td className="profile__recorded profile__muted">
                        {row.paid_piastres > 0
                          ? <><Money piastres={row.paid_piastres} kind="agreed" /> recorded</>
                          : "Nothing recorded yet"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
          {id && <Corrections key={`fix-${id}`} affiliateId={id} session={session} />}
          {id && <FinancialRulesPreview key={`${id}-${month}`} affiliateId={id} currentMonth={detail.current_month}
            firstMonth={detail.collaboration_start_month && detail.collaboration_start_month > detail.platform_start_month ? detail.collaboration_start_month : detail.platform_start_month} />}
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
