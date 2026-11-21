import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api, can } from "../../../lib/api";
import type { Session } from "../../../lib/api";
import { formatEgp } from "../../../lib/money";
import { cairoDay, pieces, shortDay } from "./format";
import {
  STATUS_WORDS,
  cogsBody,
  cogsProblem,
  cogsText,
  detailsBody,
  detailsDraft,
  detailsProblem,
  hasCogs,
  partWords,
  sizesWords,
} from "./libraryLogic";
import type { DetailsDraft } from "./libraryLogic";
import { COST_LABELS, COST_PARTS, costTotal } from "./logic";
import type { CostText } from "./logic";
import { NOT_SET, decorationWords, hexOf } from "./productLogic";
import type { LibraryFile, LibraryFileKind, LibraryItem, OrderStatus } from "./types";
import { Actions, PanelShell, Problem, StylePhoto, TextBox } from "./ui";

type Answer = { product: LibraryItem };

/** The part's name as the order form says it: "Packaging", not "Special packaging". */
const partLabel = (part: (typeof COST_PARTS)[number]) => (part === "packaging" ? "Packaging" : COST_LABELS[part]);
const PART_LABELS = Object.fromEntries(COST_PARTS.map((part) => [part, partLabel(part)])) as typeof COST_LABELS;

/** A design or a pattern can be any file (AI, PSD, DXF, ZIP...); a size chart is a photo or a PDF. */
const FILE_WORDS: Record<LibraryFileKind, { title: string; add: string; none: string; accept: string | undefined }> = {
  design: { title: "Design files", add: "Add a design file", none: "No design file yet.", accept: undefined },
  size_chart: { title: "Size charts", add: "Add a size chart", none: "No size chart yet.", accept: "image/jpeg,image/png,image/webp,image/gif,application/pdf" },
  pattern: { title: "Pattern files", add: "Add a pattern file", none: "No pattern file yet.", accept: undefined },
};
const FILE_KINDS: LibraryFileKind[] = ["design", "size_chart", "pattern"];

const ORDER_STATUS: Record<OrderStatus, string> = { open: "In production", closed: "Closed", cancelled: "Cancelled" };

/** A Shopify photo, asked for at a size fit for the page's header. */
function bigPhoto(url: string): string {
  try {
    const address = new URL(url);
    if (address.hostname !== "cdn.shopify.com") return url;
    address.searchParams.set("width", "320");
    return address.toString();
  } catch {
    return url;
  }
}

// ── The two panels ───────────────────────────────────────────────────────────

function DetailsPanel({ item, onSaved, onClose }: { item: LibraryItem; onSaved: (item: LibraryItem) => void; onClose: () => void }) {
  const [draft, setDraft] = useState<DetailsDraft>(() => detailsDraft(item));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (key: keyof DetailsDraft) => (value: string) => setDraft({ ...draft, [key]: value });

  async function save(event: FormEvent) {
    event.preventDefault();
    const problem = detailsProblem(draft);
    if (problem) return setError(problem);
    setError(null);
    setBusy(true);
    try {
      const answer = await api.patch<Answer>(`/api/prod/library/${item.id}`, detailsBody(draft));
      onSaved(answer.product);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The details could not be saved.");
      setBusy(false);
    }
  }

  return (
    <PanelShell title="Edit details" intro="A new order for this product starts with these. Orders already made keep their own." onClose={onClose}>
      <form className="prod-form" onSubmit={save} noValidate>
        <TextBox label="Colour code" value={draft.colourCode} onChange={set("colourCode")} max={200} hint="Like #1d1d1f, a Pantone or the mill's code." />
        <TextBox label="Fabric" value={draft.fabricType} onChange={set("fabricType")} max={400} hint="Like Cotton fleece 320 gsm." />
        <TextBox label="Print or embroidery" value={draft.decorationType} onChange={set("decorationType")} max={400} hint="Like DTF print or Embroidery." />
        <TextBox label="Design width, cm" value={draft.width} onChange={set("width")} inputMode="decimal" hint="Like 12 or 12.5." />
        <TextBox label="Notes" value={draft.notes} onChange={set("notes")} area wide max={4000} />
        <Actions error={error} busy={busy} label="Save details" working="Saving…" extra={<button type="button" className="button" onClick={onClose}>Cancel</button>} />
      </form>
    </PanelShell>
  );
}

