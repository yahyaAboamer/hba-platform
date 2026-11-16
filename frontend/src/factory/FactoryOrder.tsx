import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../lib/api";
import { cairoToday, pieces, plural, shortDay } from "../departments/production/next/format";
import { dayWords, reportBody, reportProblem, reportedTotal, totalTyped, typedFrom, unwrap } from "./logic";
import type { Typed } from "./logic";
import type { FactoryOrder } from "./types";

/** What a write answers is not drawn: the order is read again, so the page is always what the server says. */
type Changed = (said: string) => void;

/** A refusal or a mistake, next to what caused it, and announced. */
function Problem({ children }: { children: string }) {
  return (
    <p className="notice notice--refused" role="alert">
      {children}
    </p>
  );
}

/** One submission at a time, and the server's own words if it refuses. */
function useSend() {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const flying = useRef(false);
  async function send(problem: string | null, request: () => Promise<unknown>): Promise<boolean> {
    if (flying.current) return false;
    if (problem) {
      setError(problem);
      return false;
    }
    setError(null);
    flying.current = true;
    setBusy(true);
    try {
      await request();
      return true;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "It could not be sent.");
      return false;
    } finally {
      flying.current = false;
      setBusy(false);
    }
  }
  return { error, busy, send };
}

function SizesCard({ order, children }: { order: FactoryOrder; children?: React.ReactNode }) {
  return (
    <section className="factory__card" aria-labelledby="factory-sizes">
      <h2 id="factory-sizes">Sizes</h2>
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Size</th>
            <th scope="col" className="numeric">Planned</th>
            <th scope="col" className="numeric">You reported cut</th>
            <th scope="col" className="numeric">Confirmed cut</th>
          </tr>
        </thead>
        <tbody>
          {order.sizes.map((line) => (
            <tr key={line.size}>
              <td>{line.size}</td>
              <td className="numeric">{pieces(line.planned)}</td>
              <td className="numeric">{pieces(line.reported)}</td>
              <td className="numeric">{pieces(line.confirmed)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {children}
    </section>
  );
}

/** "Report how many you cut": a box per size, an optional note, and the total on the button. */
function ReportCard({
  order,
  correcting,
  onSent,
  onCancel,
}: {
  order: FactoryOrder;
  correcting: boolean;
  onSent: Changed;
  onCancel: () => void;
}) {
  const [typed, setTyped] = useState<Typed>(() => typedFrom(order.sizes, correcting ? "reported" : "blank"));
  const [note, setNote] = useState(correcting ? (order.report?.note ?? "") : "");
  const { error, busy, send } = useSend();
  const total = totalTyped(typed);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const sent = await send(reportProblem(typed), () =>
      api.put<unknown>(`/api/factory/orders/${order.id}/cut-report`, reportBody(typed, note)),
    );
    if (sent) onSent(correcting ? "Your correction was sent." : "Sent. HBA's QC manager will check and confirm it.");
  }

  return (
    <section className="factory__card" aria-labelledby="factory-report">
      <h2 id="factory-report">Report how many you cut</h2>
      <p className="factory__small">HBA's QC manager checks and confirms these before they count.</p>
      <form onSubmit={submit} noValidate>
        <div className="factory__sizes">
          {order.sizes.map((line) => (
            <label key={line.size} className="factory__field">
              {line.size}
              <input
                className="input"
                inputMode="numeric"
                autoComplete="off"
                value={typed[line.size] ?? ""}
                onChange={(event) => setTyped({ ...typed, [line.size]: event.target.value })}
              />
            </label>
          ))}
        </div>
        <label className="factory__field">
          Note (optional)
          <input className="input" value={note} maxLength={500} autoComplete="off" onChange={(event) => setNote(event.target.value)} />
        </label>
        {error && <Problem>{error}</Problem>}
        <div className="factory__actions">
          <button type="submit" className="button button--primary" disabled={busy}>
            {busy ? "Sending…" : total > 0 ? `Send ${plural(total, "piece")} cut` : "Send pieces cut"}
          </button>
          {correcting && (
            <button type="button" className="button" onClick={onCancel} disabled={busy}>
              Cancel
            </button>
          )}
        </div>
      </form>
    </section>
  );
}

/** "Delivery date": where it stands, moving it with a reason, and who moved it before. */
function DateCard({ order, onMoved }: { order: FactoryOrder; onMoved: Changed }) {
  const [date, setDate] = useState("");
  const [reason, setReason] = useState("");
  const { error, busy, send } = useSend();

  async function submit(event: FormEvent) {
    event.preventDefault();
    const problem = !date
      ? "Give the new date."
      : date === order.delivery_date
        ? "That is already the delivery date."
        : !reason.trim()
          ? "Say why the date will change."
          : null;
    const moved = await send(problem, () =>
      api.post<unknown>(`/api/factory/orders/${order.id}/delivery-date`, { date, reason: reason.trim() }),
    );
    if (moved) {
      setDate("");
      setReason("");
      onMoved("The delivery date was moved.");
    }
  }

  return (
    <section className="factory__card" aria-labelledby="factory-dates">
      <h2 id="factory-dates">Delivery date</h2>
      {order.can_move_date ? (
        <>
          <p className="factory__small">Now {shortDay(order.delivery_date)}. If it will change, tell us the new date and why.</p>
          <form onSubmit={submit} noValidate>
            <label className="factory__field">
              New date
              <input className="input" type="date" min={cairoToday()} value={date} onChange={(event) => setDate(event.target.value)} />
            </label>
            <label className="factory__field">
              Why
              <input
                className="input"
                placeholder="For example: waiting in the print queue"
                maxLength={500}
                autoComplete="off"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </label>
            {error && <Problem>{error}</Problem>}
            <div className="factory__actions">
              <button type="submit" className="button" disabled={busy}>
                {busy ? "Moving…" : "Move the date"}
              </button>
            </div>
          </form>
        </>
      ) : (
        <p className="factory__small">Now {shortDay(order.delivery_date)}.</p>
      )}
      {order.dates.length > 0 && (
        <table className="table factory__history">
          <thead>
            <tr>
              <th scope="col">When</th>
              <th scope="col">Date</th>
              <th scope="col">Moved by</th>
              <th scope="col">Why</th>
            </tr>
          </thead>
          <tbody>
            {order.dates.map((line, index) => (
              <tr key={index}>
                <td>{dayWords(line.on)}</td>
                <td>{shortDay(line.date)}</td>
                <td>{line.by}</td>
                <td>{line.reason ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

/** `/factory/orders/:id`: one order of the factory's - its sizes, the cut it reports, and its delivery date. */
export function FactoryOrderScreen() {
  const { id } = useParams();
  const [order, setOrder] = useState<FactoryOrder | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState(false);
  const latest = useRef(0);
  const flag = useRef<HTMLDivElement>(null);
  // Set after a write, so focus lands on what changed once the page has redrawn: the button that was
  // pressed has gone, and a keyboard or screen-reader user would otherwise be left at the top.
  const refocus = useRef(false);

  const load = useCallback(() => {
    const mine = ++latest.current;
    setError(null);
    api.get<unknown>(`/api/factory/orders/${id}`)
      .then((answer) => {
        if (latest.current === mine) setOrder(unwrap<FactoryOrder>(answer, "order"));
      })
      .catch((caught) => {
        if (latest.current === mine) setError(caught instanceof Error ? caught.message : "The order could not be loaded.");
      });
  }, [id]);
  useEffect(() => {
    setOrder(null);
    setNotice(null);
    setCorrecting(false);
    load();
    return () => {
      latest.current += 1;
    };
  }, [load]);

  useEffect(() => {
    if (!refocus.current || !order) return;
    refocus.current = false;
    flag.current?.focus();
  }, [order]);

  const changed = useCallback<Changed>(
    (said) => {
      setNotice(said);
      setCorrecting(false);
      refocus.current = true;
      load();
    },
    [load],
  );

  if (error) {
    return (
      <>
        <Link className="factory__back" to="/factory">← Your orders</Link>
        <Problem>{error}</Problem>
        <div className="factory__actions">
          <button type="button" className="button" onClick={load}>Try again</button>
        </div>
      </>
    );
  }
  if (!order) return <p className="loading" role="status">Loading your order…</p>;

  const waiting = Boolean(order.report);
  const confirmed = order.cut.confirmed_total;
  const showForm = order.can_report_cut && (!waiting || correcting);

  return (
    <>
      <Link className="factory__back" to="/factory">← Your orders</Link>
      <h1 className="factory__h1">{order.style_name} · {order.colour}</h1>
      <p className="factory__sub">
        {order.code} · printing: {order.printing} · deliver by {shortDay(order.delivery_date)}
      </p>

      <div ref={flag} tabIndex={-1} className="factory__live">
        {notice && <p className="notice notice--settled" role="status">{notice}</p>}
        {order.report && (
          <p className="factory__flag" role="status">
            You reported {plural(reportedTotal(order), "piece")} cut on {dayWords(order.report.reported_on)}. Waiting for HBA's QC manager to confirm.
            {order.report.note && <span className="factory__note"> Your note: {order.report.note}</span>}
          </p>
        )}
        {!order.report && confirmed !== null && (
          <p className="factory__small">HBA confirmed {plural(confirmed, "piece")} cut.</p>
        )}
      </div>

      <SizesCard order={order}>
        {waiting && order.can_report_cut && !correcting && (
          <div className="factory__actions">
            <button type="button" className="button" onClick={() => setCorrecting(true)}>
              Correct what I sent
            </button>
          </div>
        )}
      </SizesCard>

      {showForm && (
        <ReportCard
          // A new form each time it opens, so a correction starts from what was sent.
          key={correcting ? "correct" : "first"}
          order={order}
          correcting={correcting}
          onSent={changed}
          onCancel={() => setCorrecting(false)}
        />
      )}

      <DateCard key={`date-${order.id}`} order={order} onMoved={changed} />
    </>
  );
}
