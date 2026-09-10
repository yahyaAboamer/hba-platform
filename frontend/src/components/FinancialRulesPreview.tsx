import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { describeBlocker, formatMonth } from "../lib/money";
import { Money } from "./Money";

export type RulesPreview = {
  month: string;
  source_complete: boolean;
  performance: {
    counted_sales_piastres: number;
    delivered_orders: number;
    pending_orders: number;
    failed_orders: number;
    unavailable_orders: number;
  };
  current_entitlement: {
    payout: { piastres: number };
    blockers: string[];
    is_house: boolean;
  };
  approval: { approved_obligation_piastres: number } | null;
  settlement: { recorded_allocations_piastres: number; legacy_balance_piastres: number };
  requires_transition_reconciliation: boolean;
  legacy_allocations: {
    shopify_order_id: string; source_month: string; allocated_month: string; snapshot_id: number;
  }[];
};

const SOURCE_ISSUES: Record<string, string> = {
  delivery_status_unavailable: "Delivery status is unavailable for some orders.",
  original_delivery_basis_unavailable: "Some original delivery amounts need checking.",
  delivery_status_revision_requires_review: "A previously failed delivery changed status and needs review.",
};

export function RulesPreviewResult({ view }: { view: RulesPreview }) {
  const blocked = view.current_entitlement.blockers.length > 0;
  return <>
    <p className="page__subtitle">Pending and delivered count once. Preview only; payment instructions still use the current rules.</p>
    <dl className="detail__list">
      <div className="detail__row"><dt className="detail__label">Source sales · {formatMonth(view.month)}</dt><dd className="detail__value">
        {view.source_complete ? <Money piastres={view.performance.counted_sales_piastres} /> : "Incomplete source data"}
      </dd></div>
      <div className="detail__row"><dt className="detail__label">Delivery</dt><dd className="detail__value">
        {view.performance.delivered_orders} delivered · {view.performance.pending_orders} pending · {view.performance.failed_orders} failed
        {view.performance.unavailable_orders > 0 && ` · ${view.performance.unavailable_orders} unavailable`}
      </dd></div>
      <div className="detail__row"><dt className="detail__label">Earnings under new rules</dt><dd className="detail__value">
        {view.current_entitlement.is_house ? "House account — no compensation" : blocked ? "Needs checking" : <Money piastres={view.current_entitlement.payout.piastres} />}
      </dd></div>
      <div className="detail__row"><dt className="detail__label">Previously approved</dt><dd className="detail__value">
        {view.approval ? <Money piastres={view.approval.approved_obligation_piastres} kind="agreed" /> : "Not approved"}
      </dd></div>
      <div className="detail__row"><dt className="detail__label">Recorded transfers allocated here</dt><dd className="detail__value"><Money piastres={view.settlement.recorded_allocations_piastres} /></dd></div>
    </dl>
    {blocked && <ul className="detail__blockers">{view.current_entitlement.blockers.map(reason =>
      <li key={reason}>{SOURCE_ISSUES[reason] ?? describeBlocker(reason)}</li>
    )}</ul>}
    {view.requires_transition_reconciliation && <>
      <p>Existing delivery carry needs reconciliation before switching rules.</p>
      <ul>{view.legacy_allocations.map(link => <li key={link.shopify_order_id}>
        Order {link.shopify_order_id}: {formatMonth(link.source_month)} sale, allocated in {formatMonth(link.allocated_month)} (statement {link.snapshot_id}).
      </li>)}</ul>
    </>}
  </>;
}

function PreviewMonth({ affiliateId, month }: { affiliateId: string; month: string }) {
  const [view, setView] = useState<RulesPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let current = true;
    setView(null);
    setError(null);
    api.get<{ financial_rules_preview: RulesPreview }>(
      `/api/affiliates/${affiliateId}/earnings/${month}?rules_preview=true`,
    ).then(body => { if (current) setView(body.financial_rules_preview); })
      .catch(reason => { if (current) setError(reason instanceof Error ? reason.message : "Could not load the preview."); });
    return () => { current = false; };
  }, [affiliateId, month, attempt]);
  if (error) return <p role="alert">{error} <button type="button" className="button" onClick={() => setAttempt(n => n + 1)}>Retry</button></p>;
  if (!view) return <p role="status">Loading preview…</p>;
  return <RulesPreviewResult view={view} />;
}

export function FinancialRulesPreview({ affiliateId, currentMonth, firstMonth }: { affiliateId: string; currentMonth: string; firstMonth: string }) {
  const [open, setOpen] = useState(false);
  const [month, setMonth] = useState(currentMonth);
  return <details className="panel" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary className="panel__head">Financial rules preview</summary>
    {open && <>
      <label>Month <input type="month" value={month} min={firstMonth} max={currentMonth}
        onChange={event => setMonth(event.target.value)} /></label>
      {/^\d{4}-\d{2}$/.test(month) && month >= firstMonth && month <= currentMonth &&
        <PreviewMonth key={`${affiliateId}:${month}`} affiliateId={affiliateId} month={month} />}
    </>}
  </details>;
}
