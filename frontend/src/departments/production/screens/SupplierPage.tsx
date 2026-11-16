import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api, can } from "../../../lib/api";
import type { Session } from "../../../lib/api";
import { formatEgp } from "../../../lib/money";
import { AccountCard } from "./AccountCard";
import { FactoryLoginCard } from "./FactoryLoginCard";
import type { LoginChanged } from "./FactoryLoginCard";
import { cairoToday } from "./format";
import { PurchaseForm } from "./PurchaseForm";
import { DatesForm, LineForm, PaymentForm, ReverseForm, SupplierForm, VoidForm } from "./SupplierForms";
import { DetailsCard, OrdersCard, PurchasesCard } from "./SupplierCards";
import { hasMoney, openWords, owedFigure, panelFromSupplierOpen, sectionNames, supplierPanelKey, usualFigure } from "./supplierLogic";
import type { SupplierPanel, SupplierPowers } from "./supplierLogic";
import type { SupplierAnswer, SupplierView } from "./types";
import { Problem, useIsNarrow } from "./ui";
import type { Run } from "./ui";

/**
 * The figures under the heading. The three money figures are the owner's alone; the fourth, how late the
 * supplier usually is, is not money and is every viewer's.
 */
function Figures({ supplier }: { supplier: SupplierView }) {
  const money = hasMoney(supplier);
  const owed = supplier.owed_piastres ?? 0;
  const usual = usualFigure(supplier.usual_lateness_days);
  return (
    <dl className={`prod-facts${money ? "" : " prod-facts--one"}`}>
      {money && (
        <>
          <div>
            <dt>You owe now</dt>
            <dd className={owed > 0 ? "prod-warn" : owed < 0 ? "prod-ok" : undefined}>{owedFigure(owed)}</dd>
          </div>
          <div>
            <dt>Held until pieces are fixed</dt>
            <dd>{formatEgp(supplier.held_piastres ?? 0)}</dd>
          </div>
          <div>
            <dt>Paid in {supplier.paid_year}</dt>
            <dd>{formatEgp(supplier.paid_piastres ?? 0)}</dd>
          </div>
        </>
      )}
      <div>
        <dt>Usual lateness</dt>
        <dd className={usual.late ? "prod-late" : undefined}>{usual.text}</dd>
      </div>
    </dl>
  );
}

function PanelView({
  panel,
  supplier,
  run,
  onClose,
}: {
  panel: SupplierPanel;
  supplier: SupplierView;
  run: Run<SupplierAnswer>;
  onClose: () => void;
}) {
  const common = { supplier, run, onClose };
  switch (panel.kind) {
    case "payment":
      return <PaymentForm {...common} />;
    case "opening":
      return <LineForm {...common} mode="opening" />;
    case "adjustment":
      return <LineForm {...common} mode="adjustment" />;
    case "edit":
      return <SupplierForm supplier={supplier} run={run} onClose={onClose} />;
    case "purchase":
      return <PurchaseForm supplier={{ id: supplier.id, name: supplier.name }} suppliers={[]} run={run} onClose={onClose} />;
    case "receive":
    case "expected": {
      const purchase = supplier.purchases.find((candidate) => candidate.id === panel.id);
      return purchase ? <DatesForm purchase={purchase} mode={panel.kind} run={run} onClose={onClose} /> : null;
    }
    case "void": {
      const purchase = supplier.purchases.find((candidate) => candidate.id === panel.id);
      return purchase ? <VoidForm purchase={purchase} supplier={supplier} run={run} onClose={onClose} /> : null;
    }
    case "reverse": {
      const line = supplier.account?.find((candidate) => candidate.id === panel.entry);
      return line ? <ReverseForm line={line} run={run} onClose={onClose} /> : null;
    }
  }
}

