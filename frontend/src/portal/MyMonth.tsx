import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { usePortal } from "./AffiliateLayout";
import { Money } from "../components/Money";
import { MonthSheet } from "./MonthSheet";
import { api } from "../lib/api";
import { formatDay, formatEgp, formatMonth } from "../lib/money";
import type { MyEarnings, MyHome, PaymentMonth } from "../lib/portal";
import { cairoToday, expectedRecording, monthListStates } from "../lib/portal";
import "./Home.css";

/**
 * Where a month has got to — including *we could not find out*. A12.
 *
 * `unknown` exists because the settlement used to come from a second request,
 * and a screen that could not read it showed **approved**: a claim about her
 * money inferred from a failed network call. Home reads everything in one
 * request now, but *How this adds up* still asks separately and shares this.
 */
export type HomeState = "open" | "approved" | "paid" | "settled" | "unknown";

/** Lower case, as the export writes them; *How this adds up* shares them. */
export const STATE_LABEL: Record<HomeState, string> = {
  open: "in progress",
  approved: "approved",
  paid: "payment recorded",
  settled: "settled",
  unknown: "payment status unavailable",
};

/** Home's pill, in sentence case (batch L). */
const PILL: Record<HomeState, string> = {
  open: "In progress",
  approved: "Approved",
  paid: "Paid",
  settled: "Settled",
  unknown: "Status unavailable",
};

const HERO_LABEL: Record<HomeState, string> = {
  open: "Earned so far",
  approved: "Approved for payment",
  paid: "Paid",
  // A settled month reads like any other (ADR 0054): the pill says *Settled*,
  // and the figure is simply what she earned.
  settled: "Earned",
  unknown: "Approved earnings",
};

/** What the sum at the foot of the breakdown is called. */
export const TOTAL_LABEL: Record<HomeState, string> = {
  open: "Earnings so far",
  approved: "Approved for payment",
  paid: "Recorded payment",
  settled: "Earned",
  unknown: "Approved earnings",
};

export function homeState(
  body: MyEarnings,
  settlement?: PaymentMonth,
  /**
   * Whether the settlement read actually answered. A12: *nothing in the
   * ledger* and *the request failed* are different, and the second must not
   * be read as the first.
   */
  settlementKnown = true,
): HomeState {
  // A month from before the platform is closed and has no figure to move
  // (ADR 0036), which is the export's *settled*.
  if (body.state === "historical") return "settled";
  if (body.state === "open") return "open";
  if (!settlementKnown) return "unknown";
  // Agreed. Only the ledger may promote it to *paid*, and only once nothing is
  // outstanding: a part payment is still money owed.
  const paid = settlement?.state === "settled" || settlement?.state === "overpaid";
  return paid ? "paid" : "approved";
}

/**
 * Months already read, kept for the visit. Switching back to one paints at
 * once and is refreshed underneath, rather than blanking the screen to ask
 * the server a question it answered a moment ago.
 */
const seen = new Map<string, MyHome>();

/** One month's Home, from the visit's cache when it has it. Payments reads
 *  the running month through this, so it never asks twice. */
export async function readHome(month: string): Promise<MyHome> {
  const cached = seen.get(month);
  if (cached) return cached;
  const value = await api.get<MyHome>(`/api/me/home/${month}`);
  seen.set(month, value);
  return value;
}

const SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const LONG = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

