import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Pager } from "../../../components/Pager";
import { api, can } from "../../../lib/api";
import type { Session } from "../../../lib/api";
import { formatEgp } from "../../../lib/money";
import type { Powers } from "./logic";
import {
  arrivalDate,
  arrivalWords,
  decisionAction,
  decisionLine,
  dueWords,
  figuresOf,
  headerLine,
  linkAddress,
  nextWords,
  orderAddress,
  orderLine,
  problemLabel,
} from "./overviewLogic";
import { byUrgency } from "./search";
import type { IncomingArrival, OrderRow, Overview, OverviewDecision, OverviewOwed, OverviewProblem } from "./types";
import { Problem, Steps, StylePhoto, useIsNarrow } from "./ui";

/** How many orders the Overview shows at a time: five, unless the owner asks for more (21 November 2026). */
const ORDER_PAGE_SIZES = [5, 10, 25, 50];

/** One row's frame: the text, then what sits beside it on a wide screen or below it on a phone. */
function Row({ narrow, plain, what, side }: { narrow: boolean; plain?: boolean; what: ReactNode; side: ReactNode }) {
  const tone = plain ? " prod-task--plain" : "";
  return narrow ? (
    <li className={`prod-task prod-task--narrow${tone}`}>
      <div>{what}</div>
      <div className="prod-task__actions">{side}</div>
    </li>
  ) : (
    <li className={`prod-task${tone}`}>
      <div className="prod-task__what">{what}</div>
      <div className="prod-task__side">{side}</div>
    </li>
  );
}

function Card({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className="prod-block" aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      {children}
    </section>
  );
}

function DecisionRow({ item, today, powers, narrow }: { item: OverviewDecision; today: string; powers: Powers; narrow: boolean }) {
  const action = decisionAction(item, powers);
  const line = decisionLine(item, today);
  return (
    <Row
      narrow={narrow}
      plain
      what={
        <>
          <b>{item.title}</b>
          {line && <div className="prod-small">{line}</div>}
        </>
      }
      side={
        action && (
          <Link className="button button--row" to={action.to} aria-label={`${action.label}: ${item.title}`}>
            {action.label}
          </Link>
        )
      }
    />
  );
}

function ProblemRow({ problem, narrow }: { problem: OverviewProblem; narrow: boolean }) {
  return (
    <Row
      narrow={narrow}
      plain
      what={
        <>
          <b>{problem.title}</b>
          {problem.detail && <div className="prod-small">{problem.detail}</div>}
        </>
      }
      side={
        <Link className="prod-rowlink" to={linkAddress(problem.link)} aria-label={problemLabel(problem)}>
          Open
        </Link>
      }
    />
  );
}

function OrderRowView({ row, narrow }: { row: OrderRow; narrow: boolean }) {
  const next = nextWords(row);
  const due = dueWords(row);
  return (
    <Row
      narrow={narrow}
      what={
        <div className="prod-with-photo">
          <StylePhoto url={row.image_url} />
          <div>
            <Link className="prod-rowlink" to={orderAddress(row.id)}>
              {row.style_name} · {row.colour}
            </Link>
            <div className="prod-small">{orderLine(row)}</div>
            <Steps steps={row.steps} />
          </div>
        </div>
      }
      side={
        <>
          {next && <span className={next.ownerTurn ? "prod-warn" : undefined}>{next.text}</span>}
          <span className={due.late ? "prod-late" : undefined}>{due.text}</span>
        </>
      }
    />
  );
}

function ArrivalRowView({ row, narrow }: { row: IncomingArrival; narrow: boolean }) {
  return (
    <Row
      narrow={narrow}
      plain
      what={
        <b>
          <Link className="prod-rowlink" to={orderAddress(row.order.id)}>
            {arrivalWords(row)}
          </Link>
        </b>
      }
      side={<span className={row.late_days > 0 ? "prod-late" : undefined}>{arrivalDate(row)}</span>}
    />
  );
}

function OwedRow({ row, narrow }: { row: OverviewOwed; narrow: boolean }) {
  return (
    <Row
      narrow={narrow}
      plain
      what={
        <>
          <b>
            <Link className="prod-rowlink" to={`/production/suppliers/${row.supplier.id}`}>
              {row.supplier.name}
            </Link>
          </b>
          {row.detail && <div className="prod-small">{row.detail}</div>}
        </>
      }
      side={<span>{formatEgp(row.owed_piastres)}</span>}
    />
  );
}

/**
 * `/production/overview`: what waits for the owner, what is wrong now, every order and what happens
 * next, what arrives next and (for the owner) what is owed. One read, nothing to type. Somebody without the
 * owner's permission gets the same page without the money.
 */
