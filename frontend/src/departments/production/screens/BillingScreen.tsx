import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Money } from "../../../components/Money";
import { Pager } from "../../../components/Pager";
import { api, can } from "../../../lib/api";
import type { Session } from "../../../lib/api";
import { formatEgp } from "../../../lib/money";
import { BILL_PARTS, BILL_SEARCH_HINT, billDetail, billMatches, billName, billingQuery, billingSentence, quantityLine } from "./billingLogic";
import { cairoToday, shortDay } from "./format";
import { MAX_PHOTO_BYTES, PHOTO_ACCEPT, PRESETS, PRESET_LABELS, payRangeProblem, presetOf, presetRange } from "./paymentLogic";
import type { PayRange } from "./paymentLogic";
import { PurchaseForm } from "./PurchaseForm";
import { PART_WORDS } from "./supplierLogic";
import type { Bill, BillPhoto, BillingList, PurchasePart, SupplierAnswer, SupplierList } from "./types";
import { DateBox, Problem, SearchBox, useIsNarrow } from "./ui";
import type { Run } from "./ui";

const PAGE_SIZES = [25, 50, 100];
const PART_KEYS = BILL_PARTS.filter((part) => part.value !== "").map((part) => part.value as PurchasePart);

/** What a bill's receipt controls do. */
type ReceiptActions = {
  busy: number | null;
  confirming: number | null;
  onAdd: (bill: Bill, files: FileList | null) => void;
  onAsk: (photo: BillPhoto) => void;
  onKeep: () => void;
  onRemove: (bill: Bill, photo: BillPhoto, index: number) => void;
};

/** A bill's receipts: small previews (a "PDF" tile for a PDF), each opening in a new tab. A voided bill has none to add or remove. */
function Receipts({ bill, actions }: { bill: Bill; actions: ReceiptActions }) {
  const picker = useId();
  const busy = actions.busy === bill.id;
  const editable = !bill.voided;
  return (
    <div className="prod-pay__photos">
      {bill.photos.length > 0 && (
        <ul className="prod-thumbs">
          {bill.photos.map((photo, index) => {
            const label = `Receipt ${index + 1} of ${billName(bill)}`;
            return (
              <li key={photo.id} className="prod-thumb">
                <a href={`/api/prod/bill-photos/${photo.id}`} target="_blank" rel="noopener noreferrer" aria-label={`${label} (opens in a new tab)`}>
                  {photo.mime_type.startsWith("image/") ? (
                    <img src={`/api/prod/bill-photos/${photo.id}`} alt="" loading="lazy" />
                  ) : (
                    <span className="prod-thumb__file">PDF</span>
                  )}
                </a>
                {editable &&
                  (actions.confirming === photo.id ? (
                    <span className="prod-lib-confirm">
                      {" "}Remove it?{" "}
                      <button type="button" className="button button--row" disabled={busy} onClick={() => actions.onRemove(bill, photo, index)}>
                        Remove
                      </button>
                      <button type="button" className="button button--row" onClick={actions.onKeep}>
                        Keep
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="prod-thumb__remove"
                      disabled={busy}
                      aria-label={`Remove ${label.charAt(0).toLowerCase()}${label.slice(1)}`}
                      onClick={() => actions.onAsk(photo)}
                    >
                      ×
                    </button>
                  ))}
              </li>
            );
          })}
        </ul>
      )}
      {editable && (
        <label className="button button--row prod-pay__pick" htmlFor={picker}>
          {busy ? "Saving…" : "Add receipt"}
          <span className="prod-sr"> to {billName(bill)}</span>
          <input
            id={picker}
            className="prod-sr"
            type="file"
            multiple
            accept={PHOTO_ACCEPT}
            disabled={busy}
            onChange={(event) => {
              actions.onAdd(bill, event.target.files);
              event.target.value = "";
            }}
          />
        </label>
      )}
    </div>
  );
}

function Total({ bill }: { bill: Bill }) {
  return bill.voided ? (
    <s>
      <Money piastres={bill.total_piastres} />
    </s>
  ) : (
    <Money piastres={bill.total_piastres} kind="agreed" />
  );
}

function What({ bill }: { bill: Bill }) {
  const detail = billDetail(bill);
  return (
    <>
      <div>{bill.voided ? <s>{bill.item}</s> : bill.item}</div>
      <div className="prod-small">
        {PART_WORDS[bill.part]}
        {detail && ` · ${detail}`}
      </div>
      {bill.note && <div className="prod-small prod-pay__note">{bill.note}</div>}
      {bill.voided && (
        <div className="prod-small">
          <span className="prod-pill prod-pill--late">Voided</span> Voided: {bill.void_reason ?? "no reason given"}
        </div>
      )}
    </>
  );
}