function dayMonth(iso: string): string {
  const [, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${SHORT[m - 1]}`;
}

/**
 * Her month, redesigned in batch L (the owner, 27 September - "I don't mind
 * changing things on the approved design if they are better").
 *
 * **One question per card, most asked first.** What she has earned and when
 * it arrives share the first card, because that is why she opens the app. Her
 * orders, then where she stands, then her year. The month is named once, as
 * the control that changes it.
 *
 * **Every figure is the server's** (docs/RULES.md). The screen lays out
 * `GET /api/me/home/{month}` and works nothing out - the one ratio drawn, the
 * height of a bar, is a picture of two server figures, not a figure.
 */
export function MyMonth() {
  const { month, months, setMonth } = usePortal();
  const [home, setHome] = useState<MyHome | null>(() => seen.get(month) ?? null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [sheet, setSheet] = useState(false);

  useEffect(() => {
    let live = true;
    setHome(seen.get(month) ?? null);
    setError(null);
    api
      .get<MyHome>(`/api/me/home/${month}`)
      .then((value) => {
        seen.set(month, value);
        if (live) setHome(value);
      })
      .catch((caught) => {
        if (live) setError(caught.message);
      });
    return () => {
      live = false;
    };
  }, [month, retry]);

  if (error && !home) {
    return (
      <p className="notice notice--refused" role="alert">
        {error}{" "}
        <button className="button" onClick={() => setRetry((n) => n + 1)}>
          Retry
        </button>
      </p>
    );
  }

  if (!home) return <HomeSkeleton />;

  const body = home.earnings;
  const settlement = home.payments.months.find((row) => row.month === month);
  const state = homeState(body, settlement);

  return (
    <div className="home">
      <div className="home__monthrow">
        <button
          type="button"
          className="home__month"
          aria-haspopup="dialog"
          onClick={() => setSheet(true)}
        >
          {formatMonth(month)}
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="m6 9 6 6 6-6" />
          </svg>
        </button>
        <span className={`home__pill home__pill--${state}`}>
          <span className="home__pill-dot" aria-hidden="true" />
          {/* An ended month still open is waiting on HBA, not still earning. */}
          {state === "open" && month !== months[0] ? "Awaiting approval" : PILL[state]}
        </span>
      </div>

      <Hero home={home} state={state} settlement={settlement} />

      {/*
       * A month that moved after it was agreed, and money carried out of an
       * earlier one - the export's amber *something changed*. Only drawn when
       * it happened.
       */}
      {body.recalculated && (
        <Link className="home__change" to={`/earnings?month=${month}`}>
          <span className="home__change-kicker">Sales changed since approval</span>
          <span>
            Agreed at <Money piastres={body.recalculated.was_piastres} />, now{" "}
            <Money piastres={body.recalculated.now_piastres} />.
          </span>
          <span className="home__link">See the detail →</span>
        </Link>
      )}
      {(body.credited_from ?? []).map((row) => (
        <Link className="home__change" key={row.month} to={`/earnings?month=${month}`}>
          <span className="home__change-kicker">Carried from {formatMonth(row.month)}</span>
          <span>{row.text}</span>
          <span className="home__link">See the detail →</span>
        </Link>
      ))}
      {body.waiting_on?.length > 0 && <Waiting rows={body.waiting_on} />}

      <Orders home={home} />
      <Tiles home={home} />
      {home.content && home.best_seller && <BestSeller home={home} />}
      {home.share && <Share share={home.share} />}
      <YearBars home={home} />

      {sheet && (
        <MonthSheet
          months={months}
          current={month}
          states={monthListStates(months, home.payments)}
          onPick={(value) => {
            setMonth(value);
            setSheet(false);
          }}
          onClose={() => setSheet(false)}
        />
      )}
    </div>
  );
}

/**
 * What the month is waiting on, behind an ⓘ (owner, 1 October 2026): the
 * sentences read as instructions under the card, and they are not hers to act
 * on - every one today is HBA's move, which the line says.
 */
function Waiting({ rows }: { rows: MyEarnings["waiting_on"] }) {
  const [open, setOpen] = useState(false);
  const whose = rows.every((row) => row.who === "hba") ? "Waiting on HBA" : "Waiting";
  return (
    <div className="home__waiting">
      <span className="home__waiting-head">
        <span>{whose}</span>
        <button
          type="button"
          className="home__info"
          aria-label="What this month is waiting on"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          i
        </button>
      </span>
      {open && (
        <div className="home__why">
          {rows.map((row) => (
            <p key={row.text}>{row.text}</p>
          ))}
        </div>
      )}
    </div>
  );
}

/** Earned, how, how far through the month - and when it arrives. */
function Hero({
  home,
  state,
  settlement,
}: {
  home: MyHome;
  state: HomeState;
  settlement?: PaymentMonth;
}) {
  const body = home.earnings;
  const rate = body.commission_rate_bp;
  const compare = home.comparison;
  // The guaranteed minimum's rule, behind its ⓘ (owner, 1 October 2026).
  const [rule, setRule] = useState(false);
  const transfer = home.payments.payments.find((row) =>
    row.settles.some((part) => part.month === home.month),
  );

  // A settled month with no terms recorded has no figure to show. Its sales
  // are real, so they take the big number's place - named as sales, never
  // passed off as earnings.
  const noFigure = body.amount_piastres === null;

  return (
    <section className="home__card home__hero">
      {body.guarantee && !noFigure ? (
        /*
         * The rule's ⓘ sits by the figure it explains. Beside the tile's own
         * label it pushed *Guaranteed minimum* onto two lines at 390.
         */
        <span className="home__hero-head">
          <span className="home__eyebrow">{HERO_LABEL[state]}</span>
          <button
            type="button"
            className="home__info"
            aria-label="How the guaranteed minimum works"
            aria-expanded={rule}
            onClick={() => setRule(!rule)}
          >
            i
          </button>
        </span>
      ) : (
        <span className="home__eyebrow">{noFigure ? "Sales" : HERO_LABEL[state]}</span>
      )}
      <div className="home__figure">
        <span className="home__amount">
          {noFigure ? body.sales.counted : <Money piastres={body.amount_piastres!} />}
        </span>
        {body.split ? (
          /*
           * Salary plus commission (audit, 1 October 2026): EGP 10,000.00
           * earned above EGP 0.00 in sales read as a mistake. The two parts
           * are the server's and add up to the figure above; only the
           * commission grows as she sells.
           */
          <div className="home__split">
            <div>
              <span className="home__split-label">Monthly salary</span>
              <span className="home__split-value">{body.split.salary}</span>
              <span className="home__split-note">fixed</span>
            </div>
            <div className="home__split--grows">
              <span className="home__split-label">Commission</span>
              <span className="home__split-value">{body.split.commission}</span>
              <span className="home__split-note">
                {rate !== null ? `${rate / 100}% of ` : ""}
                {body.sales.counted} in sales
              </span>
            </div>
          </div>
        ) : body.guarantee && !noFigure ? (
          /*
           * Guaranteed minimum (owner, 1 October 2026): split out the way a
           * salary is. Unlike a salary the two do not add up - they are paid
           * the higher - so the tile the figure above comes from carries the
           * accent and says so in words, and one line names the rule.
           */
          <>
            <div className="home__split">
              <div className={body.guarantee.applied ? "home__split--grows" : undefined}>
                <span className="home__split-label">Guaranteed minimum</span>
                <span className="home__split-value">{body.guarantee.amount}</span>
                <span className="home__split-note">{guaranteeNote(body.guarantee)}</span>
              </div>
              <div className={body.guarantee.applied ? undefined : "home__split--grows"}>
                <span className="home__split-label">Commission</span>
                <span className="home__split-value">{body.guarantee.commission}</span>
                <span className="home__split-note">
                  {rate !== null ? `${rate / 100}% of ` : ""}
                  {body.sales.counted} in sales
                </span>
              </div>
            </div>
            {rule && (
              <p className="home__why">
                You're paid the higher of the two. The minimum counts once your targets are met and checked.
              </p>
            )}
          </>
        ) : noFigure ? (
          body.note && <span className="home__sub">{body.note}</span>
        ) : (
          <span className="home__sub">
            {/* "10% of" would be untrue on a guaranteed-minimum month, where
                the total may be more than the commission. Both halves are
                true on every arrangement. */}
            <strong>{body.sales.counted}</strong> in sales
            {rate !== null && <> · {rate / 100}% commission</>}
          </span>
        )}
        {/*
         * ADR 0070, the owner's ask: her month says a bonus was added. Already
         * in the figure above, so it reads as *included*, never as more to
         * come - and on its own line, so the salary and commission tiles
         * still say what they say.
         */}
        {body.bonus && !noFigure && (
          <span className="home__bonus">
            Includes a bonus of <strong>{body.bonus.amount}</strong> from HBA
          </span>
        )}
      </div>

      {compare && (
        <span
          className={
            compare.change_pct >= 0 ? "home__compare home__compare--up" : "home__compare home__compare--down"
          }
        >
          <span aria-hidden="true">{compare.change_pct >= 0 ? "▲" : "▼"}</span>
          {Math.abs(compare.change_pct)}% in sales vs {compare.window}
          <span className="home__compare-note">
            {" "}({compare.now} against {compare.before})
          </span>
        </span>
      )}

      {state === "open" && body.window.days_left !== null && (
        <div className="home__progress">
          <div
            className="home__bar"
            role="progressbar"
            aria-label="How far through the month"
            aria-valuenow={Math.round(body.window.progress_pct)}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <span style={{ width: `${Math.max(2, Math.min(100, body.window.progress_pct))}%` }} />
          </div>
          <div className="home__ends">
            <span>{dayMonth(body.window.opens)}</span>
            <strong>
              {body.window.days_left === 0
                ? "Last day"
                : `${body.window.days_left} day${body.window.days_left === 1 ? "" : "s"} left`}
            </strong>
            <span>{dayMonth(body.window.closes)}</span>
          </div>
        </div>
      )}

      <Link className="home__link" to={`/earnings?month=${home.month}`}>
        See how it adds up →
      </Link>

      <div className="home__rule" />

      <Payment month={home.month} state={state} settlement={settlement} transferDate={transfer?.occurred_at ?? null} reference={transfer?.reference ?? null} />
    </section>
  );
}

/**
 * Under the minimum, where its targets stand - §15's three answers, with
 * `null` (nobody has recorded them) kept apart from a miss. Where the minimum
 * is the figure, it says so in words as well as in colour.
 */
function guaranteeNote(guarantee: NonNullable<MyHome["earnings"]["guarantee"]>): string {
  if (guarantee.applied) return "targets met · paid this month";
  if (guarantee.targets_achieved === null) return "targets not recorded yet";
  if (!guarantee.targets_achieved) return "targets not met";
  return guarantee.targets_verified ? "targets met" : "targets met, being checked";
}

/** When the money arrives, from the ledger - one row, and a way to Payments. */
function Payment({
  month,
  state,
  settlement,
  transferDate,
  reference,
}: {
  month: string;
  state: HomeState;
  settlement?: PaymentMonth;
  transferDate: string | null;
  reference: string | null;
}) {
  const recorded = settlement && settlement.paid_piastres > 0;
  const part = recorded && settlement.state === "partially_paid";
  const expected = recorded ? null : expectedRecording(month, state, cairoToday());
  const when = expected ? expected.label.replace(/ \d{4}$/, "") : null;

  let label: string;
  let value: React.ReactNode;
  if (recorded) {
    label = part ? "Paid so far" : "Paid";
    value = part ? (
      <>
        <Money piastres={settlement.paid_piastres} /> of <Money piastres={settlement.obligation_piastres} />
      </>
    ) : (
      <>
        <Money piastres={settlement.paid_piastres} />
        {transferDate && ` · ${formatDay(transferDate.slice(0, 10))}`}
        {reference && ` · ${reference}`}
      </>
    );
  } else if (state === "settled") {
    // One of the two places a settled month differs (ADR 0054). HBA paid it
    // directly, so there is no transfer here to show - and that is normal.
    label = "Payment";
    value = "Paid directly by HBA";
  } else if (expected?.passed) {
    label = "Payment";
    value = `Expected ${when} — not recorded yet`;
  } else if (expected) {
    label = "Next payment";
    value = `Around ${when}`;
  } else {
    label = "Payment";
    value = "No payment recorded here";
  }

  return (
    <Link className="home__pay" to="/payments">
      <span className="home__pay-icon" aria-hidden="true">
        <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3.5" y="5" width="17" height="15" rx="2.5" />
          <path d="M3.5 10h17M8 3v4M16 3v4" />
        </svg>
      </span>
      <span className="home__pay-text">
        <span className="home__pay-label">{label}</span>
        <span className="home__pay-value">{value}</span>
      </span>
      <svg className="home__chevron" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="m9 6 6 6-6 6" />
      </svg>
    </Link>
  );
}

/**
 * Her orders, in the three states the Orders tab files them under (the
 * owner, 27 September, amending batch L's five): *delivered*, *pending* and
 * *failed* - failed holding every order that did not count, whether the
 * courier failed, the order was cancelled or it was refunded. Each row on the
 * Orders tab still names which.
 *
 * **Each count opens its own orders** (ADR 0048, amended). The card is no
 * longer one link: the head and the bar open them all, and each count with
 * something in it opens the matching filter - never a link inside a link. A
 * zero opens nothing, so it is plain text rather than a way into an empty
 * list.
 */
const OUTCOMES = [
  { key: "delivered", status: "earned", word: "delivered" },
  { key: "pending", status: "pending", word: "pending" },
  { key: "failed", status: "void", word: "failed" },
] as const;

function Orders({ home }: { home: MyHome }) {
  const o = home.outcomes;
  const count = {
    delivered: o.delivered,
    pending: o.pending,
    // The same orders as the Orders tab's *Failed* filter: every void one.
    failed: o.failed + o.cancelled + o.refunded,
  };
  const parts = OUTCOMES.map((outcome) => ({ ...outcome, n: count[outcome.key] }));
  const total = parts.reduce((sum, part) => sum + part.n, 0);

  return (
    <section className="home__card home__orders" aria-label="Orders">
      <Link className="home__orders-all" to="/orders">
        <div className="home__orders-head">
          <span>
            <span className="home__big">{home.earnings.orders.counted}</span>{" "}
            <span className="home__muted">
              {home.earnings.orders.counted === 1 ? "order counted" : "orders counted"}
            </span>
          </span>
          <span className="home__faint home__orders-uses">
            {home.earnings.orders.uses} code {home.earnings.orders.uses === 1 ? "use" : "uses"}
            <svg className="home__chevron" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="m9 6 6 6-6 6" />
            </svg>
          </span>
        </div>
        {total > 0 && (
          <div className="home__stack" aria-hidden="true">
            {parts
              .filter((part) => part.n > 0)
              .map((part) => (
                <span key={part.key} className={`home__seg home__seg--${part.key}`} style={{ flexGrow: part.n }} />
              ))}
          </div>
        )}
        <span className="visually-hidden">, see all orders</span>
      </Link>
      <ul className="home__legend">
        {parts.map((part) => (
          <li key={part.key}>
            {part.n > 0 ? (
              <Link className={`home__key home__key--${part.key}`} to={`/orders?status=${part.status}`}>
                <span className="home__dot" aria-hidden="true" />
                <span className="home__key-word">{part.n} {part.word}</span>
              </Link>
            ) : (
              <span className="home__key home__key--none">
                <span className="home__dot" aria-hidden="true" />
                {part.n} {part.word}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Where she stands, what an order is worth, and her content - each a way in. */
function Tiles({ home }: { home: MyHome }) {
  const c = home.content;
  return (
    <div className="home__tiles">
      <Link className="home__tile" to="/ranking">
        <svg className="home__tile-icon home__tile-icon--rank" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0V4Z" />
          <path d="M17 5h3v2a3 3 0 0 1-3 3M7 5H4v2a3 3 0 0 0 3 3" />
        </svg>
        <span className="home__tile-value">{home.rank ? `#${home.rank.rank}` : "—"}</span>
        <span className="home__tile-label">{home.rank ? `of ${home.rank.of} models` : "not ranked yet"}</span>
      </Link>
      <Link className="home__tile" to="/orders">
        <svg className="home__tile-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 7h12l-1 13H7L6 7Z" />
          <path d="M9 7a3 3 0 0 1 6 0" />
        </svg>
        <span className="home__tile-value">{home.earnings.sales.average_order ?? "—"}</span>
        <span className="home__tile-label">average order</span>
      </Link>
      {c ? (
        <Link className="home__tile" to="/targets">
          <svg className="home__tile-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="3" y="6" width="13" height="12" rx="2.5" />
            <path d="m16 10 5-3v10l-5-3" />
          </svg>
          {c.actual_videos === null && c.actual_stories === null ? (
            <>
              <span className="home__tile-value home__tile-value--small">Not recorded yet</span>
              <span className="home__tile-label">content</span>
            </>
          ) : (
            <span className="home__tile-lines">
              {c.required_videos ? <span><strong>{c.actual_videos ?? 0}/{c.required_videos}</strong> videos</span> : null}
              {c.required_stories ? <span><strong>{c.actual_stories ?? 0}/{c.required_stories}</strong> stories</span> : null}
            </span>
          )}
        </Link>
      ) : home.best_seller ? (
        <Link className="home__tile" to="/best">
          <svg className="home__tile-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9L12 3Z" />
          </svg>
          <span className="home__tile-value home__tile-value--small home__clamp">{home.best_seller.title}</span>
          <span className="home__tile-label">best seller · {home.best_seller.quantity} sold</span>
        </Link>
      ) : (
        <Link className="home__tile" to="/targets">
          <svg className="home__tile-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="8.5" />
            <circle cx="12" cy="12" r="4.5" />
          </svg>
          <span className="home__tile-value home__tile-value--small">No targets</span>
          <span className="home__tile-label">this month</span>
        </Link>
      )}
    </div>
  );
}