/** `/production/suppliers/:id`: one supplier, its account, purchases and orders. */
export function SupplierPage({ session }: { session: Session }) {
  const { id } = useParams();
  const powers = useMemo<SupplierPowers>(
    () => ({
      canEdit: can(session, "production.edit"),
      isOwner: can(session, "production.owner"),
      canManage: can(session, "production.suppliers"),
    }),
    [session],
  );
  const narrow = useIsNarrow();
  const today = useMemo(cairoToday, []);
  const [supplier, setSupplier] = useState<SupplierView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [panel, setPanel] = useState<SupplierPanel | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const trigger = useRef<Element | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  // Set after a panel saved, so focus goes somewhere sensible once the page has redrawn.
  const refocus = useRef(false);
  const panelOpen = useRef(false);
  // Which supplier is on the page (changes with the id and on leaving), and which answer is the newest:
  // an answer for a supplier the person has left, or one that an earlier request delivers late, is dropped.
  const page = useRef(0);
  const latest = useRef(0);
  // The address's supplier as of now, for an inline write that answers after the person moved on.
  const current = useRef(id);
  useEffect(() => {
    current.current = id;
  }, [id]);
  useEffect(() => {
    panelOpen.current = panel !== null;
  }, [panel]);

  // `?open=purchase:<id>` (from a task on the Tasks screen) is read once, cleared from the address at once so
  // a reload or a shared link does not open it again, and used when the supplier has loaded.
  const [params, setParams] = useSearchParams();
  const asked = params.get("open");
  const wanted = useRef<string | null>(null);
  useEffect(() => {
    if (asked === null) return;
    wanted.current = asked;
    setParams(
      (before) => {
        const next = new URLSearchParams(before);
        next.delete("open");
        return next;
      },
      { replace: true },
    );
  }, [asked, setParams]);

  const load = useCallback(() => {
    const mine = ++latest.current;
    setError(null);
    api.get<SupplierAnswer>(`/api/prod/suppliers/${id}`)
      .then((answer) => {
        if (latest.current === mine) setSupplier(answer.supplier);
      })
      .catch((caught) => {
        if (latest.current === mine) setError(caught instanceof Error ? caught.message : "The supplier could not be loaded.");
      });
  }, [id]);
  useEffect(() => {
    setSupplier(null);
    setPanel(null);
    setNotice(null);
    load();
    return () => {
      page.current += 1;
      latest.current += 1;
    };
  }, [load]);

  const open = useCallback((next: SupplierPanel) => {
    trigger.current = document.activeElement;
    setNotice(null);
    setPanel(next);
  }, []);

  // The supplier for this address has loaded: open the form the address asked for, if this person may use it.
  useEffect(() => {
    if (wanted.current === null || !supplier || supplier.id !== id) return;
    const next = panelFromSupplierOpen(wanted.current, supplier, powers);
    wanted.current = null;
    if (next) open(next);
  }, [supplier, id, powers, open]);

  const close = useCallback(() => {
    setPanel(null);
    queueMicrotask(() => {
      const back = trigger.current;
      if (back instanceof HTMLElement && back.isConnected) back.focus();
    });
  }, []);

  const run = useCallback<Run<SupplierAnswer>>(async (request, done) => {
    const here = page.current;
    try {
      const answer = await request();
      // The write is done either way; it is only drawn if this supplier is still the one on the page.
      if (page.current !== here) return null;
      latest.current += 1;
      setSupplier(answer.supplier);
      refocus.current = panelOpen.current;
      setPanel(null);
      setNotice(answer.notice ?? done);
      return null;
    } catch (caught) {
      return caught instanceof Error ? caught.message : "It could not be saved.";
    }
  }, []);

  // An inline write (a receipt) that answered with the page.
  const apply = useCallback((next: SupplierView, said: string) => {
    if (next.id !== current.current) return;
    latest.current += 1;
    setSupplier(next);
    setNotice(said);
  }, []);

  // The factory login changed (invited, resent, switched off): the page it answered with, or else read it again.
  const loginChanged = useCallback<LoginChanged>(
    (answer, said) => {
      const next = (answer as { supplier?: SupplierView } | null)?.supplier;
      if (next && next.factory_login !== undefined) apply(next, said);
      else {
        setNotice(said);
        load();
      }
    },
    [apply, load],
  );

  // After a panel saved and closed: the control that opened it if it is still on the page, else the heading.
  useEffect(() => {
    if (panel !== null || !refocus.current) return;
    refocus.current = false;
    const back = trigger.current;
    const target = back instanceof HTMLElement && back !== document.body && back.isConnected ? back : heading.current;
    target?.focus();
  }, [panel, supplier]);

  if (error) {
    return (
      <>
        <Link className="prod-back" to="/production/suppliers">← All suppliers</Link>
        <Problem>{error}</Problem>
        <button type="button" className="button" onClick={load}>Try again</button>
      </>
    );
  }
  if (!supplier) return <p className="loading" role="status">Loading the supplier…</p>;

  return (
    <>
      <Link className="prod-back" to="/production/suppliers">← All suppliers</Link>
      <div className="page__head">
        <div className="page__title">
          <h1 ref={heading} tabIndex={-1}>{supplier.name}</h1>
          <span className="page__subtitle">
            {sectionNames(supplier.sections)} · {openWords(supplier)}
            {supplier.active ? "" : " · Inactive"}
          </span>
        </div>
        {powers.isOwner && (
          <div className="prod-head-actions">
            <button type="button" className="button button--primary" onClick={() => open({ kind: "payment" })}>
              Record a payment
            </button>
          </div>
        )}
      </div>

      {notice && <p className="notice notice--settled" role="status">{notice}</p>}

      {panel && <PanelView key={supplierPanelKey(panel)} panel={panel} supplier={supplier} run={run} onClose={close} />}

      <Figures supplier={supplier} />

      <div className="prod-stack">
        <AccountCard supplier={supplier} today={today} narrow={narrow} open={open} onChange={apply} heading={heading} />
        <PurchasesCard supplier={supplier} powers={powers} today={today} narrow={narrow} open={open} />
        <OrdersCard supplier={supplier} powers={powers} />
        <DetailsCard supplier={supplier} powers={powers} open={open} />
        {powers.canManage && supplier.factory_login !== undefined && (
          <FactoryLoginCard key={supplier.id} supplierId={supplier.id} login={supplier.factory_login} onChanged={loginChanged} />
        )}
      </div>
    </>
  );
}
