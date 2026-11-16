import { useMemo, useState } from "react";

import { api } from "../../../lib/api";
import { cairoToday, plural } from "./format";
import { countDifferences, countStarted, countsFrom, deliveryProblem, sizesBody, totalOf, whole } from "./logic";
import type { Counts } from "./logic";
import type { Delivery, DeliveryKind, OrderAnswer, OrderView } from "./types";
import { Actions, DateBox, PanelShell, SizeInputs, TextBox, useSubmit } from "./ui";
import type { Run } from "./ui";

/**
 * One delivery leaving the factory: what shipped, and what Khazenly counted.
 * The two counts may be entered on different days, so the second half can be
 * left empty now and filled from the same form later.
 *
 * A count that differs from what shipped is flagged here and asks for a
 * reason. The reason may be given now or later (ADR 0084, decision 5: a
 * mismatch is flagged and the order cannot close until it has one), so saving
 * without it is allowed and says what is still owed.
 */
export function DeliveryForm({
  order,
  delivery,
  kind: startKind,
  run,
  onClose,
}: {
  order: OrderView;
  /** The delivery being completed or corrected; `null` for a new one. */
  delivery: Delivery | null;
  kind: DeliveryKind;
  run: Run;
  onClose: () => void;
}) {
  const today = useMemo(cairoToday, []);
  const [kind, setKind] = useState<DeliveryKind>(delivery?.kind ?? startKind);
  const [shippedOn, setShippedOn] = useState(delivery?.shipped_on ?? today);
  const [shipped, setShipped] = useState<Counts>(() =>
    countsFrom(Object.fromEntries((delivery?.sizes ?? []).map((line) => [line.size, line.shipped]))),
  );
  const [countedOn, setCountedOn] = useState(delivery?.counted_on ?? "");
  const [counted, setCounted] = useState<Counts>(() =>
    countsFrom(Object.fromEntries((delivery?.sizes ?? []).map((line) => [line.size, line.counted]))),
  );
  const [reason, setReason] = useState(delivery?.mismatch_reason ?? "");
  const { error, busy, submit } = useSubmit(run);

  // What this kind of delivery may still take, leaving out the one being corrected.
  const limit = kind === "finished" ? (order.totals.passed ?? 0) : (order.totals.to_fix ?? 0);
  const others = order.deliveries
    .filter((other) => other.kind === kind && other.id !== delivery?.id)
    .reduce((sum, other) => sum + other.shipped_total, 0);
  const room = Math.max(0, limit - others);

  const draft = { kind, shippedOn, shipped, countedOn, counted, room, today };
  const differences = countStarted(draft) ? countDifferences(draft) : [];
  const shippedTotal = totalOf(shipped);
  const countedTotal = totalOf(counted);
  const gap = countedTotal - shippedTotal;
  const title = delivery ? `Delivery ${delivery.number}` : "Record a delivery";
  const fix = kind === "fix";

  return (
    <PanelShell
      title={title}
      intro={
        delivery
          ? "The two counts can be entered on different days. Fill in whichever is still missing."
          : `${plural(room, "piece")} can still ${fix ? "come back from fixing" : "leave the factory"}. The two counts can be entered on different days.`
      }
      onClose={onClose}
    >
      <form
        className="prod-form"
        onSubmit={(event) => {
          event.preventDefault();
          const started = countStarted(draft);
          const shippedBody = sizesBody(shipped, () => false);
          const countedBody = started ? sizesBody(counted, (size) => whole(shipped[size]) > 0) : undefined;
          const why = differences.length ? reason.trim() || null : null;
          submit(
            deliveryProblem(draft),
            () =>
              delivery
                ? api.patch<OrderAnswer>(`/api/prod/deliveries/${delivery.id}`, {
                    shipped_on: shippedOn,
                    shipped: shippedBody,
                    ...(started ? { counted_on: countedOn, counted: countedBody } : {}),
                    mismatch_reason: why,
                  })
                : api.post<OrderAnswer>(`/api/prod/orders/${order.id}/deliveries`, {
                    kind,
                    shipped_on: shippedOn,
                    shipped: shippedBody,
                    ...(started ? { counted_on: countedOn, counted: countedBody } : {}),
                    mismatch_reason: why,
                  }),
            differences.length && !why
              ? "Delivery saved. The counts do not match, so it still needs a reason before the order can close."
              : "Delivery saved.",
          );
        }}
      >
        {!delivery && (
          <div className="prod-field prod-wide">
            <label className="field__label" htmlFor="delivery-kind">
              What is arriving
            </label>
            <select id="delivery-kind" className="input" value={kind} onChange={(event) => setKind(event.target.value as DeliveryKind)}>
              <option value="finished">Finished pieces</option>
              <option value="fix">Pieces that were sent back to be fixed</option>
            </select>
          </div>
        )}
        <DateBox label="Date it left the factory" value={shippedOn} onChange={setShippedOn} max={today} />
        <DateBox label="Date Khazenly counted it" value={countedOn} onChange={setCountedOn} max={today} hint="Leave empty until Khazenly has counted it." />
        <SizeInputs
          legend="Shipped from the factory, counted by the QC manager"
          counts={shipped}
          onChange={(size, value) => setShipped({ ...shipped, [size]: value })}
          total={`Total ${shippedTotal.toLocaleString("en-GB")}`}
        />
        <SizeInputs
          legend="Counted by Khazenly, copied from their dashboard"
          counts={counted}
          onChange={(size, value) => setCounted({ ...counted, [size]: value })}
          total={`Total ${countedTotal.toLocaleString("en-GB")}`}
        />
        {differences.length > 0 && (
          <div className="prod-wide prod-flag prod-flag--refused" role="status">
            {differences.map((line) => (
              <div key={line.size}>
                Size {line.size}: shipped {line.shipped.toLocaleString("en-GB")}, Khazenly counted {line.counted.toLocaleString("en-GB")}.
              </div>
            ))}
            <div>
              {gap < 0 ? `${plural(-gap, "piece")} missing.` : gap > 0 ? `${plural(gap, "piece")} more than shipped.` : "The totals match, but the sizes do not."}{" "}
              Say why below. You can save without a reason, but the order cannot close until it has one.
            </div>
          </div>
        )}
        {differences.length > 0 && (
          <TextBox label="Why the counts differ" value={reason} onChange={setReason} area wide max={1000} />
        )}
        <Actions error={error} busy={busy} label="Save delivery" working="Saving…" />
      </form>
    </PanelShell>
  );
}
