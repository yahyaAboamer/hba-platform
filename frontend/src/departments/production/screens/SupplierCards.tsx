/**
 * The cards of a supplier's page other than the account: its purchases, its orders and its details.
 *
 * **Money is drawn only when its keys are there.** A purchase's price, total, deposit and void reason are
 * absent for anybody without `production.owner`; nothing below draws a column, a figure or a control for
 * them then, and never a zero in their place.
 */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Money } from "../../../components/Money";
import { shortDay, stagePhrase } from "./format";
import { PART_WORDS, RATING_ROLE_WORDS, hasMoney, latenessWords, priceWords, purchaseDates, quantityWords, sectionNames, starsWords } from "./supplierLogic";
import type { SupplierPanel, SupplierPowers } from "./supplierLogic";
import type { PurchaseView, SupplierOrder, SupplierView } from "./types";

type PurchaseProps = {
  supplier: SupplierView;
  powers: SupplierPowers;
  today: string;
  narrow: boolean;
  open: (panel: SupplierPanel) => void;
};

/** What can be done to one purchase, for this person. A voided one can be changed no more. */
function PurchaseButtons({ purchase, powers, open }: { purchase: PurchaseView; powers: SupplierPowers; open: PurchaseProps["open"] }) {
  if (purchase.voided) return null;
  const received = purchase.received_on !== null;
  return (
    <div className="prod-actions prod-line__actions">
      {powers.canEdit && !received && (
        <button type="button" className="button button--row" onClick={() => open({ kind: "receive", id: purchase.id })}>
          Mark received<span className="prod-sr">: {purchase.item}</span>
        </button>
      )}
      {powers.canEdit && received && (
        <button type="button" className="button button--row" onClick={() => open({ kind: "receive", id: purchase.id })}>
          Change arrival date<span className="prod-sr">: {purchase.item}</span>
        </button>
      )}
      {powers.canEdit && (
        <button type="button" className="button button--row" onClick={() => open({ kind: "expected", id: purchase.id })}>
          Change expected date<span className="prod-sr">: {purchase.item}</span>
        </button>
      )}
      {powers.isOwner && (
        <button type="button" className="button button--row" onClick={() => open({ kind: "void", id: purchase.id })}>
          Void<span className="prod-sr">: {purchase.item}</span>
        </button>
      )}
    </div>
  );
}

/** The item, what part of the cost it is, and its note; struck through, with the reason, once voided. */
function PurchaseItem({ purchase }: { purchase: PurchaseView }) {
  return (
    <>
      <div className={purchase.voided ? "prod-struck" : undefined}>
        <b>{purchase.item}</b>
        {purchase.voided && <span className="prod-sr"> (voided)</span>}
      </div>
      <div className="prod-small">
        {PART_WORDS[purchase.part]}
        {purchase.note ? ` · ${purchase.note}` : ""}
      </div>
      {purchase.voided && (
        <div className="prod-small">
          Voided{purchase.void_reason ? `: ${purchase.void_reason}` : ""}
        </div>
      )}
    </>
  );
}

function PurchaseOrder({ purchase }: { purchase: PurchaseView }) {
  return purchase.order ? (
    <Link to={`/production/orders/${purchase.order.id}`}>
      {purchase.order.style_name} · {purchase.order.colour} · {purchase.order.code}
    </Link>
  ) : (
    <span className="prod-small">No order</span>
  );
}

/** The owner's figures for a purchase: price per unit, total and the deposit paid. */
function PurchaseMoney({ purchase }: { purchase: PurchaseView }) {
  if (purchase.total_piastres === undefined) return null;
  return (
    <>
      <span className={purchase.voided ? "prod-struck" : undefined}>
        <Money piastres={purchase.total_piastres} />
      </span>
      {priceWords(purchase) && <div className="prod-small">{priceWords(purchase)}</div>}
      {(purchase.deposit_piastres ?? 0) > 0 && (
        <div className="prod-small">
          {purchase.deposit_kept ? "Deposit kept as credit" : "Deposit paid"} <Money piastres={purchase.deposit_piastres as number} />
        </div>
      )}
    </>
  );
}

