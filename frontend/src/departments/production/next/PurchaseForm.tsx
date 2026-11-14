import { useEffect, useMemo, useState } from "react";

import { api } from "../../../lib/api";
import { cairoToday } from "./format";
import { METHODS, PARTS, UNITS, UNIT_PER, perPieceSentence, purchaseBody, purchaseProblem, purchaseSentence, purchaseSums } from "./supplierLogic";
import type { PurchaseDraft } from "./supplierLogic";
import type { OrderRow, PayMethod, PurchasePart, PurchaseUnit, SupplierAnswer } from "./types";
import { Actions, DateBox, PanelShell, Problem, SelectBox, TextBox, useSubmit } from "./ui";
import type { Run } from "./ui";

type OrdersAnswer = { orders: OrderRow[] };

/**
 * Record a purchase (the owner's): what was bought, how much, at what price, for which order, and an
 * optional deposit. The total is worked out as the person types, with the server's own rounding, and is
 * never sent. `supplier` fixes the supplier (opened from a supplier's page); without it the person picks
 * one from `suppliers` (opened from the list).
 */
export function PurchaseForm({
  supplier,
  suppliers,
  run,
  onClose,
}: {
  supplier?: { id: string; name: string };
  suppliers: readonly { id: string; name: string }[];
  run: Run<SupplierAnswer>;
  onClose: () => void;
}) {
  const today = useMemo(cairoToday, []);
  const [draft, setDraft] = useState<PurchaseDraft>({
    supplierId: supplier?.id ?? "",
    orderId: "",
    item: "",
    part: "fabric",
    quantity: "",
    unit: "kg",
    price: "",
    boughtOn: today,
    expectedOn: "",
    deposit: "",
    depositMethod: "bank_transfer",
    note: "",
  });
  const [orders, setOrders] = useState<OrderRow[] | null>(null);
  const [ordersError, setOrdersError] = useState<string | null>(null);
  const { error, busy, submit } = useSubmit(run);

  // The orders still in production, to pick the one the purchase is for.
  useEffect(() => {
    let current = true;
    api.get<OrdersAnswer>("/api/prod/orders?status=open")
      .then((answer) => {
        if (current) setOrders(answer.orders);
      })
      .catch((caught) => {
        if (!current) return;
        setOrders([]); // a purchase can still be recorded without an order
        setOrdersError(caught instanceof Error ? caught.message : "The orders could not be loaded.");
      });
    return () => {
      current = false;
    };
  }, []);

  const set = (patch: Partial<PurchaseDraft>) => setDraft((before) => ({ ...before, ...patch }));
  const sums = purchaseSums(draft);
  const picked = orders?.find((order) => String(order.id) === draft.orderId);
  const sentence = purchaseSentence(sums);
  const perPieceWords = perPieceSentence(sums.total, draft.part, picked);
  const name = supplier?.name ?? suppliers.find((row) => row.id === draft.supplierId)?.name;

  return (
    <PanelShell
      title={supplier ? `Record a purchase from ${supplier.name}` : "Record a purchase"}
      intro="Fabric, printing, accessories or packaging bought by HBA. The total is worked out for you and goes on the supplier's balance."
      onClose={onClose}
    >
      <form
        className="prod-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit(
            purchaseProblem(draft, today),
            () => api.post<SupplierAnswer>(`/api/prod/suppliers/${draft.supplierId}/purchases`, purchaseBody(draft)),
            `Purchase recorded: ${draft.item.trim()}${name ? ` from ${name}` : ""}.`,
          );
        }}
      >
        {!supplier && (
          <SelectBox
            label="Supplier"
            value={draft.supplierId}
            onChange={(value) => set({ supplierId: value })}
            options={[{ value: "", label: suppliers.length ? "Choose a supplier" : "No active suppliers" }, ...suppliers.map((row) => ({ value: row.id, label: row.name }))]}
          />
        )}
        <SelectBox
          label="For which order, optional"
          value={draft.orderId}
          onChange={(value) => set({ orderId: value })}
          options={[
            { value: "", label: orders === null ? "Loading orders…" : "No order" },
            ...(orders ?? []).map((order) => ({ value: String(order.id), label: `${order.style_name} · ${order.colour} · ${order.code}` })),
          ]}
        />
        {ordersError && (
          <div className="prod-wide">
            <Problem>{ordersError}</Problem>
          </div>
        )}
        <TextBox label="What was bought" value={draft.item} onChange={(value) => set({ item: value })} wide max={200} hint="For example: Heavy fleece, black." />
        <SelectBox
          label="Which part of the cost it is"
          value={draft.part}
          onChange={(value) => set({ part: value as PurchasePart })}
          options={PARTS}
        />
        <TextBox label="Quantity" value={draft.quantity} onChange={(value) => set({ quantity: value })} inputMode="decimal" />
        <SelectBox label="Measured in" value={draft.unit} onChange={(value) => set({ unit: value as PurchaseUnit })} options={UNITS} />
        <TextBox label={`Price per ${UNIT_PER[draft.unit]}, EGP`} value={draft.price} onChange={(value) => set({ price: value })} inputMode="decimal" />
        <DateBox label="Bought on" value={draft.boughtOn} onChange={(value) => set({ boughtOn: value })} max={today} />
        <DateBox label="Expected to arrive, optional" value={draft.expectedOn} onChange={(value) => set({ expectedOn: value })} />
        <TextBox label="Deposit paid now, EGP, optional" value={draft.deposit} onChange={(value) => set({ deposit: value })} inputMode="decimal" />
        <SelectBox
          label="Deposit paid by"
          value={draft.depositMethod}
          onChange={(value) => set({ depositMethod: value as PayMethod })}
          options={METHODS}
        />
        <TextBox label="Note, optional" value={draft.note} onChange={(value) => set({ note: value })} wide max={2000} />
        <div className="prod-wide prod-small prod-sentence" aria-live="polite">
          {sentence ?? "Give the quantity and the price to see the total."}
          {perPieceWords && <div>{perPieceWords}</div>}
        </div>
        <Actions error={error} busy={busy} label="Save purchase" working="Saving…" />
      </form>
    </PanelShell>
  );
}
