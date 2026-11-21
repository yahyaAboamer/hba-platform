import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api, can } from "../../../lib/api";
import type { Session } from "../../../lib/api";
import { cogsText, hasCogs } from "./libraryLogic";
import { COST_PARTS, DATED_STAGES, DATE_LABELS, fillDates, isBlank } from "./logic";
import { cairoToday } from "./format";
import type { DatedStage } from "./logic";
import { NEW_STYLE, OrderFields, draftBody, draftProblem, emptyDraft } from "./OrderFields";
import type { Choices, LibraryItem, OrderAnswer, StageKey } from "./types";
import { Problem } from "./ui";

type Dates = Record<DatedStage, string>;
const noDates = (): Dates => Object.fromEntries(DATED_STAGES.map((stage) => [stage, ""])) as Dates;

/** `/production/orders/new`: one style in one colour at one factory. The owner's. */
export function NewOrder({ session }: { session: Session }) {
  const navigate = useNavigate();
  const isOwner = can(session, "production.owner");
  const [choices, setChoices] = useState<Choices | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [draft, setDraft] = useState(emptyDraft);
  const [repeat, setRepeat] = useState(false);
  const [dates, setDates] = useState<Dates>(noDates);
  // Dates the person has set by hand: a new target date does not overwrite them.
  const [touched, setTouched] = useState<ReadonlySet<DatedStage>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [params] = useSearchParams();
  // Whether the target cost was filled from the Library's COGS (ADR 0087), for the line that says so.
  const [costFromLibrary, setCostFromLibrary] = useState(false);

  useEffect(() => {
    if (!isOwner) return;
    api.get<Choices>("/api/prod/choices")
      .then(setChoices)
      .catch((caught) => setLoadError(caught instanceof Error ? caught.message : "The form could not be loaded."));
  }, [isOwner]);

  // Opened from a Library page (`?product=`): that product is the style.
  const wanted = params.get("product");
  useEffect(() => {
    if (!choices || !wanted) return;
    const product = choices.products.find((candidate) => candidate.id === wanted);
    if (product) setDraft((before) => (before.productId ? before : { ...before, productId: product.id, styleName: product.title }));
  }, [choices, wanted]);

  // A Library product with a COGS fills the target cost per piece, while every box of it is still blank.
  // The colour code, fabric and print come from the Library on the server's side.
  const productId = draft.productId;
  useEffect(() => {
    setCostFromLibrary(false);
    if (!productId || productId === NEW_STYLE) return;
    let current = true;
    api.get<{ product: LibraryItem }>(`/api/prod/library/${encodeURIComponent(productId)}`)
      .then(({ product }) => {
        if (!current || !hasCogs(product.cogs)) return;
        const cogs = product.cogs;
        setDraft((before) => {
          if (before.productId !== productId || COST_PARTS.some((part) => !isBlank(before.target[part]))) return before;
          setCostFromLibrary(true);
          return { ...before, target: cogsText(cogs) };
        });
      })
      .catch(() => undefined); // the form works the same without it
    return () => {
      current = false;
    };
  }, [productId]);

  // The expected date of each stage, backwards from the target date: again when the date or the tick changes.
  useEffect(() => {
    if (!choices || !draft.targetDate) return;
    const filled = fillDates(draft.targetDate, choices.stage_days, repeat ? new Set<StageKey>(["sample"]) : new Set<StageKey>(), cairoToday());
    setDates((before) => {
      const next = { ...before };
      for (const stage of DATED_STAGES) if (!touched.has(stage)) next[stage] = filled[stage] ?? "";
      return next;
    });
  }, [choices, draft.targetDate, repeat, touched]);

  if (!isOwner) {
    return (
      <>
        <div className="page__head"><div className="page__title"><h1>New production order</h1></div></div>
        <p className="notice">Only owners make production orders.</p>
        <p><Link to="/production/orders">Back to all orders</Link></p>
      </>
    );
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    const problem = draftProblem(draft, true);
    if (problem) {
      setError(problem);
      return;
    }
    const skipped = (stage: DatedStage) => repeat && stage === "sample";
    const expected = Object.fromEntries(DATED_STAGES.filter((stage) => !skipped(stage) && dates[stage]).map((stage) => [stage, dates[stage]]));
    setError(null);
    setBusy(true);
    try {
      const made = await api.post<OrderAnswer>("/api/prod/orders", { ...draftBody(draft), repeat_run: repeat, expected_dates: expected });
      navigate(`/production/orders/${made.order.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The order could not be saved.");
      setBusy(false);
    }
  }

  return (
    <>
      <Link className="prod-back" to="/production/orders">← All orders</Link>
      <div className="page__head">
        <div className="page__title">
          <h1>New production order</h1>
          <span className="page__subtitle">One style in one colour</span>
        </div>
      </div>
      {loadError && <Problem>{loadError}</Problem>}
      {!choices && !loadError && <p className="loading" role="status">Loading the form…</p>}
      {choices && (
        <div className="prod-block">
          <form className="prod-form" onSubmit={create} noValidate>
            <OrderFields draft={draft} onChange={setDraft} choices={choices} />
            {costFromLibrary && (
              <p className="prod-small prod-wide" role="status">
                The target cost per piece is filled from this product&apos;s COGS in the Library. Change it if this run costs differently.
              </p>
            )}

            <fieldset className="prod-fieldset prod-wide">
              <legend className="field__label">Expected date for each stage, filled in from the target date. Change any of them.</legend>
              <div className="prod-sizes prod-sizes--dates">
                {DATED_STAGES.map((stage) => {
                  const skipped = repeat && stage === "sample";
                  const id = `date-${stage}`;
                  return (
                    <div key={stage} className="prod-size">
                      <label htmlFor={id}>{DATE_LABELS[stage]}</label>
                      {skipped ? (
                        <input id={id} className="input" value="Skipped" disabled readOnly />
                      ) : (
                        <input
                          id={id}
                          className="input"
                          type="date"
                          value={dates[stage]}
                          onChange={(event) => {
                            setDates({ ...dates, [stage]: event.target.value });
                            setTouched(new Set([...touched, stage]));
                          }}
                        />
                      )}
                    </div>
                  );
                })}
              </div>
              <p className="prod-total">Dates you change by hand stay as you set them when the target date moves.</p>
            </fieldset>

            <label className="prod-check prod-wide">
              <input type="checkbox" checked={repeat} onChange={(event) => setRepeat(event.target.checked)} />
              Repeat run with nothing changed: skip the sample
            </label>

            <div className="prod-wide">
              {error && <Problem>{error}</Problem>}
              <div className="prod-actions">
                <button type="submit" className="button button--primary" disabled={busy}>
                  {busy ? "Creating…" : "Create order"}
                </button>
                <Link className="button" to="/production/orders">Cancel</Link>
              </div>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