const SupplierLink = ({ bill }: { bill: Bill }) => <Link to={`/production/suppliers/${bill.supplier.id}`}>{bill.supplier.name}</Link>;

function BillTable({ bills, actions }: { bills: Bill[]; actions: ReceiptActions }) {
  return (
    <div className="surface prod-scroll">
      <table className="table prod-pay__table">
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">Supplier</th>
            <th scope="col">What</th>
            <th scope="col">Quantity</th>
            <th scope="col" className="numeric">Total</th>
            <th scope="col">Receipt</th>
          </tr>
        </thead>
        <tbody>
          {bills.map((bill) => (
            <tr key={bill.id} className={bill.voided ? "prod-pay--reversed" : undefined}>
              <td>{shortDay(bill.bought_on)}</td>
              <td>
                <SupplierLink bill={bill} />
              </td>
              <td>
                <What bill={bill} />
              </td>
              <td>{quantityLine(bill)}</td>
              <td className="numeric">
                <Total bill={bill} />
              </td>
              <td>
                <Receipts bill={bill} actions={actions} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BillCards({ bills, actions }: { bills: Bill[]; actions: ReceiptActions }) {
  return (
    <ul className="prod-cards prod-pay__cards">
      {bills.map((bill) => (
        <li key={bill.id} className={`prod-card${bill.voided ? " prod-pay--reversed" : ""}`}>
          <div className="prod-pay__top">
            <SupplierLink bill={bill} />
            <Total bill={bill} />
          </div>
          <div className="prod-small">
            {shortDay(bill.bought_on)} · {quantityLine(bill)}
          </div>
          <What bill={bill} />
          <Receipts bill={bill} actions={actions} />
        </li>
      ))}
    </ul>
  );
}

/** `/production/billing` (ADR 0089): every purchase from every supplier, with its receipts. Owner only. */
export function BillingScreen({ session }: { session: Session }) {
  const isOwner = can(session, "production.owner");
  const narrow = useIsNarrow();
  const today = useMemo(cairoToday, []);
  const [range, setRange] = useState<PayRange>(() => presetRange("all", today));
  const [supplier, setSupplier] = useState("");
  const [part, setPart] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0]);
  const [data, setData] = useState<BillingList | null>(null);
  // How many bills each part has, as last seen with every part showing for the same dates and supplier.
  const [counts, setCounts] = useState<{ key: string; byPart: Record<string, number> } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [choosable, setChoosable] = useState<{ id: string; name: string }[] | null>(null);
  const [justAdded, setJustAdded] = useState<{ id: number; item: string } | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const latest = useRef(0);
  const alive = useRef(true);
  const supplierBox = useId();
  const receiptBox = useId();

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      latest.current += 1;
    };
  }, []);

  const wrongWay = payRangeProblem(range);
  const load = useCallback(() => {
    const mine = ++latest.current;
    if (!isOwner || payRangeProblem(range)) return;
    const text = billingQuery(range, supplier, part);
    api.get<BillingList>(`/api/prod/billing${text ? `?${text}` : ""}`)
      .then((answer) => {
        if (latest.current !== mine) return;
        setData(answer);
        setError(null);
        if (!part) {
          const byPart: Record<string, number> = {};
          for (const bill of answer.bills) byPart[bill.part] = (byPart[bill.part] ?? 0) + 1;
          setCounts({ key: billingQuery(range, supplier, ""), byPart });
        }
      })
      .catch((caught) => {
        if (latest.current === mine) setError(caught instanceof Error ? caught.message : "The bills could not be loaded.");
      });
  }, [isOwner, range, supplier, part]);
  useEffect(load, [load]);

  const bills = useMemo(() => (data?.bills ?? []).filter((bill) => billMatches(bill, query)), [data, query]);
  const lastPage = Math.max(0, Math.ceil(bills.length / pageSize) - 1);
  const shownPage = Math.min(page, lastPage);
  const pageBills = bills.slice(shownPage * pageSize, (shownPage + 1) * pageSize);
  const searching = query.trim() !== "";

  /** Count for a chip: from the last look at every part; the chosen part always knows its own. */
  function countOf(key: string): number | null {
    const sameLook = counts?.key === billingQuery(range, supplier, "");
    if (key === "") return sameLook ? Object.values(counts!.byPart).reduce((sum, n) => sum + n, 0) : part === "" ? (data?.bills.length ?? null) : null;
    if (sameLook) return counts!.byPart[key] ?? 0;
    return part === key ? (data?.bills.length ?? null) : null;
  }

  async function addReceipts(bill: { id: number; item: string }, list: FileList | null) {
    const files = Array.from(list ?? []);
    if (!files.length) return;
    setNotice(null);
    setProblem(null);
    const tooBig = files.filter((file) => file.size > MAX_PHOTO_BYTES);
    if (tooBig.length) {
      setProblem(`Receipts must be 20 MB or smaller: ${tooBig.map((file) => file.name).join(", ")}.`);
      return;
    }
    setBusy(bill.id);
    const failed: string[] = [];
    let added = 0;
    for (const file of files) {
      try {
        await api.upload(`/api/prod/purchases/${bill.id}/photos`, file);
        if (!alive.current) return;
        added += 1;
      } catch (caught) {
        failed.push(`${file.name}${caught instanceof Error && caught.message ? ` (${caught.message})` : ""}`);
      }
    }
    if (!alive.current) return;
    setBusy(null);
    if (added) {
      setNotice(`${added === 1 ? "Receipt" : `${added} receipts`} added to ${bill.item}.`);
      setJustAdded(null);
      load();
    }
    if (failed.length) setProblem(`Could not add: ${failed.join(", ")}.`);
  }

  async function removeReceipt(bill: Bill, photo: BillPhoto, index: number) {
    setNotice(null);
    setProblem(null);
    setBusy(bill.id);
    try {
      await api.del(`/api/prod/bill-photos/${photo.id}`);
      if (!alive.current) return;
      setConfirming(null);
      setNotice(`Receipt ${index + 1} removed from ${billName(bill)}.`);
      load();
      // The button pressed is gone: the heading takes focus, and the notice is read.
      heading.current?.focus();
    } catch (caught) {
      if (alive.current) setProblem(caught instanceof Error ? caught.message : "The receipt could not be removed.");
    } finally {
      if (alive.current) setBusy(null);
    }
  }

  async function openAdd() {
    setNotice(null);
    setProblem(null);
    setJustAdded(null);
    setAdding(true);
    try {
      const answer = await api.get<SupplierList>("/api/prod/suppliers");
      if (alive.current) setChoosable(answer.suppliers.filter((row) => row.active).map((row) => ({ id: row.id, name: row.name })));
    } catch {
      if (alive.current) setChoosable(data?.suppliers ?? []);
    }
  }

  function closeAdd() {
    setAdding(false);
    setChoosable(null);
    queueMicrotask(() => (addButton.current ?? heading.current)?.focus());
  }

  // The purchase form's write: on success the panel closes, the receipt is offered and the list is read again.
  const run = useCallback<Run<SupplierAnswer>>(
    async (request, done) => {
      try {
        const answer = await request();
        if (!alive.current) return null;
        setAdding(false);
        setChoosable(null);
        setNotice(answer.notice ?? done);
        if (answer.purchase_id !== undefined) setJustAdded({ id: answer.purchase_id, item: done.replace(/^Purchase recorded: /, "").replace(/\.$/, "") });
        load();
        queueMicrotask(() => (addButton.current ?? heading.current)?.focus());
        return null;
      } catch (caught) {
        return caught instanceof Error ? caught.message : "It could not be saved.";
      }
    },
    [load],
  );

  if (!isOwner) {
    return (
      <>
        <div className="page__head">
          <div className="page__title">
            <h1>Billing</h1>
          </div>
        </div>
        <p className="empty">Billing is for the owner only.</p>
      </>
    );
  }

  const chosen = presetOf(range, today);
  const actions: ReceiptActions = {
    busy,
    confirming,
    onAdd: (bill, files) => void addReceipts(bill, files),
    onAsk: (photo) => setConfirming(photo.id),
    onKeep: () => setConfirming(null),
    onRemove: (bill, photo, index) => void removeReceipt(bill, photo, index),
  };
  const partTotals = data ? PART_KEYS.filter((key) => (data.by_part[key] ?? 0) !== 0) : [];

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1 ref={heading} tabIndex={-1}>Billing</h1>
          <span className="page__subtitle">
            {data && !wrongWay ? `What HBA bought, from every supplier · ${billingSentence(data.bills, data.total_piastres)}` : "What HBA bought, from every supplier"}
          </span>
        </div>
        <div className="prod-head-actions">
          <button ref={addButton} type="button" className="button button--primary" disabled={!data} onClick={() => void openAdd()}>
            Add a bill
          </button>
        </div>
      </div>

      {notice && <p className="notice notice--settled" role="status">{notice}</p>}
      {problem && <Problem>{problem}</Problem>}
      {justAdded && (
        <div className="prod-bill-offer">
          <label className="button button--row prod-pay__pick" htmlFor={receiptBox}>
            {busy === justAdded.id ? "Saving…" : "Add the receipt photo"}
            <span className="prod-sr"> for {justAdded.item}</span>
            <input
              id={receiptBox}
              className="prod-sr"
              type="file"
              multiple
              accept={PHOTO_ACCEPT}
              disabled={busy === justAdded.id}
              onChange={(event) => {
                void addReceipts(justAdded, event.target.files);
                event.target.value = "";
              }}
            />
          </label>
          <button type="button" className="button button--quiet button--row" onClick={() => setJustAdded(null)}>
            Not now
          </button>
        </div>
      )}

      {adding && choosable && (
        <PurchaseForm key="bill" suppliers={choosable} run={run} onClose={closeAdd} />
      )}

      <div className="prod-chips" role="group" aria-label="Period">
        {PRESETS.map((preset) => (
          <button
            key={preset}
            type="button"
            className={`chip${chosen === preset ? " chip--on" : ""}`}
            aria-pressed={chosen === preset}
            onClick={() => {
              setRange(presetRange(preset, today));
              setPage(0);
            }}
          >
            {PRESET_LABELS[preset]}
          </button>
        ))}
      </div>
      <div className="prod-sectionbar prod-range" role="group" aria-label="Bought between">
        <DateBox label="From" value={range.from} max={range.to || undefined} onChange={(from) => setRange((before) => ({ ...before, from }))} />
        <DateBox label="To" value={range.to} min={range.from || undefined} onChange={(to) => setRange((before) => ({ ...before, to }))} />
        <div className="prod-field">
          <label className="field__label" htmlFor={supplierBox}>
            Supplier
          </label>
          <select
            id={supplierBox}
            className="input"
            value={supplier}
            onChange={(event) => {
              setSupplier(event.target.value);
              setPage(0);
            }}
          >
            <option value="">All suppliers</option>
            {(data?.suppliers ?? []).map((one) => (
              <option key={one.id} value={one.id}>
                {one.name}
              </option>
            ))}
            {supplier && data && !data.suppliers.some((one) => one.id === supplier) && <option value={supplier}>{supplier}</option>}
          </select>
        </div>
      </div>
      {wrongWay && <Problem>{wrongWay}</Problem>}

      <div className="prod-chips" role="group" aria-label="Part of the cost">
        {BILL_PARTS.map((one) => {
          const count = countOf(one.value);
          return (
            <button
              key={one.value || "all"}
              type="button"
              className={`chip${part === one.value ? " chip--on" : ""}`}
              aria-pressed={part === one.value}
              onClick={() => {
                setPart(one.value);
                setPage(0);
              }}
            >
              {one.label}
              {count !== null && ` · ${count}`}
            </button>
          );
        })}
      </div>

      {data && !wrongWay && !error && (
        <dl className="prod-bill-totals" aria-label="Totals, leaving out voided bills">
          <div>
            <dt>Total</dt>
            <dd>{formatEgp(data.total_piastres)}</dd>
          </div>
          {partTotals.map((key) => (
            <div key={key}>
              <dt>{PART_WORDS[key]}</dt>
              <dd>{formatEgp(data.by_part[key])}</dd>
            </div>
          ))}
        </dl>
      )}

      <SearchBox
        label="Search the bills"
        hint={BILL_SEARCH_HINT}
        value={query}
        onChange={(value) => {
          setQuery(value);
          setPage(0);
        }}
      />

      {error && (
        <div>
          <Problem>{error}</Problem>
          <button type="button" className="button" onClick={load}>
            Try again
          </button>
        </div>
      )}
      {!error && !wrongWay && data === null && <p className="loading" role="status">Loading bills…</p>}
      {data && !wrongWay && !error && (
        <>
          {bills.length === 0 ? (
            <p className="empty">{searching ? "No bill matches." : "No bills here."}</p>
          ) : narrow ? (
            <BillCards bills={pageBills} actions={actions} />
          ) : (
            <BillTable bills={pageBills} actions={actions} />
          )}
          {bills.length > PAGE_SIZES[0] && (
            <Pager
              page={shownPage}
              size={pageSize}
              total={bills.length}
              sizes={PAGE_SIZES}
              suffix={searching ? " matching" : ""}
              onPage={setPage}
              onSize={(size) => {
                setPageSize(size);
                setPage(0);
              }}
            />
          )}
        </>
      )}
    </>
  );
}