export function PurchasesCard({ supplier, powers, today, narrow, open }: PurchaseProps) {
  const money = hasMoney(supplier);
  const purchases = supplier.purchases;
  return (
    <section className="prod-block" aria-labelledby="prod-purchases">
      <div className="prod-block__head">
        <h2 id="prod-purchases">Purchases</h2>
        {powers.isOwner && supplier.active && (
          <button type="button" className="button button--row" onClick={() => open({ kind: "purchase" })}>
            Record a purchase
          </button>
        )}
      </div>
      {purchases.length === 0 ? (
        <p className="prod-small">Nothing has been bought from {supplier.name} yet.</p>
      ) : narrow ? (
        <ul className="prod-lines">
          {purchases.map((purchase) => {
            const dates = purchaseDates(purchase, today);
            return (
              <li key={purchase.id} className="prod-line">
                <PurchaseItem purchase={purchase} />
                <div className="prod-small">{quantityWords(purchase.quantity, purchase.unit)}</div>
                <div className="prod-small">
                  <PurchaseOrder purchase={purchase} />
                </div>
                <div className={`prod-small${dates.late ? " prod-late" : ""}`}>{dates.text}</div>
                {money && (
                  <div>
                    <PurchaseMoney purchase={purchase} />
                  </div>
                )}
                <PurchaseButtons purchase={purchase} powers={powers} open={open} />
              </li>
            );
          })}
        </ul>
      ) : (
        <div className="prod-scroll">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Item</th>
                <th scope="col">Quantity</th>
                <th scope="col">Order</th>
                <th scope="col">Dates</th>
                {money && <th scope="col" className="numeric">Total</th>}
              </tr>
            </thead>
            <tbody>
              {purchases.map((purchase) => {
                const dates = purchaseDates(purchase, today);
                return (
                  <tr key={purchase.id}>
                    <td>
                      <PurchaseItem purchase={purchase} />
                      <PurchaseButtons purchase={purchase} powers={powers} open={open} />
                    </td>
                    <td>{quantityWords(purchase.quantity, purchase.unit)}</td>
                    <td>
                      <PurchaseOrder purchase={purchase} />
                    </td>
                    <td className={dates.late ? "prod-late" : undefined}>{dates.text}</td>
                    {money && (
                      <td className="numeric">
                        <PurchaseMoney purchase={purchase} />
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ── Orders ───────────────────────────────────────────────────────────────────

/** "PO-2609-04 · Factory · closed 30 Oct · 2 days late · 1.2% rejected": what is known of the order, only. */
function OrderFacts({ order }: { order: SupplierOrder }) {
  const late = latenessWords(order.lateness_days);
  const rejected = order.reject_rate === null || order.reject_rate === undefined ? null : `${order.reject_rate.toFixed(1)}% rejected`;
  return (
    <div className="prod-small">
      {order.code} · {RATING_ROLE_WORDS[order.role]} ·{" "}
      {order.status === "closed" && order.closed_on ? `closed ${shortDay(order.closed_on)}` : order.status === "cancelled" ? "cancelled" : stagePhrase(order)}
      {late && (
        <>
          {" · "}
          <span className={late.late ? "prod-late" : undefined}>{late.text}</span>
        </>
      )}
      {rejected && ` · ${rejected}`}
    </div>
  );
}

/** The right-hand side of an order: its stars, or what can be done about having none. */
function OrderRating({ order, isOwner }: { order: SupplierOrder; isOwner: boolean }) {
  if (order.rating) return <span>{starsWords(order.rating)}</span>;
  if (order.status === "open") return <span className="prod-small">Rate it when the order is settled</span>;
  if (order.status !== "closed") return null;
  // Rating is the owner's, and happens on the order's page, which opens the panel.
  if (isOwner) {
    return (
      <Link className="button button--row" to={`/production/orders/${order.id}?open=rate`}>
        Rate it<span className="prod-sr">: {order.style_name} · {order.colour}</span>
      </Link>
    );
  }
  return <span className="prod-small">Not rated yet</span>;
}

export function OrdersCard({ supplier, powers }: { supplier: SupplierView; powers: SupplierPowers }) {
  return (
    <section className="prod-block" aria-labelledby="prod-supplier-orders">
      <h2 id="prod-supplier-orders">Orders and ratings</h2>
      {supplier.orders.length === 0 ? (
        <p className="prod-small">{supplier.name} has not worked on any order yet.</p>
      ) : (
        <ul className="prod-plain">
          {supplier.orders.map((order) => (
            <li key={`${order.id}-${order.role}`} className="prod-plain__row prod-orderrow">
              <div className="prod-orderrow__what">
                <Link className="prod-rowlink" to={`/production/orders/${order.id}`}>
                  {order.style_name} · {order.colour}
                </Link>
                <OrderFacts order={order} />
                {order.rating?.note && <div className="prod-small">“{order.rating.note}”</div>}
              </div>
              <div className="prod-orderrow__side">
                <OrderRating order={order} isOwner={powers.isOwner} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ── Details ──────────────────────────────────────────────────────────────────

export function DetailsCard({ supplier, powers, open }: { supplier: SupplierView; powers: SupplierPowers; open: PurchaseProps["open"] }) {
  const rows: [string, ReactNode][] = [];
  if (supplier.contact_person) rows.push(["Contact", supplier.contact_person]);
  if (supplier.phone) rows.push(["Phone", <a key="tel" href={`tel:${supplier.phone.replace(/\s+/g, "")}`}>{supplier.phone}</a>]);
  if (supplier.whatsapp) rows.push(["WhatsApp", supplier.whatsapp]);
  if (supplier.city) rows.push(["City", supplier.city]);
  rows.push(["Sections", sectionNames(supplier.sections)]);
  rows.push(["Status", supplier.active ? "Active" : "Inactive: not offered for new purchases"]);
  rows.push(["Code", supplier.code]);
  if (supplier.notes) rows.push(["Notes", supplier.notes]);
  return (
    <section className="prod-block" aria-labelledby="prod-details">
      <div className="prod-block__head">
        <h2 id="prod-details">Details</h2>
        {powers.canManage && (
          <button type="button" className="button button--row" onClick={() => open({ kind: "edit" })}>
            Edit details
          </button>
        )}
      </div>
      <dl className="prod-details">
        {rows.map(([name, value]) => (
          <div key={name}>
            <dt>{name}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
