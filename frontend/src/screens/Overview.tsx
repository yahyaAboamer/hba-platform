import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Money } from "../components/Money";
import { MonthPicker } from "../components/MonthPicker";
import type { MonthLock } from "../components/MonthPicker";
import { api } from "../lib/api";
import type { Session } from "../lib/api";
import { currentMonth, describeBlocker, formatMonth } from "../lib/money";

type PayrollRow = {
  affiliate_id: number;
  name: string;
  calculation_state?: string;
  obligation_piastres?: number;
  blockers?: string[];
  is_payable?: boolean;
  /* Historical months carry sales and no commission figure (ADR 0014). */
  net_sales_piastres?: number;
  orders?: number | { earned: number; pending: number; void: number };
};

type PayrollMonth = {
  month: string;
  is_historical: boolean;
  affiliates: PayrollRow[];
  totals: {
    affiliates: number;
    payable_affiliates: number;
    blocked_affiliates: number;
    obligation_piastres: number;
  };
};

/** §16's in-platform notifications. Empty on a healthy platform. */
type Attention = {
  items: {
    key: string;
    severity: "blocking" | "attention";
    text: string;
    detail: string;
    where: string;
  }[];
  blocking: number;
  /** Still true, still unresolved, and somebody chose to stop seeing it. */
  muted: {
    key: string;
    severity: "blocking" | "attention";
    text: string;
    where: string;
  }[];
};

type SyncStatus = {
  orders_indexed: number;
  go_live_month: string | null;
  payroll_can_be_approved: boolean;
  jobs: { failed: number };
};

/**
 * Where a month stands.
 *
 * §12.3's noted tension applies here: a page carries summary figures only where
 * they support the decision made on that page. The decision on this page is
 * *can I run payroll for this month, and if not, what is stopping me* — so the
 * figures are what is owed, who is blocked, and why.
 *
 * Nothing here is a chart. Twenty rows is not a dataset.
 */
/**
 * The owner's month, in the parts a payroll decision is made from. A01.
 *
 * **Every figure arrives computed.** The parts of an expected payout are
 * carved out of the one rounded total on the server, so this renders them and
 * never sums them — three components added in a browser would disagree with
 * the payroll screen the first time one of them rounded, on the screen whose
 * only job is to say how much money to find.
 */
type Summary = {
  active_models: number;
  sales_piastres: number;
  ready: number;
  blocked: number;
  expected: {
    payout_piastres: number;
    commission_piastres: number;
    fixed_piastres: number;
    guarantee_top_up_piastres: number;
  };
  /** Keyed by why: `no_target`, `not_recorded_this_week`, `behind`. */
  needs_review: Record<string, number>;
  top: {
    affiliate_id: number;
    name: string;
    rank: number;
    sales_piastres: number;
    uses: number;
  }[];
};

/** D08's three, and only the last is about her. */
const REVIEW_TEXT: Record<string, string> = {
  no_target: "nothing asked for yet",
  not_recorded_this_week: "nothing recorded this week",
  behind: "behind for the week",
};

