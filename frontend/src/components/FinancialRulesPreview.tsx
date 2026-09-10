import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { api } from "../lib/api";
import { describeBlocker, formatMonth } from "../lib/money";
import { Money } from "./Money";
import { MonthPicker } from "./MonthPicker";
import "./FinancialRulesPreview.css";

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
  settlement: {
    recorded_allocations_piastres: number;
    legacy_balance_piastres: number;
  };
  requires_transition_reconciliation: boolean;
  legacy_allocations: {
    shopify_order_id: string;
    source_month: string;
    allocated_month: string;
    snapshot_id: number;
  }[];
};

const SOURCE_ISSUES: Record<string, string> = {
  delivery_status_unavailable: "Delivery status is unavailable for some orders.",
  original_delivery_basis_unavailable: "Some original delivery amounts need checking.",
  delivery_status_revision_requires_review: "A previously failed delivery changed status and needs review.",
};

/**
 * This is a read-only rehearsal, not an alternative approve button. D01 and
 * the later financial batches own the live switch; opening this panel must
 * not suggest that its pending-inclusive amount is a transfer instruction.
 */
export function FinancialRulesPreview({ affiliateId, currentMonth, firstMonth }: {
  affiliateId: string;
  currentMonth: string;
  firstMonth: string;
}) {
  const [open, setOpen] = useState(false);
  const [month, setMonth] = useState(currentMonth);
  const [selectionNotice, setSelectionNotice] = useState<string | null>(null);
  const eligible = month >= firstMonth && month <= currentMonth;

  function chooseMonth(next: string) {
    // MonthPicker marks months but deliberately permits every choice. This
    // endpoint has a narrower history window: the server's platform floor
    // and this model's collaboration start, never a browser-owned date.
    if (next < firstMonth || next > currentMonth) {
      setSelectionNotice(
        `Choose a month from ${formatMonth(firstMonth)} to ${formatMonth(currentMonth)}.`,
      );
      return;
    }
    setSelectionNotice(null);
    setMonth(next);
  }

  return (
    <details
      className="panel rules-preview"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="rules-preview__heading">Financial rules preview</summary>
      {open && (
        <div className="rules-preview__body">
          <div className="rules-preview__month">
            <span>Month</span>
            <MonthPicker
              value={month}
              onChange={chooseMonth}
              lockFor={(candidate) => candidate > currentMonth ? "future" : null}
            />
          </div>
          {selectionNotice && (
            <p
              className="rules-preview__note"
              role="status"
            >
              {selectionNotice}
            </p>
          )}
          {eligible ? (
            <PreviewMonth
              key={`${affiliateId}:${month}`}
              affiliateId={affiliateId}
              month={month}
            />
          ) : (
            <p className="rules-preview__note">
              Preview history starts in {formatMonth(firstMonth)}.
            </p>
          )}
        </div>
      )}
    </details>
  );
}

function PreviewMonth({ affiliateId, month }: { affiliateId: string; month: string }) {
  const [view, setView] = useState<RulesPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    // Changing model/month must discard the old figures, including a late
    // response from the previous request. A failed load is not zero earnings.
    let current = true;
    setView(null);
    setError(null);
    api
      .get<{ financial_rules_preview: RulesPreview }>(
        `/api/affiliates/${affiliateId}/earnings/${month}?rules_preview=true`,
      )
      .then((body) => {
        if (current) setView(body.financial_rules_preview);
      })
      .catch((reason) => {
        if (current) {
          setError(reason instanceof Error ? reason.message : "Could not load the preview.");
        }
      });
    return () => {
      current = false;
    };
  }, [affiliateId, month, attempt]);

  if (error) {
    return (
      <div
        className="rules-preview__error"
        role="alert"
      >
        <p>{error}</p>
        <button
          type="button"
          className="button"
          onClick={() => setAttempt((n) => n + 1)}
        >
          Retry
        </button>
      </div>
    );
  }
  if (!view) return <p role="status">Loading preview…</p>;
  return <RulesPreviewResult view={view} />;
}

/**
 * Source performance, candidate earnings, an immutable approval and actual
 * transfer allocations are independent facts. Keep their labels separate:
 * subtracting them here would invent a second money engine in the browser.
 */
export function RulesPreviewResult({ view }: { view: RulesPreview }) {
  const blocked = view.current_entitlement.blockers.length > 0;

  return (
    <>
      <p className="rules-preview__note">
        Pending and delivered count once. Preview only; payment instructions still use the current rules.
      </p>
      <dl className="rules-preview__figures">
        <PreviewRow label={`Source sales · ${formatMonth(view.month)}`}>
          {view.source_complete ? (
            <Money piastres={view.performance.counted_sales_piastres} />
          ) : "Incomplete source data"}
        </PreviewRow>
        <PreviewRow label="Delivery">
          {view.performance.delivered_orders} delivered · {view.performance.pending_orders} pending · {view.performance.failed_orders} failed
          {view.performance.unavailable_orders > 0 && ` · ${view.performance.unavailable_orders} unavailable`}
        </PreviewRow>
        <PreviewRow label="Earnings under new rules">
          {view.current_entitlement.is_house ? "House account — no compensation" : blocked ? (
            "Needs checking"
          ) : (
            <Money piastres={view.current_entitlement.payout.piastres} />
          )}
        </PreviewRow>
        <PreviewRow label="Previously approved">
          {view.approval ? (
            <Money
              piastres={view.approval.approved_obligation_piastres}
              kind="agreed"
            />
          ) : "Not approved"}
        </PreviewRow>
        <PreviewRow label="Recorded transfers allocated here">
          <Money piastres={view.settlement.recorded_allocations_piastres} />
        </PreviewRow>
      </dl>
      {blocked && (
        <ul className="rules-preview__issues">
          {view.current_entitlement.blockers.map((reason) => (
            <li key={reason}>{SOURCE_ISSUES[reason] ?? describeBlocker(reason)}</li>
          ))}
        </ul>
      )}
      {/* A legacy allocation links a sale to an old statement; it does not
          prove that money was transferred. Reconciliation remains explicit. */}
      {view.requires_transition_reconciliation && (
        <div className="rules-preview__reconciliation">
          <p>Existing delivery carry needs reconciliation before switching rules.</p>
          <ul className="rules-preview__issues">
            {view.legacy_allocations.map((link) => (
              <li key={link.shopify_order_id}>
                Order {link.shopify_order_id}: {formatMonth(link.source_month)} sale,
                allocated in {formatMonth(link.allocated_month)} (statement {link.snapshot_id}).
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

function PreviewRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rules-preview__row">
      <dt className="rules-preview__label">{label}</dt>
      <dd className="rules-preview__value">{children}</dd>
    </div>
  );
}
