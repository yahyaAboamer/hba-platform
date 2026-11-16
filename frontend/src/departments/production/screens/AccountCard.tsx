/**
 * A supplier's account (the owner's alone: the `account` key is absent for everybody else, and then no card
 * is drawn). Newest first, with what is owed after each line. A line is never changed or deleted: a wrong
 * one is reversed, with a reason, and shown struck through; a payment can carry a receipt photo.
 */
import { useRef, useState } from "react";
import type { RefObject } from "react";
import { Link } from "react-router-dom";

import { Money } from "../../../components/Money";
import { api } from "../../../lib/api";
import { accountDay, balanceAfterWords, canHaveReceipt, canReverse, directionWords, reversalOf } from "./supplierLogic";
import type { SupplierPanel } from "./supplierLogic";
import type { AccountLine, SupplierAnswer, SupplierView } from "./types";
import { Problem } from "./ui";
import { RECEIPT_TYPES } from "./SupplierForms";

const MAX_RECEIPT_BYTES = 20 * 1024 * 1024;

type Props = {
  supplier: SupplierView;
  today: string;
  narrow: boolean;
  open: (panel: SupplierPanel) => void;
  /** An inline write (a receipt) answered with the supplier's page. */
  onChange: (supplier: SupplierView, notice: string) => void;
  /** The page's heading: focus goes there after a receipt was saved, and the notice is read. */
  heading: RefObject<HTMLHeadingElement | null>;
};

type Actions = {
  busy: boolean;
  pickFor: (line: AccountLine) => void;
  remove: (line: AccountLine) => void;
  reverse: (line: AccountLine) => void;
};

const keyOf = (line: AccountLine): string => (line.id === null ? `open-${line.order?.id ?? "x"}` : `line-${line.id}`);

/** What the line is, in words, with what hangs off it: the order, the note, the reason it was reversed. */
function LineWhat({ line, account }: { line: AccountLine; account: readonly AccountLine[] }) {
  const reversal = reversalOf(line, account);
  return (
    <>
      <div className={line.reversed ? "prod-struck" : undefined}>
        {line.what}
        {line.reversed && <span className="prod-sr"> (reversed)</span>}
      </div>
      {line.order && (
        <div className="prod-small">
          <Link to={`/production/orders/${line.order.id}`}>{line.order.code}</Link>
        </div>
      )}
      {line.not_settled && <div className="prod-small">Worked out now. It becomes a line of its own when the order is settled.</div>}
      {line.reversal ? (
        line.note && <div className="prod-small">Reason: {line.note}</div>
      ) : (
        <>
          {line.note && <div className="prod-small">{line.note}</div>}
          {line.reversed && <div className="prod-small">Reversed{reversal?.note ? `: ${reversal.note}` : ""}</div>}
        </>
      )}
    </>
  );
}

/** A payment's receipt, and what can be done to it; and Reverse where the server allows it. */
function LineActions({ line, actions, owner }: { line: AccountLine; actions: Actions; owner: boolean }) {
  const receipt = canHaveReceipt(line);
  const reverse = canReverse(line);
  if (!owner || (!receipt && !reverse && !line.receipt)) return null;
  return (
    <div className="prod-actions prod-line__actions">
      {line.receipt && line.id !== null && (
        <>
          {line.receipt.mime_type.startsWith("image/") && (
            <a href={`/api/prod/entries/${line.id}/receipt`} target="_blank" rel="noopener noreferrer" className="prod-receipt">
              <img src={`/api/prod/entries/${line.id}/receipt`} alt="Receipt photo" loading="lazy" />
            </a>
          )}
          <a className="button button--row" href={`/api/prod/entries/${line.id}/receipt`} target="_blank" rel="noopener noreferrer">
            View receipt<span className="prod-sr"> for {line.what}</span>
          </a>
        </>
      )}
      {receipt && (
        <>
          <button type="button" className="button button--row" disabled={actions.busy} onClick={() => actions.pickFor(line)}>
            {line.receipt ? "Replace receipt" : "Add receipt"}
            <span className="prod-sr"> for {line.what}</span>
          </button>
          {line.receipt && (
            <button type="button" className="button button--row" disabled={actions.busy} onClick={() => actions.remove(line)}>
              Remove receipt<span className="prod-sr"> for {line.what}</span>
            </button>
          )}
        </>
      )}
      {reverse && (
        <button type="button" className="button button--row" disabled={actions.busy} onClick={() => actions.reverse(line)}>
          Reverse<span className="prod-sr">: {line.what}</span>
        </button>
      )}
    </div>
  );
}