/** Her best seller, when the third tile is her content (batch L). */
function BestSeller({ home }: { home: MyHome }) {
  const best = home.best_seller!;
  return (
    <Link className="home__card home__row" to="/best">
      <span className="home__row-icon" aria-hidden="true">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9L12 3Z" />
        </svg>
      </span>
      <span className="home__row-text">
        <span className="home__pay-label">Best seller this month</span>
        <span className="home__pay-value home__clamp">{best.title}</span>
      </span>
      <span className="home__faint">{best.quantity} sold</span>
    </Link>
  );
}

/**
 * Her code as a link that applies it at checkout (batch L). The phone's own
 * share sheet where there is one; otherwise the link is copied.
 */
function Share({ share }: { share: NonNullable<MyHome["share"]> }) {
  const [done, setDone] = useState<string | null>(null);

  async function go() {
    const text = `Use my code ${share.code} at HBA`;
    try {
      if (share.url && typeof navigator.share === "function") {
        await navigator.share({ title: "HBA", text, url: share.url });
        return;
      }
      await navigator.clipboard.writeText(share.url ?? share.code);
      setDone(share.url ? "Link copied" : "Code copied");
      window.setTimeout(() => setDone(null), 1600);
    } catch {
      // Dismissed, or the clipboard is not allowed here. The code is on the
      // screen either way; a failed convenience is not an error to show.
    }
  }

  return (
    <section className="home__card home__share">
      <span className="home__share-text">
        <strong>Share your code</strong>
        <span className="home__faint">
          {share.url ? "A shop link with your discount already applied" : share.code}
        </span>
      </span>
      <button type="button" className="home__share-button" onClick={go}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 15V3M7 8l5-5 5 5" />
          <path d="M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6" />
        </svg>
        {done ?? "Share"}
      </button>
    </section>
  );
}