export function Overview({ session }: { session: Session }) {
  // Opens on the working month, which before go-live is the month the
  // platform starts in rather than an August it holds nothing for.
  const [month, setMonth] = useState(session.platform.working_month);
  const [payroll, setPayroll] = useState<PayrollMonth | null>(null);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [attention, setAttention] = useState<Attention | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  /**
   * Notices hidden for this browsing session only (A10's *temporary hide*).
   *
   * `sessionStorage`, so it comes back next time - which is the whole
   * difference from a mute. Wrapped, because a private window or blocked site
   * data makes the accessor itself throw, and a panel of notices is not worth
   * a blank screen.
   */
  const [hidden, setHidden] = useState<string[]>(() => {
    try {
      return JSON.parse(sessionStorage.getItem("hidden-notices") ?? "[]");
    } catch {
      return [];
    }
  });

  function hide(key: string) {
    setHidden((was) => {
      const next = [...was, key];
      try {
        sessionStorage.setItem("hidden-notices", JSON.stringify(next));
      } catch {
        // Hiding is a convenience. If it cannot be remembered it still works
        // for this view, which is most of the value.
      }
      return next;
    });
  }

  function reloadNotices() {
    api
      .get<Attention>("/api/operations/attention")
      .then(setAttention)
      .catch(() => undefined);
  }

  function mute(key: string) {
    api
      .post("/api/operations/notices/mute", { key })
      .then(reloadNotices)
      .catch((caught) => setError(caught.message));
  }

  function unmute(key: string) {
    api
      .del(`/api/operations/notices/mute/${key}`)
      .then(reloadNotices)
      .catch((caught) => setError(caught.message));
  }
  const [error, setError] = useState<string | null>(null);
  const [lockNote, setLockNote] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    Promise.all([
      api.get<PayrollMonth>(`/api/payroll/${month}`),
      api.get<SyncStatus>("/api/operations/sync"),
      api.get<Attention>("/api/operations/attention"),
      api.get<Summary>(`/api/payroll/${month}/summary`),
    ])
      .then(([months, status, needing, month_summary]) => {
        setPayroll(months);
        setSync(status);
        setAttention(needing);
        setSummary(month_summary);
      })
      .catch((caught) => setError(caught.message));
    setLockNote(null);
  }, [month]);

  function lockFor(candidate: string): MonthLock {
    if (sync?.go_live_month && candidate < sync.go_live_month) return "historical";
    if (candidate > currentMonth()) return "future";
    return null;
  }

  const blocked = payroll?.affiliates.filter((row) => row.blockers?.length) ?? [];

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Home</h1>
          <span className="page__subtitle">{formatMonth(month)}</span>
        </div>
        <MonthPicker
          value={month}
          onChange={setMonth}
          lockFor={lockFor}
          onLockedClick={(candidate, lock) =>
            setLockNote(
              lock === "historical"
                ? `${formatMonth(candidate)} was settled before the platform, so it shows sales and no commission figure.`
                : `${formatMonth(candidate)} has not finished. Orders are still arriving, so the figures will move.`,
            )
          }
        />
      </div>

      {lockNote && (
        <p className="notice" style={{ marginBottom: "var(--space-4)" }}>
          {lockNote}
        </p>
      )}

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {/*
       * §16's in-platform notifications, where somebody lands rather than
       * behind a tab they have to think to open. Every item is conditional on
       * something genuinely true and genuinely actionable, and the whole panel
       * disappears on a healthy platform - which is what makes it worth
       * reading when it does not.
       *
       * The go-live warning used to be a bespoke banner here. It is one of
       * these now: the judgement about what deserves attention belongs on the
       * server, in one place, rather than being spread across screens that ask
       * the same question differently.
       */}
      {attention && attention.items.length > 0 && (
        <section className="attention">
          {attention.items
            .filter((item) => !hidden.includes(item.key))
            .map((item) => (
              <div
                key={item.key}
                className={
                  item.severity === "blocking"
                    ? "attention__item attention__item--blocking"
                    : "attention__item"
                }
              >
                {/*
                 * A10: a notice points. One for a single record opens that
                 * record; one about several opens a filtered list. Either way
                 * it is a link, because a notice that only describes a problem
                 * leaves somebody hunting for it.
                 */}
                <Link className="attention__text" to={item.where}>
                  {item.text}
                </Link>
                <p className="attention__detail">{item.detail}</p>
                <div className="attention__actions">
                  {/*
                   * **Hide and mute are different promises, so they are
                   * different buttons** (A10).
                   *
                   * Hide is this browser's business and comes back - it lives
                   * in `sessionStorage` and nothing on the server knows about
                   * it. Mute is a decision that outlives the tab, so it is
                   * recorded.
                   *
                   * **Neither resolves anything.** The problem is still there
                   * and the notice is still true; fixing it is what makes it
                   * go away, at which point it stops being generated at all.
                   */}
                  <button
                    type="button"
                    className="attention__action"
                    onClick={() => hide(item.key)}
                  >
                    Hide for now
                  </button>
                  {item.severity !== "blocking" && (
                    <button
                      type="button"
                      className="attention__action"
                      onClick={() => mute(item.key)}
                    >
                      Stop showing this
                    </button>
                  )}
                </div>
              </div>
            ))}
        </section>
      )}

      {/*
        * Muted notices, listed rather than swallowed. A mute is not a
        * resolution: every one of these is still true and still unfixed, and
        * somebody who did not mute it should be able to find it and put it
        * back.
        */}
      {attention && attention.muted.length > 0 && (
        <details className="attention__muted">
          <summary>
            {attention.muted.length} turned off ·{" "}
            {attention.muted.length === 1 ? "it is" : "they are"} still
            unresolved
          </summary>
          <ul>
            {attention.muted.map((item) => (
              <li key={item.key}>
                <Link to={item.where}>{item.text}</Link>
                <button
                  type="button"
                  className="attention__action"
                  onClick={() => unmute(item.key)}
                >
                  Show again
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}

      {/*
        * A month before go-live is a different page, not the same page with
        * zeroes in it. §11.2: those months were settled outside the platform,
        * so "owed" and "blocked" are not questions about them - and answering
        * them with 0 and 5 at the same time, which an earlier version did, is
        * worse than not answering at all.
        */}
      {payroll?.is_historical && (
        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">{formatMonth(month)}</h2>
            <span className="state">settled before the platform</span>
          </div>
          <p className="empty">
            Paid outside the platform, so it shows sales and no commission
            figure. The rates that applied then live in the old system and in
            somebody's memory; applying today's would be misleading.
          </p>
          <table className="table">
            <thead>
              <tr>
                <th>Model</th>
                <th className="numeric">Net sales</th>
              </tr>
            </thead>
            <tbody>
              {payroll.affiliates.map((row) => (
                <tr key={row.affiliate_id}>
                  <td>{row.name}</td>
                  <td className="numeric">
                    <Money piastres={row.net_sales_piastres ?? 0} kind="blocked" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {payroll && !payroll.is_historical && (
        <>
          <div className="overview__figures">
            {/*
              * "Ready to approve", not "owed". Nothing is owed until a month is
              * approved - that is the distinction seven phases exist to keep,
              * and the label was quietly breaking it.
              */}
            <Figure
              label="Ready to approve"
              value={
                <Money
                  piastres={payroll.totals.obligation_piastres}
                  tone={payroll.totals.obligation_piastres > 0 ? "owed" : "neutral"}
                />
              }
              note={`${payroll.totals.payable_affiliates} of ${payroll.totals.affiliates} models`}
            />
            <Figure
              label="Blocked"
              value={
                <span className="overview__count">
                  {payroll.totals.blocked_affiliates}
                </span>
              }
              note={
                payroll.totals.blocked_affiliates
                  ? "Something is missing, not something is wrong"
                  : "Nothing waiting"
              }
            />
            {/*
             * A01: the active model count. Beside the money it explains,
             * because "how much" and "across how many people" are read
             * together and answered separately everywhere else.
             */}
            {summary && (
              <Figure
                label="Active models"
                value={
                  <span className="overview__count">
                    {summary.active_models}
                  </span>
                }
                note={`${summary.ready} ready · ${summary.blocked} blocked`}
              />
            )}
            <Figure
              label="Orders indexed"
              value={
                <span className="overview__count">{sync?.orders_indexed ?? "—"}</span>
              }
              note={sync?.jobs.failed ? `${sync.jobs.failed} failed jobs` : "Sync healthy"}
            />
          </div>

          {/*
           * **Where the money goes, and it is rendered rather than summed.**
           * A01 asks for salaries, commissions and guarantee top-ups
           * separately; the server carves them out of the one rounded payout
           * so the three always add to the figure above, and this screen never
           * does arithmetic on money.
           *
           * Shown only where something is ready. A breakdown of nothing is
           * three zeroes and a heading.
           */}
          {summary && summary.expected.payout_piastres > 0 && (
            <section className="panel">
              <div className="panel__head">
                <h2 className="panel__title">What makes up the payout</h2>
              </div>
              <dl className="detail__list overview__breakdown">
                <div className="detail__row">
                  <dt className="detail__label">Commission on sales</dt>
                  <dd className="detail__value">
                    <Money piastres={summary.expected.commission_piastres} />
                  </dd>
                </div>
                {summary.expected.fixed_piastres > 0 && (
                  <div className="detail__row">
                    <dt className="detail__label">Fixed salaries</dt>
                    <dd className="detail__value">
                      <Money piastres={summary.expected.fixed_piastres} />
                    </dd>
                  </div>
                )}
                {summary.expected.guarantee_top_up_piastres > 0 && (
                  <div className="detail__row">
                    <dt className="detail__label">
                      Guaranteed minimums, above what was sold
                    </dt>
                    <dd className="detail__value">
                      <Money
                        piastres={summary.expected.guarantee_top_up_piastres}
                      />
                    </dd>
                  </div>
                )}
              </dl>
            </section>
          )}

          {/*
           * A01's top three by generated sales. Everybody in the first three
           * places, which on a tie is more than three people - D03 shares a
           * place and skips the next, and a list that cut one of three equals
           * would have picked a winner the rule did not.
           */}
          {summary && summary.top.length > 0 && (
            <section className="panel">
              <div className="panel__head">
                <h2 className="panel__title">Top sellers</h2>
              </div>
              <ol className="overview__top">
                {summary.top.map((row) => (
                  <li key={row.affiliate_id}>
                    <span className="overview__place">{row.rank}</span>
                    <Link to={`/affiliates/${row.affiliate_id}`}>{row.name}</Link>
                    <Money piastres={row.sales_piastres} />
                  </li>
                ))}
              </ol>
            </section>
          )}

          {/*
           * A01's content progress needing review, split by why. Two of the
           * three are HBA's own work rather than anything about a model
           * (D08), so they are never summed into one accusing number.
           */}
          {summary && Object.keys(summary.needs_review).length > 0 && (
            <section className="panel">
              <div className="panel__head">
                <h2 className="panel__title">Content needing a look</h2>
              </div>
              <ul className="overview__review">
                {Object.entries(summary.needs_review).map(([why, count]) => (
                  <li key={why}>
                    <span className="overview__count">{count}</span>{" "}
                    {count === 1 ? "model" : "models"} ·{" "}
                    {REVIEW_TEXT[why] ?? why.replace(/_/g, " ")}
                  </li>
                ))}
              </ul>
              <p className="detail__note overview__reviewnote">
                Only the last of these is about a model. The others are ours.
              </p>
            </section>
          )}

          {/*
           * Orders left the sidebar in the redesign (S02) and this is its way
           * in - beside the count it explains, which is where the design puts
           * it too. Without a link here the screen would still exist and
           * nothing would reach it, which is the exact failure
           * `test_reachability.py` was written after.
           */}
          <p className="overview__all-orders">
            <Link to="/orders">See every attributed order</Link>
          </p>

          <section className="panel">
            <div className="panel__head">
              <h2 className="panel__title">What is stopping {formatMonth(month)}</h2>
            </div>
            {blocked.length === 0 ? (
              <p className="empty">
                Nothing. Every model is ready to approve.
              </p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Waiting on</th>
                    <th className="numeric">Would be</th>
                  </tr>
                </thead>
                <tbody>
                  {blocked.map((row) => (
                    <tr key={row.affiliate_id}>
                      <td>{row.name}</td>
                      <td>
                        <ul className="overview__blockers">
                          {row.blockers!.map((key) => (
                            <li key={key} className="blocker">
                              {describeBlocker(key)}
                            </li>
                          ))}
                        </ul>
                      </td>
                      <td className="numeric">
                        {/*
                         * ADR 0027. Set in the prose face, because it is not an
                         * obligation - it is what the figure would be if the
                         * missing thing arrived.
                         */}
                        <Money
                          piastres={row.obligation_piastres ?? 0}
                          kind="blocked"
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </>
  );
}

function Figure({
  label,
  value,
  note,
}: {
  label: string;
  value: React.ReactNode;
  note: string;
}) {
  return (
    <div className="overview__figure">
      <span className="overview__label">{label}</span>
      <span className="overview__value">{value}</span>
      <span className="overview__note">{note}</span>
    </div>
  );
}