export function OverviewScreen({ session }: { session: Session }) {
  const powers = useMemo<Powers>(
    () => ({ canEdit: can(session, "production.edit"), isOwner: can(session, "production.owner") }),
    [session],
  );
  const narrow = useIsNarrow();
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(ORDER_PAGE_SIZES[0]);
  const [decisionPageAsked, setDecisionPage] = useState(0);
  const [decisionSize, setDecisionSize] = useState(ORDER_PAGE_SIZES[0]);
  // Which answer is the newest: an answer that an earlier request delivers late, or one for a screen
  // that has been left, is dropped.
  const latest = useRef(0);

  const load = useCallback(() => {
    const mine = ++latest.current;
    setError(null);
    api.get<Overview>("/api/prod/overview")
      .then((answer) => {
        if (latest.current === mine) setData(answer);
      })
      .catch((caught) => {
        if (latest.current === mine) setError(caught instanceof Error ? caught.message : "The overview could not be loaded.");
      });
  }, []);

  useEffect(() => {
    load();
    return () => {
      latest.current += 1;
    };
  }, [load]);

  const isOwner = powers.isOwner;
  const newOrder = (
    <Link className="button button--primary" to="/production/orders/new">
      New order
    </Link>
  );
  const figures = data ? figuresOf(data, isOwner) : [];
  const ordered = useMemo(() => (data ? byUrgency(data.orders) : []), [data]);
  // A reload with fewer orders may leave the page past the end: the last page is shown instead.
  const lastPage = Math.max(0, Math.ceil(ordered.length / pageSize) - 1);
  const shownPage = Math.min(page, lastPage);
  const pageRows = ordered.slice(shownPage * pageSize, (shownPage + 1) * pageSize);
  // The decisions too, five at a time (the owner, 21 November 2026), in the order the server sends them.
  const decisions = data?.decisions ?? [];
  const decisionPage = Math.min(decisionPageAsked, Math.max(0, Math.ceil(decisions.length / decisionSize) - 1));
  const decisionRows = decisions.slice(decisionPage * decisionSize, (decisionPage + 1) * decisionSize);

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Production</h1>
          <span className="page__subtitle">{data ? headerLine(data) : "Loading"}</span>
        </div>
        {isOwner && data && data.orders.length > 0 && <div className="prod-head-actions">{newOrder}</div>}
      </div>

      {error && (
        <div>
          <Problem>{error}</Problem>
          <button type="button" className="button" onClick={load}>
            Try again
          </button>
        </div>
      )}

      {!error && data === null && <p className="loading" role="status">Loading the overview…</p>}

      {data && (
        <>
          <dl className={`prod-facts${figures.length === 3 ? " prod-facts--three" : ""}`}>
            {figures.map((figure) => (
              <div key={figure.label}>
                <dt>{figure.label}</dt>
                <dd className={figure.tone ? `prod-${figure.tone === "late" ? "late" : "warn"}` : undefined}>{figure.value}</dd>
              </div>
            ))}
          </dl>

          <div className="prod-halves">
            <Card id="prod-ov-decisions" title={isOwner ? "Waiting for your decision" : "Waiting for the owner"}>
              {data.decisions.length === 0 ? (
                <p className="empty">{isOwner ? "Nothing is waiting for you." : "Nothing is waiting for the owner."}</p>
              ) : (
                <>
                  <ul className="prod-tasks">
                    {decisionRows.map((item) => (
                      <DecisionRow key={item.key} item={item} today={data.today} powers={powers} narrow={narrow} />
                    ))}
                  </ul>
                  {data.decisions.length > ORDER_PAGE_SIZES[0] && (
                    <Pager
                      page={decisionPage}
                      size={decisionSize}
                      total={data.decisions.length}
                      sizes={ORDER_PAGE_SIZES}
                      onPage={setDecisionPage}
                      onSize={(size) => {
                        setDecisionSize(size);
                        setDecisionPage(0);
                      }}
                    />
                  )}
                </>
              )}
            </Card>
            <Card id="prod-ov-problems" title="Problems right now">
              {data.problems.length === 0 ? (
                <p className="empty">No problems right now.</p>
              ) : (
                <ul className="prod-tasks">
                  {data.problems.map((problem, index) => (
                    <ProblemRow key={`${problem.kind}:${index}`} problem={problem} narrow={narrow} />
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <section aria-labelledby="prod-ov-orders">
            <h2 id="prod-ov-orders" className="prod-group">Every order, and what happens next</h2>
            {data.orders.length === 0 ? (
              <div>
                <p className="empty">No orders in production.</p>
                {isOwner && <div className="prod-head-actions">{newOrder}</div>}
              </div>
            ) : (
              <>
                <ul className="surface prod-tasks">
                  {pageRows.map((row) => (
                    <OrderRowView key={row.id} row={row} narrow={narrow} />
                  ))}
                </ul>
                {ordered.length > ORDER_PAGE_SIZES[0] && (
                  <Pager
                    page={shownPage}
                    size={pageSize}
                    total={ordered.length}
                    sizes={ORDER_PAGE_SIZES}
                    onPage={setPage}
                    onSize={(size) => {
                      setPageSize(size);
                      setPage(0);
                    }}
                  />
                )}
              </>
            )}
          </section>

          <div className={`prod-halves prod-halves--after${data.owed === undefined ? " prod-halves--one" : ""}`}>
            <Card id="prod-ov-arriving" title="Arriving next">
              {data.arriving.length === 0 ? (
                <p className="empty">Nothing is on its way.</p>
              ) : (
                <ul className="prod-tasks">
                  {data.arriving.map((row) => (
                    <ArrivalRowView key={row.key} row={row} narrow={narrow} />
                  ))}
                </ul>
              )}
            </Card>
            {data.owed !== undefined && (
              <Card id="prod-ov-owed" title="What you owe">
                {data.owed.length === 0 ? (
                  <p className="empty">You owe no supplier anything.</p>
                ) : (
                  <ul className="prod-tasks">
                    {data.owed.map((row) => (
                      <OwedRow key={row.supplier.id} row={row} narrow={narrow} />
                    ))}
                  </ul>
                )}
              </Card>
            )}
          </div>
        </>
      )}
    </>
  );
}
