import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, can } from "../../../lib/api";
import type { Session } from "../../../lib/api";
import { DATED_STAGES, DATE_LABELS, fillDates } from "./logic";
import { cairoToday } from "./format";
import type { DatedStage } from "./logic";
import { OrderFields, draftBody, draftProblem, emptyDraft } from "./OrderFields";
import type { Choices, OrderAnswer, StageKey } from "./types";
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

  useEffect(() => {
    if (!isOwner) return;
    api.get<Choices>("/api/prod/choices")
      .then(setChoices)
      .catch((caught) => setLoadError(caught instanceof Error ? caught.message : "The form could not be loaded."));
  }, [isOwner]);

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
