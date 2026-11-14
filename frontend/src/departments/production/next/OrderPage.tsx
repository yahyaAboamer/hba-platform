import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, can } from "../../../lib/api";
import type { Session } from "../../../lib/api";
import { DeliveryForm } from "./DeliveryForm";
import { cairoToday, pieces, plural, shortDay, stagePhrase, whoWhen } from "./format";
import { BUYER_WORDS, nextButton, panelKey } from "./logic";
import type { Panel, Powers } from "./logic";
import { CostCard, DatesCard, DeliveriesCard, FilesCard, HistoryCard, OwedCard, OwnerCard, SizesCard, StagesCard } from "./OrderCards";
import { ActualCostForm, CancelForm, DateChangeForm, EditForm, ReopenForm, SampleForm, SettleForm, WriteOffForm } from "./OtherForms";
import { CompleteForm, CutForm, FabricForm, InspectionForm } from "./StageForms";
import type { OrderAnswer, OrderView } from "./types";
import { Problem } from "./ui";
import type { Run } from "./ui";

const PRINTING_WORDS = { factory: "printed at the factory", outside: "printed outside", none: "no printing" } as const;

function Facts({ order }: { order: OrderView }) {
  const late = order.lateness_days > 0 && order.status !== "cancelled";
  return (
    <dl className="prod-facts">
      <div>
        <dt>Planned</dt>
        <dd>{pieces(order.totals.planned)}</dd>
      </div>
      <div>
        <dt>Received so far</dt>
        <dd>{pieces(order.received_total)}</dd>
      </div>
      <div>
        <dt>Target date</dt>
        <dd>{shortDay(order.target_date)}</dd>
      </div>
      <div>
        <dt>{order.finished_on ? "Finished" : "Promised for"}</dt>
        <dd className={late ? "prod-late" : undefined}>
          {shortDay(order.finished_on ?? order.delivery_date)}
          {late && ` · ${plural(order.lateness_days, "day")} late`}
        </dd>
      </div>
    </dl>
  );
}

function PanelView({
  panel,
  order,
  run,
  powers,
  onClose,
}: {
  panel: Panel;
  order: OrderView;
  run: Run;
  powers: Powers;
  onClose: () => void;
}) {
  const common = { order, run, onClose };
  switch (panel.kind) {
    case "complete":
      return <CompleteForm {...common} stage={panel.stage} />;
    case "fabric":
      return <FabricForm {...common} />;
    case "cut":
      return <CutForm {...common} />;
    case "inspection":
      return <InspectionForm {...common} />;
    case "sample":
      return <SampleForm {...common} />;
    case "delivery":
      return (
        <DeliveryForm
          key={panelKey(panel)}
          {...common}
          delivery={panel.id === null ? null : (order.deliveries.find((delivery) => delivery.id === panel.id) ?? null)}
          kind={panel.deliveryKind}
        />
      );
    case "date":
      return <DateChangeForm {...common} isOwner={powers.isOwner} />;
    case "writeoff":
      return <WriteOffForm {...common} />;
    case "settle":
      return <SettleForm {...common} />;
    case "reopen":
      return <ReopenForm {...common} stage={panel.stage} />;
    case "cancel":
      return <CancelForm {...common} />;
    case "edit":
      return <EditForm {...common} />;
    case "actual":
      return <ActualCostForm {...common} />;
  }
}