const sign = (piastres: number): string => (piastres > 0 ? "+ " : "− ");

function AmountCell({ line }: { line: AccountLine }) {
  return (
    <span className={line.reversed ? "prod-struck" : undefined}>
      {sign(line.amount_piastres)}
      <Money piastres={Math.abs(line.amount_piastres)} />
      <span className="prod-sr"> ({directionWords(line.amount_piastres)})</span>
    </span>
  );
}

export function AccountCard({ supplier, today, narrow, open, onChange, heading }: Props) {
  const account = supplier.account;
  const picker = useRef<HTMLInputElement>(null);
  const pending = useRef<AccountLine | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!account) return null;

  async function write(request: () => Promise<SupplierAnswer>, done: string, failed: string) {
    setBusy(true);
    setError(null);
    try {
      const answer = await request();
      onChange(answer.supplier, done);
      heading.current?.focus();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : failed);
    } finally {
      setBusy(false);
    }
  }

  const actions: Actions = {
    busy,
    pickFor: (line) => {
      pending.current = line;
      picker.current?.click();
    },
    remove: (line) => {
      if (!window.confirm("Remove the receipt photo from this payment?")) return;
      void write(() => api.del<SupplierAnswer>(`/api/prod/entries/${line.id}/receipt`), "Receipt removed.", "The receipt could not be removed.");
    },
    reverse: (line) => open({ kind: "reverse", entry: line.id as number }),
  };

  function chosen(file: File | undefined) {
    const line = pending.current;
    pending.current = null;
    if (!file || !line) return;
    if (file.size > MAX_RECEIPT_BYTES) {
      setError("Files must be 20 MB or smaller.");
      return;
    }
    void write(
      () => api.upload<SupplierAnswer>(`/api/prod/entries/${line.id}/receipt`, file),
      line.receipt ? "Receipt replaced." : "Receipt added.",
      "The receipt could not be added.",
    );
  }

  return (
    <section className="prod-block" aria-labelledby="prod-account">
      <div className="prod-block__head">
        <h2 id="prod-account">Account</h2>
        <div className="prod-actions">
          {supplier.has_opening === false && (
            <button type="button" className="button button--row" onClick={() => open({ kind: "opening" })}>
              Balance brought forward
            </button>
          )}
          <button type="button" className="button button--row" onClick={() => open({ kind: "adjustment" })}>
            Add a correction
          </button>
        </div>
      </div>
      <input
        ref={picker}
        type="file"
        accept={RECEIPT_TYPES}
        hidden
        aria-label="Choose a receipt photo or PDF"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          chosen(file);
        }}
      />
      {error && <Problem>{error}</Problem>}
      {account.length === 0 ? (
        <p className="prod-small">Nothing on the account yet.</p>
      ) : narrow ? (
        <ul className="prod-lines">
          {account.map((line) => (
            <li key={keyOf(line)} className="prod-line">
              <div className="prod-line__top">
                <span className="prod-small">{line.not_settled ? "So far" : accountDay(line.happened_on, today)}</span>
                <AmountCell line={line} />
              </div>
              <div className="prod-small">{directionWords(line.amount_piastres)}</div>
              <LineWhat line={line} account={account} />
              <div className="prod-small">You owe after this line: {balanceAfterWords(line.balance_after_piastres)}</div>
              <LineActions line={line} actions={actions} owner />
            </li>
          ))}
        </ul>
      ) : (
        <div className="prod-scroll">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col">What</th>
                <th scope="col" className="numeric">Amount</th>
                <th scope="col" className="numeric">You owe after</th>
              </tr>
            </thead>
            <tbody>
              {account.map((line) => (
                <tr key={keyOf(line)}>
                  <td>{line.not_settled ? "So far" : accountDay(line.happened_on, today)}</td>
                  <td>
                    <LineWhat line={line} account={account} />
                    <LineActions line={line} actions={actions} owner />
                  </td>
                  <td className="numeric"><AmountCell line={line} /></td>
                  <td className="numeric">{balanceAfterWords(line.balance_after_piastres)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