function CogsPanel({ item, onSaved, onClose }: { item: LibraryItem; onSaved: (item: LibraryItem) => void; onClose: () => void }) {
  const [text, setText] = useState<CostText>(() => cogsText(item.cogs));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const total = costTotal(text);

  async function save(event: FormEvent) {
    event.preventDefault();
    const problem = cogsProblem(text, PART_LABELS);
    if (problem) return setError(problem);
    setError(null);
    setBusy(true);
    try {
      const answer = await api.patch<Answer>(`/api/prod/library/${item.id}`, cogsBody(text));
      onSaved(answer.product);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The COGS could not be saved.");
      setBusy(false);
    }
  }

  return (
    <PanelShell title="Edit COGS" intro="What one piece costs to make, in pounds. Leave a part blank if it is not known yet." onClose={onClose}>
      <form className="prod-form" onSubmit={save} noValidate>
        {COST_PARTS.map((part) => (
          <TextBox key={part} label={PART_LABELS[part]} value={text[part]} onChange={(value) => setText({ ...text, [part]: value })} inputMode="decimal" />
        ))}
        <p className="prod-total prod-wide">{total === null ? "Check the amounts." : `Total ${formatEgp(total)} a piece`}</p>
        <Actions error={error} busy={busy} label="Save COGS" working="Saving…" extra={<button type="button" className="button" onClick={onClose}>Cancel</button>} />
      </form>
    </PanelShell>
  );
}

// ── Files ────────────────────────────────────────────────────────────────────

function FileGroup({
  kind,
  files,
  editable,
  busy,
  confirming,
  onAdd,
  onAskRemove,
  onKeep,
  onRemove,
}: {
  kind: LibraryFileKind;
  files: LibraryFile[];
  editable: boolean;
  busy: boolean;
  confirming: number | null;
  onAdd: (kind: LibraryFileKind, file: File) => void;
  onAskRemove: (file: LibraryFile) => void;
  onKeep: () => void;
  onRemove: (file: LibraryFile) => void;
}) {
  const picker = useRef<HTMLInputElement>(null);
  const words = FILE_WORDS[kind];
  return (
    <div>
      <dt>{words.title}</dt>
      <dd>
        {files.length === 0 ? (
          <span className="prod-small">{editable ? words.none : NOT_SET}</span>
        ) : (
          <ul className="prod-filelist">
            {files.map((file) => (
              <li key={file.id}>
                <a href={file.url} target="_blank" rel="noopener noreferrer">
                  {file.name}
                </a>
                {file.uploaded_by && <span className="prod-small"> · {file.uploaded_by}</span>}
                {editable &&
                  (confirming === file.id ? (
                    <span className="prod-lib-confirm">
                      {" "}Remove it?{" "}
                      <button type="button" className="button button--row" disabled={busy} onClick={() => onRemove(file)}>
                        Remove
                      </button>{" "}
                      <button type="button" className="button button--row" onClick={onKeep}>
                        Keep
                      </button>
                    </span>
                  ) : (
                    <>
                      {" "}
                      <button type="button" className="button button--quiet button--row" aria-label={`Remove ${file.name}`} disabled={busy} onClick={() => onAskRemove(file)}>
                        Remove
                      </button>
                    </>
                  ))}
              </li>
            ))}
          </ul>
        )}
        {editable && (
          <>
            <input
              ref={picker}
              type="file"
              accept={words.accept}
              hidden
              aria-label={words.add}
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) onAdd(kind, file);
              }}
            />
            <button type="button" className="button button--row prod-filelist__add" disabled={busy} onClick={() => picker.current?.click()}>
              {busy ? "Saving…" : words.add}
            </button>
          </>
        )}
      </dd>
    </div>
  );
}

// ── The page ─────────────────────────────────────────────────────────────────

/**
 * `/production/library/:id` (ADR 0087): one product. What Shopify knows (read only), what HBA adds
 * (details, files and, for the owner, the COGS), and the production orders made of it.
 */