/** `/production/next/orders/:id`: one order, its stages, its pieces and what happens next. */
export function OrderPage({ session }: { session: Session }) {
  const { id } = useParams();
  const powers = useMemo<Powers>(
    () => ({ canEdit: can(session, "production.edit"), isOwner: can(session, "production.owner") }),
    [session],
  );
  const [order, setOrder] = useState<OrderView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [panel, setPanel] = useState<Panel | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Bumped after every write, so the history and the photos read again.
  const [version, setVersion] = useState(0);
  const trigger = useRef<Element | null>(null);
  const today = useMemo(cairoToday, []);

  const load = useCallback(() => {
    setError(null);
    api.get<{ order: OrderView }>(`/api/prod/orders/${id}`)
      .then((answer) => setOrder(answer.order))
      .catch((caught) => setError(caught instanceof Error ? caught.message : "The order could not be loaded."));
  }, [id]);
  useEffect(() => {
    setOrder(null);
    setPanel(null);
    setNotice(null);
    load();
  }, [load]);

  const open = useCallback((next: Panel) => {
    trigger.current = document.activeElement;
    setNotice(null);
    setPanel(next);
  }, []);

  const close = useCallback(() => {
    setPanel(null);
    queueMicrotask(() => {
      const back = trigger.current;
      if (back instanceof HTMLElement && back.isConnected) back.focus();
    });
  }, []);

  const run = useCallback<Run>(async (request, done) => {
    try {
      const answer: OrderAnswer = await request();
      setOrder(answer.order);
      setPanel(null);
      setNotice(done);
      setVersion((before) => before + 1);
      return null;
    } catch (caught) {
      return caught instanceof Error ? caught.message : "It could not be saved.";
    }
  }, []);

  if (error) {
    return (
      <>
        <Link className="prod-back" to="/production/next/orders">← All orders</Link>
        <Problem>{error}</Problem>
        <button type="button" className="button" onClick={load}>Try again</button>
      </>
    );
  }
  if (!order) return <p className="loading" role="status">Loading the order…</p>;

  const action = order.next_action;
  const button = nextButton(order, powers);
  const pillTone = order.status !== "open" ? "prod-pill--ok" : order.flags.late ? "prod-pill--late" : order.flags.waiting_for_owner ? "prod-pill--wait" : "";
  const waitingFor = action && !button ? (action.who === "owner" ? "the owner" : action.who === "factory" ? "the factory" : null) : null;

  return (
    <>
      <Link className="prod-back" to="/production/next/orders">← All orders</Link>
      <div className="page__head">
        <div className="page__title">
          <h1>{order.style_name} · {order.colour}</h1>
          <span className="page__subtitle">
            {order.code} · {order.factory.name ?? "—"} · fabric bought by {BUYER_WORDS[order.fabric_bought_by]} ·{" "}
            {order.printing === "outside" && order.print_supplier?.name ? `printed by ${order.print_supplier.name}` : PRINTING_WORDS[order.printing]}
            {order.repeat_run ? " · repeat run" : ""}
          </span>
        </div>
        <span className={`prod-pill ${pillTone}`}>{stagePhrase(order)}</span>
      </div>

      {notice && <p className="notice notice--settled" role="status">{notice}</p>}

      <div className="prod-nextbar" role="region" aria-label="Next action">
        {action ? (
          <>
            <div>
              <b>Next: {action.what.charAt(0).toLowerCase() + action.what.slice(1)}</b>
              <div className="prod-small">
                {whoWhen(action, today, order.flags.waiting_for_owner)}
                {action.stage === "making" && " · mark making finished first"}
                {waitingFor && ` · waiting for ${waitingFor}`}
              </div>
            </div>
            {button && (
              <button type="button" className="button button--primary" onClick={() => open(button.panel)}>
                {button.label}
              </button>
            )}
          </>
        ) : (
          <div>
            <b>{order.status === "cancelled" ? "This order was cancelled." : "This order is settled and closed."}</b>
            <div className="prod-small">Nothing on it can change now.</div>
          </div>
        )}
      </div>

      {panel && <PanelView key={panelKey(panel)} panel={panel} order={order} run={run} powers={powers} onClose={close} />}

      <Facts order={order} />

      <div className="prod-cols">
        <StagesCard order={order} powers={powers} open={open} run={run} />
        <div className="prod-stack">
          <SizesCard order={order} powers={powers} open={open} />
          <DatesCard order={order} powers={powers} open={open} />
          <DeliveriesCard order={order} powers={powers} open={open} />
          <CostCard order={order} powers={powers} open={open} />
          <OwedCard order={order} />
          <OwnerCard order={order} powers={powers} open={open} />
          <FilesCard order={order} powers={powers} version={version} />
          <HistoryCard order={order} version={version} />
        </div>
      </div>
    </>
  );
}