/**
 * Her year as bars, sales or uses (the owner, 27 September: bars for both).
 * One total per month is a set of separate buckets, which bars compare and a
 * line does not; and the switch keeps the chart's shape under her thumb.
 * Tapping a bar says that month's figure.
 */
function YearBars({ home }: { home: MyHome }) {
  const { months } = usePortal();
  const [metric, setMetric] = useState<"sales" | "uses">("sales");
  const [picked, setPicked] = useState(home.month);

  useEffect(() => setPicked(home.month), [home.month]);

  const year = home.month.slice(0, 4);
  const rows = home.year.months
    .filter((row) => row.month.startsWith(year) && months.includes(row.month))
    .sort((a, b) => a.month.localeCompare(b.month));

  if (rows.length === 0) return null;

  const value = (row: (typeof rows)[number]) =>
    metric === "sales" ? row.sales_piastres ?? 0 : row.uses ?? 0;
  const max = Math.max(1, ...rows.map(value));
  const chosen = rows.find((row) => row.month === picked) ?? rows[rows.length - 1];
  const chosenIndex = Number(chosen.month.slice(5)) - 1;

  return (
    <section className="home__card home__year">
      <div className="home__year-head">
        <span className="home__eyebrow">{year} so far</span>
        <div className="home__switch" role="radiogroup" aria-label="Show">
          {(["sales", "uses"] as const).map((option) => (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={metric === option}
              className={metric === option ? "home__switch-on" : undefined}
              onClick={() => setMetric(option)}
            >
              {option === "sales" ? "Sales" : "Uses"}
            </button>
          ))}
        </div>
      </div>
      <div className="home__year-figure">
        <span className="home__faint">
          {LONG[chosenIndex]}
          {chosen.in_progress ? " · so far" : ""}
        </span>
        <span className="home__year-value">
          {metric === "sales"
            ? chosen.sales_piastres === null
              ? "—"
              : formatEgp(chosen.sales_piastres)
            : chosen.uses === null
              ? "—"
              : `${chosen.uses} code use${chosen.uses === 1 ? "" : "s"}`}
        </span>
      </div>
      <div className="home__bars" style={{ gridTemplateColumns: `repeat(${rows.length}, minmax(0, 1fr))` }}>
        {rows.map((row) => {
          const index = Number(row.month.slice(5)) - 1;
          const on = row.month === chosen.month;
          return (
            <button
              key={row.month}
              type="button"
              className={on ? "home__col home__col--on" : row.month === home.month ? "home__col home__col--this" : "home__col"}
              aria-label={`${LONG[index]}: ${
                metric === "sales"
                  ? row.sales_piastres === null ? "no figure" : formatEgp(row.sales_piastres)
                  : `${row.uses ?? 0} uses`
              }`}
              aria-pressed={on}
              onClick={() => setPicked(row.month)}
            >
              <span className="home__bar-fill" style={{ height: `${Math.max(3, (value(row) / max) * 100)}%` }} />
              <span className="home__bar-label">{SHORT[index].charAt(0)}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

/** The shape of Home while it loads, so nothing jumps when it arrives. */
function HomeSkeleton() {
  return (
    <div className="home" aria-busy="true" aria-label="Loading">
      <div className="home__monthrow">
        <span className="home__ghost" style={{ width: 170, height: 24 }} />
        <span className="home__ghost" style={{ width: 96, height: 24, borderRadius: 999 }} />
      </div>
      <div className="home__card home__ghost" style={{ height: 300 }} />
      <div className="home__card home__ghost" style={{ height: 116 }} />
      <div className="home__tiles">
        <div className="home__tile home__ghost" style={{ height: 96 }} />
        <div className="home__tile home__ghost" style={{ height: 96 }} />
        <div className="home__tile home__ghost" style={{ height: 96 }} />
      </div>
    </div>
  );
}
