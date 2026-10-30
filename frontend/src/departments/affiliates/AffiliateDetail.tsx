import { useEffect, useState, useRef } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ContactForm } from "./ContactForm";
import { MonthPicker } from "../../components/MonthPicker";
import { Money } from "../../components/Money";
import { Corrections } from "./Corrections";
import { Bonuses } from "./Bonuses";
import { FinancialRulesPreview } from "./FinancialRulesPreview";
import { api, can } from "../../lib/api";
import { DestinationDetails } from "./DestinationDetails";
import type { DestinationCard } from "../../lib/payouts";
import type { NetSales } from "../../lib/portal";
import { describeDestination, PAY_TYPE } from "../../lib/payouts";
import type { Session } from "../../lib/api";
import { formatEgp, formatMonth } from "../../lib/money";
import { ROSTER_STATUS } from "./Affiliates";
import type { Affiliate } from "./Affiliates";
import { ApproveDialog, ModelLifecycle } from "./ModelLifecycle";
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
  /** Why she cannot be erased; empty when she can (ADR 0052). */
  erase_blockers?: string[];
  /** Terms exist for the working month - what approval checks (ADR 0052). */
  working_terms_set?: boolean;
  /** Every code she has held, oldest first, for the code timeline. */
  code_history?: { code: string; start_month: string; end_month: string | null; verified: boolean }[];
  shipping: Shipping;
  current_month: string;
  /** Which month `compensation` and `codes` below actually describe. */
  terms_month: string;
  platform_start_month: string;
  /** Her months, newest first (`months_for`): the profile's month control. */
  months: string[];
  codes: Code[];
  compensation: Compensation | null;
  payout_destination: Destination | null;
  /** Applied from outside Egypt; HBA arranges her payment by hand (ADR 0046). */
  payout_abroad?: boolean;
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
  /** What happened to it; only a courier's failure is `failed`. */
  status: "delivered" | "pending" | "failed" | "cancelled" | "refunded";
  /** Net sales and how it is known - never inferred from a zero. */
  net_sales: NetSales;
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

/** One entry in her Activity (`GET /api/audit`), already in words. */
type ActivityEntry = {
  id: number;
  subject: string;
  sentence: string;
  who: string | null;
  reason: string | null;
  created_at: string;
};

type Tone = { label: string; tone: string };

/**
 * The export's three order states, by what they mean for money - and the two
 * void orders the export has no word for. A cancelled order, or one refunded
 * while travelling, did not count either, and is red like a failed delivery;
 * it is not *called* a failed delivery, because no courier failed.
 */