export function LibraryPage({ session }: { session: Session }) {
  const { id = "" } = useParams();
  const isOwner = can(session, "production.owner");
  const canEdit = can(session, "production.edit");
  const [item, setItem] = useState<LibraryItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [panel, setPanel] = useState<"details" | "cogs" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [fileBusy, setFileBusy] = useState(false);
  const [confirming, setConfirming] = useState<number | null>(null);

  const address = `/api/prod/library/${encodeURIComponent(id)}`;
  const load = useCallback(() => {
    setError(null);
    return api.get<Answer>(address)
      .then((answer) => setItem(answer.product))
      .catch((caught) => setError(caught instanceof Error ? caught.message : "The product could not be loaded."));
  }, [address]);
  useEffect(() => {
    void load();
  }, [load]);

  function saved(next: LibraryItem, words: string) {
    setItem(next);
    setPanel(null);
    setNotice(words);
  }

  async function fileWrite(request: () => Promise<unknown>, words: string) {
    setFileBusy(true);
    setFileError(null);
    setNotice(null);
    try {
      await request();
      setConfirming(null);
      await load();
      setNotice(words);
    } catch (caught) {
      setFileError(caught instanceof Error ? caught.message : "The file could not be saved.");
    } finally {
      setFileBusy(false);
    }
  }

  const back = <Link className="prod-back" to="/production/library">← Library</Link>;
  if (error && !item) {
    return (
      <>
        {back}
        <Problem>{error}</Problem>
        <button type="button" className="button" onClick={() => void load()}>
          Try again
        </button>
      </>
    );
  }
  if (!item) {
    return (
      <>
        {back}
        <p className="loading" role="status">Loading the product…</p>
      </>
    );
  }

  const swatch = hexOf(item.details.colour_code);
  const decoration = decorationWords(item.details);
  const sizes = item.variants.map((variant) => variant.title);

  return (
    <>
      {back}
      <div className="page__head">
        <div className="prod-lib-head">
          {item.image_url ? (
            <img className="prod-photo prod-photo--big" src={bigPhoto(item.image_url)} alt={item.title} />
          ) : (
            <StylePhoto url={null} />
          )}
          <div className="page__title">
            <h1>{item.title}</h1>
            <span className="page__subtitle">
              <span className={`prod-pill${item.status === "active" ? " prod-pill--ok" : ""}`}>{STATUS_WORDS[item.status]}</span> · {sizesWords(sizes)}
            </span>
          </div>
        </div>
        {isOwner && (
          <div className="prod-head-actions">
            <Link className="button button--primary" to={`/production/orders/new?product=${encodeURIComponent(item.id)}`}>
              New order
            </Link>
          </div>
        )}
      </div>

      {notice && <p className="notice notice--settled" role="status">{notice}</p>}

      {panel === "details" && <DetailsPanel item={item} onSaved={(next) => saved(next, "Details saved.")} onClose={() => setPanel(null)} />}
      {panel === "cogs" && <CogsPanel item={item} onSaved={(next) => saved(next, "COGS saved.")} onClose={() => setPanel(null)} />}

      <div className="prod-halves">
        <section className="prod-block" aria-labelledby="lib-details">
          <div className="prod-block__head">
            <h2 id="lib-details">Details</h2>
            {isOwner && panel !== "details" && (
              <button type="button" className="button button--row" onClick={() => setPanel("details")}>
                Edit details
              </button>
            )}
          </div>
          <dl className="prod-details">
            <div>
              <dt>Colour code</dt>
              <dd>
                {item.details.colour_code ? (
                  <>
                    {swatch && <span className="prod-swatch" style={{ background: swatch }} aria-hidden="true" />}
                    {item.details.colour_code}
                  </>
                ) : (
                  <span className="prod-small">{NOT_SET}</span>
                )}
              </dd>
            </div>
            <div>
              <dt>Fabric</dt>
              <dd>{item.details.fabric_type ?? <span className="prod-small">{NOT_SET}</span>}</dd>
            </div>
            <div>
              <dt>Print or embroidery</dt>
              <dd>{decoration ?? <span className="prod-small">{NOT_SET}</span>}</dd>
            </div>
            <div>
              <dt>Notes</dt>
              <dd>{item.details.notes ?? <span className="prod-small">{NOT_SET}</span>}</dd>
            </div>
          </dl>
          {item.updated_at && (
            <p className="prod-small">
              Last changed {shortDay(cairoDay(item.updated_at))}
              {item.updated_by ? ` by ${item.updated_by}` : ""}
            </p>
          )}
        </section>

        {item.cogs !== undefined && (
          <section className="prod-block" aria-labelledby="lib-cogs">
            <div className="prod-block__head">
              <h2 id="lib-cogs">COGS a piece</h2>
              {isOwner && panel !== "cogs" && (
                <button type="button" className="button button--row" onClick={() => setPanel("cogs")}>
                  Edit COGS
                </button>
              )}
            </div>
            {hasCogs(item.cogs) ? (
              <dl className="prod-details">
                {COST_PARTS.map((part) => (
                  <div key={part}>
                    <dt>{PART_LABELS[part]}</dt>
                    <dd className={item.cogs?.[`${part}_piastres`] === null ? "prod-small" : undefined}>{partWords(item.cogs?.[`${part}_piastres`] ?? null)}</dd>
                  </div>
                ))}
                <div>
                  <dt>Total</dt>
                  <dd>
                    <b>{formatEgp(item.cogs.total_piastres ?? 0)}</b>
                  </dd>
                </div>
              </dl>
            ) : (
              <p className="empty">No COGS yet. A new order fills its target cost from it.</p>
            )}
          </section>
        )}
      </div>

      <section className="prod-block" aria-labelledby="lib-files">
        <h2 id="lib-files">Files</h2>
        {fileError && <Problem>{fileError}</Problem>}
        <dl className="prod-details prod-product">
          {FILE_KINDS.map((kind) => (
            <FileGroup
              key={kind}
              kind={kind}
              files={item.files[kind]}
              editable={canEdit}
              busy={fileBusy}
              confirming={confirming}
              onAdd={(which, file) =>
                void fileWrite(
                  () => api.upload(`${address}/files`, file, { fields: { kind: which } }),
                  `${FILE_WORDS[which].title.replace(/s$/, "")} added: ${file.name}.`,
                )
              }
              onAskRemove={(file) => setConfirming(file.id)}
              onKeep={() => setConfirming(null)}
              onRemove={(file) => void fileWrite(() => api.del(file.url), `Removed: ${file.name}.`)}
            />
          ))}
        </dl>
      </section>

      <div className="prod-halves prod-halves--after">
        <section className="prod-block" aria-labelledby="lib-shopify">
          <h2 id="lib-shopify">From Shopify</h2>
          {item.variants.length === 0 ? (
            <p className="empty">Shopify lists no sizes for it.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Size</th>
                  <th scope="col">SKU</th>
                </tr>
              </thead>
              <tbody>
                {item.variants.map((variant) => (
                  <tr key={variant.id}>
                    <td>{variant.title}</td>
                    <td>{variant.sku ?? <span className="prod-small">None</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="prod-small">
            The name, photo, status and sizes are Shopify's and change there.
            {item.synced_at ? ` As of ${shortDay(cairoDay(item.synced_at))}.` : ""}
          </p>
        </section>

        <section className="prod-block" aria-labelledby="lib-orders">
          <h2 id="lib-orders">Production orders</h2>
          {item.orders.length === 0 ? (
            <p className="empty">No production order made of it yet.</p>
          ) : (
            <ul className="prod-tasks">
              {item.orders.map((order) => (
                <li key={order.id} className="prod-task prod-task--plain">
                  <div className="prod-task__what">
                    <Link className="prod-rowlink" to={`/production/orders/${order.id}`}>
                      {order.code} · {order.colour}
                    </Link>
                    <div className="prod-small">
                      {pieces(order.planned_total)} planned · target {shortDay(order.target_date)}
                    </div>
                  </div>
                  <div className="prod-task__side">{ORDER_STATUS[order.status]}</div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