const ORDER_STATE: Record<ProfileOrder["status"], Tone> = {
  delivered: { label: "Delivered", tone: "approved" },
  pending: { label: "Pending", tone: "owed" },
  failed: { label: "Failed delivery", tone: "refused" },
  cancelled: { label: "Cancelled", tone: "refused" },
  refunded: { label: "Refunded", tone: "refused" },
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

/** `25 November 2026` - the approved orders table prints the year. */
function dateWithYear(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
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
  const navigate = useNavigate();
  const location = useLocation();
  const [query, setQuery] = useSearchParams();
  const section = ["overview", "wardrobe", "performance", "targets", "payments", "activity"].includes(query.get("section") ?? "") ? query.get("section")! : "overview";
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
  /** The page head's *Add bonus* asked for the form (ADR 0070). */
  const [bonusAsked, setBonusAsked] = useState(false);
  const [correction, setCorrection] = useState("");
  /** A confirmed code on a waiting application, opened to be changed (ADR 0058). */
  const [changingCode, setChangingCode] = useState(false);
  /**
   * A draft, not the value. `null` means "not editing" - so the field shows
   * what is recorded until somebody deliberately opens it, and Cancel puts
   * back what the server said rather than what was typed (M03's rule, applied
   * here because it is the same failure either side of the platform).
   */
  const [startDraft, setStartDraft] = useState<string | null>(null);
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
        // Her code, filled in and editable, so a typo can be seen to be
        // correctable (ADR 0058) - it used to show only as placeholder text.
        setCorrection(body.codes[0]?.code ?? "");
        setChangingCode(false);
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
      const typed = correction.trim().toUpperCase();
      const current = detail?.codes[0]?.code ?? "";
      const result = await api.post<{ is_verified: boolean; code: string }>(
        `/api/affiliates/${id}/recheck-code`,
        typed && typed !== current ? { code: typed } : {},
      );
      setNotice({
        good: result.is_verified,
        text: result.is_verified
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

  /** ADR 0052: approving asks first - she is emailed the moment it happens. */
  const [approving, setApproving] = useState(false);
  /** Admin Models audit: Overview reads her details; editing is asked for. */
  const [editingContact, setEditingContact] = useState(false);
  const [emailDraft, setEmailDraft] = useState<string | null>(null);
  const [emailProblem, setEmailProblem] = useState<string | null>(null);
  /** Her Activity: the audit entries about her, in words. */
  const [activity, setActivity] = useState<ActivityEntry[] | null>(null);
  const [activityError, setActivityError] = useState<string | null>(null);

  // Another model's page reuses this component: nothing typed or read for
  // the last one may carry over (an open email change would save onto her).
  useEffect(() => {
    setEmailDraft(null);
    setEmailProblem(null);
    setEditingContact(false);
    setActivity(null);
  }, [id]);

  useEffect(() => {
    if (section !== "activity" || !can(session, "audit.view")) return;
    let live = true;
    setActivityError(null);
    api
      .get<{ events: ActivityEntry[] }>(`/api/audit?subject=${encodeURIComponent(`affiliate:${id}`)}&limit=200`)
      .then((body) => {
        // The feed matches a substring, so `affiliate:1` would also bring
        // `affiliate:12`: only her own subject is kept.
        if (live) setActivity(body.events.filter((event) => event.subject === `affiliate:${id}`));
      })
      .catch((caught) => { if (live) setActivityError(caught.message); });
    return () => { live = false; };
  }, [section, id, session]);

  async function saveEmail() {
    if (emailDraft === null) return;
    setEmailProblem(null);
    try {
      await api.patch(`/api/affiliates/${id}`, { email: emailDraft.trim() });
      setEmailDraft(null);
      changed("Her sign-in email is changed. She signs in with the new address from now on.");
    } catch (caught) {
      setEmailProblem(caught instanceof Error ? caught.message : "Could not change it.");
    }
  }

  /** After any change of status: say what happened, and read her again. */
  function changed(message: string) {
    setError(null);
    setNotice({ good: true, text: message });
    load();
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
  // Never paid and never asked for content: the model-only setup steps and
  // payment wording do not apply to it.
  const house = detail.account_kind === "house";
  // Any month with a number asked for. The step used to have no done state
  // at all, so it read as outstanding however long ago targets were set.
  const targetsSet = record?.targets.some((row) => row.required_videos !== null) ?? false;
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

  /**
   * Where her money goes, with *Pay on InstaPay* when she uses it (owner,
   * 29 September): the same card on Overview and on Payments, so the two
   * can never disagree. The InstaPay number is the one she gave for
   * InstaPay (`instapay_phone`), never her contact phone.
   */
  const whereToPay = (title: string) => (
    <section className="pay-detail__card profile__card">
      <h2 className="pay-detail__card-title">{title}</h2>
      {detail.payout_destination === null && detail.payout_abroad ? (
        /* ADR 0046: she applied from outside Egypt. Nothing is missing -
         *  there is no Egyptian destination to give, and paying her is
         *  arranged with her outside the platform. */
        <p className="pay-detail__missing">
          {detail.name} is paid outside Egypt. Arrange it with her directly,
          or set a destination here once she has one.
        </p>
      ) : detail.payout_destination === null && house ? (
        <p className="pay-detail__missing">
          {detail.name} is a house account and is never paid.
        </p>
      ) : detail.payout_destination === null ? (
        <p className="pay-detail__missing">
          {detail.name} has not submitted payment details, so nothing can be sent yet.
        </p>
      ) : detail.payout_destination_card ? (
        /* **The whole destination** (ADR 0042), served only where
         *  `payments.record` holds; marketing gets the shortened sentence. */
        <DestinationDetails card={detail.payout_destination_card} linkLabel="Pay on InstaPay ↗" />
      ) : (
        <p className="profile__card-line">{describeDestination(detail.payout_destination)}</p>
      )}
      {can(session, "affiliates.manage") && !house && (
        <p className="profile__card-actions">
          <Link className="pay-detail__link profile__card-link" to={`/affiliates/models/${detail.id}/payout-destination`}>
            {detail.payout_destination ? "Correct it →" : "Set it →"}
          </Link>
        </p>
      )}
      {/* Masking still governs every *record* (ADR 0028, as amended by
       *  0042). This line says an old transfer is not rewritten by a new
       *  destination. */}
      <p className="pay-detail__faint">Earlier transfers keep the destination they were sent to.</p>
    </section>
  );

  return (
    <>
      <div className="page__head">
        <Link className="button profile__back" to="/affiliates/models">
          ← Models
        </Link>
        {/* Her name, and under it the code an order knows her by: the
         *  export's title and subtitle for a model (`titleVals`, `m.code`). */}
        <div className="page__title">
          <h1>{detail.name}</h1>
          {current && <span className="page__subtitle">{current.code}</span>}
        </div>
        {/* ADR 0064: her portal as she sees it, read only. A house account
         *  is not a person and has no portal to look at. */}
        {!house && (
          <Link className="button" to={`/affiliates/models/${detail.id}/portal`}>
            View her portal
          </Link>
        )}
        {/* ADR 0070, the owner's ask: a bonus from every model's page. It
         *  opens the form on Payments, where her months and bonuses are. */}
        {!house && can(session, "payroll.bonus") && (
          <button
            type="button"
            className="button button--primary"
            onClick={() => {
              setQuery((previous) => {
                const next = new URLSearchParams(previous);
                next.set("section", "payments");
                next.set("month", month);
                return next;
              });
              setBonusAsked(true);
            }}
          >
            Add bonus
          </button>
        )}
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
        {/* ADR 0052: what her status allows - decline, reconsider,
            reactivate, and More actions for pause, archive and erase. */}
        <ModelLifecycle
          subject={detail}
          session={session}
          onChanged={changed}
          onErased={(message) => navigate("/affiliates/models", { state: { notice: message } })}
        />
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
                  account is all this row has to do. A house account is never
                  paid, so it has no such row. */}
              {!house && (
                <div>
                  <dt>Paid to</dt>
                  <dd>
                    {detail.payout_destination === null && detail.payout_abroad
                      ? "Outside Egypt — arranged directly"
                      : describeDestination(detail.payout_destination)}
                  </dd>
                </div>
              )}
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
              {/* ADR 0058: her code, filled in, can be corrected until she is
                  approved - a confirmed one too, through Change, since a
                  mistyped code can happen to exist on Shopify. */}
              {(!verified || changingCode) && (
                <div className="detail__step-action">
                  <input
                    className="input detail__correction"
                    value={correction}
                    onChange={(event) => setCorrection(event.target.value)}
                    placeholder="Discount code"
                    aria-label="Her code, which you can correct"
                    title="Correct a mistyped code here, then check it"
                  />
                  <button
                    type="button"
                    className="button"
                    onClick={verifyCode}
                    disabled={working !== null || !correction.trim()}
                  >
                    {working === "code"
                      ? "Asking Shopify…"
                      : correction.trim().toUpperCase() !== (detail.codes[0]?.code ?? "")
                        ? "Save and check"
                        : "Check it"}
                  </button>
                  {changingCode && (
                    <button
                      type="button"
                      className="button"
                      onClick={() => {
                        setChangingCode(false);
                        setCorrection(detail.codes[0]?.code ?? "");
                      }}
                      disabled={working !== null}
                    >
                      Cancel
                    </button>
                  )}
                </div>
              )}
              {verified && !changingCode && detail.status === "pending" && detail.codes.length === 1 && (
                <div className="detail__step-action">
                  <button type="button" className="button" onClick={() => setChangingCode(true)}>
                    Change
                  </button>
                </div>
              )}
            </li>

            {/* A house account is never paid and records no content, so only
                the code check applies to it. */}
            {!house && (
            <li className={detail.compensation ? "detail__step--done" : undefined}>
              <div>
                <strong>Set what {detail.name} is paid</strong>
                <span className="detail__note">
                  {detail.compensation
                    ? "The arrangement is recorded."
                    : "Required before approving."}
                </span>
              </div>
              <Link className="button" to={`/affiliates/models/${detail.id}/compensation`}>
                {detail.compensation ? "Change it" : "Set it"}
              </Link>
            </li>
            )}

            {!house && (
            <li className={targetsSet ? "detail__step--done" : undefined}>
              <div>
                <strong>Set the targets</strong>
                <span className="detail__note">
                  {targetsSet ? (
                    "Targets are recorded."
                  ) : detail.compensation?.compensation_type === "base_guarantee" ? (
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
              <Link className="button" to="/affiliates/targets">
                {targetsSet ? "Change them" : "Open targets"}
              </Link>
            </li>
            )}
          </ol>
          </section>

          {/*
           * The gate is `set_status`, server-side, and it raises on an
           * unverified code. Saying so on the button means the maintainer sees
           * why before pressing rather than meeting a refusal after.
           */}
          {/* ADR 0052: a paid model also needs pay terms, which the server
              enforces; the button says which step is missing. */}
          <button
            type="button"
            className="button button--primary detail__approve"
            onClick={() => setApproving(true)}
            disabled={working !== null || !verified || (!house && !detail.working_terms_set)}
          >
            {!verified
              ? "Check the code first"
              : !house && !detail.working_terms_set
                ? "Set the pay terms first"
                : "Approve this application"}
          </button>
          {approving && (
            <ApproveDialog
              subject={detail}
              onCancel={() => setApproving(false)}
              onDone={(message) => {
                setApproving(false);
                changed(message);
              }}
            />
          )}
          </div>
        </div>
      )}

      <div className="profile__navigation">
        <nav className="profile__tabs" aria-label="Model sections">
          {/* A house account has no wardrobe, targets or pay; Activity is for
              whoever may read the audit (admin Models audit). */}
          {(house ? ["Overview", "Performance"] : ["Overview", "Wardrobe", "Performance", "Targets", "Payments"])
            .concat(can(session, "audit.view") ? ["Activity"] : [])
            .map(label => {
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
        <span className="profile__month">
          {/* The export's in-page select (`mMonth`), over **her** months
           *  (`mMonthOptions`: from when she started to the current month) -
           *  decided on the server by the rule her own portal uses. Admin
           *  reporting screens keep the platform's months; this control is
           *  about one model. A month reached from a link outside them still
           *  shows, because the control never hides the month on screen. */}
          <MonthPicker value={month} size="section"
            months={detail.months}
            onChange={(next) => {
              setMonth(next);
              // Into the address as well, replacing rather than adding a
              // history entry: an order opened from here comes Back to the
              // address it left, and that should be the month on screen,
              // not the one the section was first opened on.
              setQuery((previous) => {
                const address = new URLSearchParams(previous);
                address.set("month", next);
                return address;
              }, { replace: true });
            }} />
        </span>
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
        {/*
         * The export's two columns (Admin lines 870-915): *Contact and
         * shipping* on the left, and on the right Sizing, Current terms and,
         * kept, Discount codes - the code she applied with, which the export does not
         * draw anywhere.
         */}
        <div className="profile__columns profile__full">
        <section className="pay-detail__card profile__contact">
          <h2 className="pay-detail__card-title">Her details</h2>
          {/*
           * Owner, 29 September: open a model and everything about her is on
           * the first tab. Read first; editing is a deliberate step below.
           */}
          <dl className="profile__details">
            <div>
              <dt>Signs in with</dt>
              <dd>
                {emailDraft === null ? (
                  <>
                    <span>{detail.email ?? "—"}</span>
                    {can(session, "affiliates.manage") && (
                      <button type="button" className="button button--quiet" onClick={() => setEmailDraft(detail.email ?? "")}>
                        Change
                      </button>
                    )}
                  </>
                ) : (
                  <span className="profile__email-edit">
                    <input
                      className="input"
                      type="email"
                      value={emailDraft}
                      aria-label="Her new sign-in email"
                      onChange={(event) => setEmailDraft(event.target.value)}
                    />
                    <button type="button" className="button button--primary" onClick={saveEmail}>
                      Save
                    </button>
                    <button type="button" className="button" onClick={() => { setEmailDraft(null); setEmailProblem(null); }}>
                      Cancel
                    </button>
                    <span className="detail__note">
                      She signs in with this address from now on; her password stays the same.
                    </span>
                    {emailProblem && <span className="blocker" role="alert">{emailProblem}</span>}
                  </span>
                )}
              </dd>
            </div>
            <div>
              <dt>Phone</dt>
              <dd>
                <span>{detail.phone ?? "Not given"}</span>
                {detail.phone && <CopyButton value={detail.phone} />}
              </dd>
            </div>
            <div>
              <dt>Ship to</dt>
              <dd>
                {[
                  detail.shipping.shipping_line1,
                  detail.shipping.shipping_line2,
                  detail.shipping.shipping_city,
                  detail.shipping.shipping_governorate,
                ]
                  .filter(Boolean)
                  .join(", ") || "Not given"}
              </dd>
            </div>
            {!house && (
              <div>
                <dt>Height · weight</dt>
                <dd>
                  {detail.height_cm || detail.weight_kg
                    ? `${detail.height_cm ? `${detail.height_cm} cm` : "no height"} · ${detail.weight_kg ? `${detail.weight_kg} kg` : "no weight"}`
                    : "Not given"}
                  <span className="detail__note">Only she can change these.</span>
                </dd>
              </div>
            )}
          </dl>
          {/* H01: when she started. Not a contact detail and not in the
           *  export's form, so it sits above it, not among the inputs. */}
          <div className="profile__start">
            <span className="contact-form__label">Started with HBA</span>
            <div className="profile__start-value">
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
            </div>
          </div>
          {/* The export's form, now behind a deliberate press: Overview reads
              her details, and changing them is its own step. */}
          {can(session, "affiliates.manage") &&
            (editingContact ? (
              <>
                <ContactForm
                  key={detail.id}
                  contact={{ id: detail.id, name: detail.name, phone: detail.phone, email: detail.email, shipping: detail.shipping }}
                  canEdit
                  onSaved={load}
                />
                <button type="button" className="button profile__edit-done" onClick={() => setEditingContact(false)}>
                  Done editing
                </button>
              </>
            ) : (
              <button type="button" className="button profile__edit-open" onClick={() => setEditingContact(true)}>
                Edit contact and shipping
              </button>
            ))}
        </section>
        <div className="profile__side">
        {/* Sizing moved into *Her details*; where to pay her takes its place
            (owner, 29 September). A house account is never paid. */}
        {!house && whereToPay("Where to pay her")}
        <section className="pay-detail__card profile__card">
          <h2 className="pay-detail__card-title">Current terms</h2>
          <p className="profile__card-line">{termLine}</p>
          {can(session, "compensation.manage") && (
            <Link className="pay-detail__link profile__card-link control-font" to={`/affiliates/models/${id}/compensation`}>
              Compensation history →
            </Link>
          )}
        </section>
        <section className="pay-detail__card">
          <h2 className="pay-detail__card-title">Discount codes</h2>
          {/* Admin Models audit: every code she has held, with its months, so
              *why does she have no code?* answers itself. */}
          {(detail.code_history?.length ?? 0) > 0 && (
            <ol className="profile__code-timeline" aria-label="Every code she has held">
              {detail.code_history!.map((period) => (
                <li
                  key={`${period.code}-${period.start_month}`}
                  className={period.end_month === null ? "profile__code-period profile__code-period--open" : "profile__code-period"}
                >
                  <span className="code">{period.code}</span>
                  <span className="profile__code-months">
                    {formatMonth(period.start_month)}
                    {period.end_month === null ? " → now" : period.end_month === period.start_month ? "" : ` – ${formatMonth(period.end_month)}`}
                  </span>
                  {!period.verified && <span className="blocker">not confirmed</span>}
                </li>
              ))}
            </ol>
          )}
          {detail.codes.length === 0 ? (
            <p className="empty">
              {/* `codes` describe `terms_month`, the month being looked at -
                  naming the working month here contradicted the list. */}
              None registered for {formatMonth(detail.terms_month)}.
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

          {/* ADR 0053: her code is the one she applied with and does not
              change, so there is nothing here to register or replace. A typo
              in a code Shopify has not confirmed is corrected on re-checking. */}
        </section>
        </div>
        </div>
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
                    ? <Link key={`${item.shopify_order_id}-${index}`} className="profile__piece" to={`/affiliates/products/${item.shopify_product_id}`}>{body}</Link>
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
              <Link className="pay-detail__link" to="/affiliates/products">Open the catalogue →</Link>
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
                    const state = ORDER_STATE[order.status] ?? ORDER_STATE.pending;
                    const opens = `/affiliates/orders/${encodeURIComponent(order.shopify_order_id)}`;
                    // The export's row is one button: the whole line opens
                    // the order, and the order's back link returns here.
                    const back = { label: detail.name, to: `${location.pathname}${location.search}` };
                    return (
                      <tr
                        key={order.shopify_order_id}
                        className="profile__order-row"
                        onClick={() => navigate(opens, { state: { back } })}
                      >
                        <td className="profile__ref">
                          <Link to={opens} state={{ back }} onClick={(event) => event.stopPropagation()}>
                            {order.order_number}
                          </Link>
                        </td>
                        <td className="profile__muted">{dateWithYear(order.placed_at)}</td>
                        <td className={`profile__state profile__tone--${state.tone}`}>{state.label}</td>
                        <td className="profile__money">
                          {/* The server says how it knows: a real zero
                              prints EGP 0.00, a cancelled order's recorded
                              placed-at total prints as such, and only a
                              figure nobody recorded is *amount not available*. */}
                          {order.net_sales.kind === "unavailable" || order.net_sales.piastres === null
                            ? <span className="profile__muted">amount not available</span>
                            : <Money piastres={order.net_sales.piastres} kind="agreed" />}
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
            <Link className="pay-detail__link" to={`/affiliates/targets?month=${month}`}>Open Targets →</Link>
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
              <Link className="pay-detail__link profile__card-link control-font" to={`/affiliates/models/${id}/compensation`}>
                Edit terms →
              </Link>
            )}
          </section>
          {whereToPay("Where to send it")}
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
                        <Link to={`/affiliates/payments/${row.month}/${detail.id}`}>{formatMonth(row.month)}</Link>
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
          {/* Admin Models audit: her whole ledger has its own page, which
              nothing linked to. */}
          <p className="profile__ledger-link">
            <Link className="pay-detail__link" to={`/affiliates/models/${detail.id}/payments`}>
              See every transfer and adjustment →
            </Link>
          </p>
        </div>
          {id && !house && (
            <Bonuses
              key={`bonus-${id}`}
              affiliateId={id}
              name={detail.name}
              month={month}
              session={session}
              open={bonusAsked}
              onOpened={() => setBonusAsked(false)}
              onChanged={load}
            />
          )}
          {id && <Corrections key={`fix-${id}`} affiliateId={id} session={session} />}
          {id && <FinancialRulesPreview key={`${id}-${month}`} affiliateId={id} currentMonth={detail.current_month}
            firstMonth={detail.collaboration_start_month && detail.collaboration_start_month > detail.platform_start_month ? detail.collaboration_start_month : detail.platform_start_month} />}
        </>}
        {/*
         * Admin Models audit: who did what to her account, when, and why -
         * approvals, code and term changes, pauses. It was all audited and
         * none of it was visible from her page.
         */}
        {section === "activity" && (
          <div className="surface profile__full profile__activity">
            {activityError ? (
              <p className="notice notice--refused" role="alert">{activityError}</p>
            ) : activity === null ? (
              <p className="empty">Loading…</p>
            ) : activity.length === 0 ? (
              <p className="empty">Nothing has been recorded about {detail.name} yet.</p>
            ) : (
              <ol className="profile__timeline">
                {activity.map((entry) => (
                  <li key={entry.id}>
                    <time dateTime={entry.created_at}>
                      {new Date(entry.created_at).toLocaleDateString("en-GB", {
                        day: "numeric",
                        month: "short",
                        year: "numeric",
                      })}
                    </time>
                    <span>
                      {entry.sentence}
                      {entry.who && <span className="profile__muted"> · {entry.who}</span>}
                      {entry.reason && <span className="profile__timeline-reason">“{entry.reason}”</span>}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        )}
      </div>
    </>
  );
}

/** Copy one value, saying so for a moment; silent if the browser refuses. */
function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="button button--quiet"
      onClick={() => {
        navigator.clipboard
          ?.writeText(value)
          .then(() => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          })
          .catch(() => undefined);
      }}
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}
