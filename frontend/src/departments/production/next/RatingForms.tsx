/**
 * The rating of the suppliers of a closed order (ADR 0084, decision 10): the owner's panel, and the card
 * that shows what was given.
 *
 * Stars are real radio buttons, each named "N of 5" for a screen reader and drawn with its number as well as
 * a filled or empty star, so the choice never rests on colour. Timing starts at the star the server suggests
 * from the real lateness, and the owner may change it. Nothing here is money, so the card is drawn for
 * anybody who can see the order.
 */
import { useId, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../../../lib/api";
import { PanelShell, Problem, TextBox } from "./ui";
import { RATING_ROLE_WORDS, latenessWords, starsWords } from "./supplierLogic";
import type { OrderRatings, OrderView, RatingTarget } from "./types";

type Stars = number | null;

/** One group of five stars, as radio buttons. */
function StarChoice({ label, name, value, onChange, hint }: { label: string; name: string; value: Stars; onChange: (value: number) => void; hint?: string }) {
  const id = useId();
  return (
    <div className="prod-field">
      <span id={id} className="field__label">
        {label}
      </span>
      <div className="prod-stars" role="radiogroup" aria-labelledby={id}>
        {[1, 2, 3, 4, 5].map((n) => {
          const on = value !== null && n <= value;
          return (
            <label key={n} className={`prod-star${on ? " is-on" : ""}${value === n ? " is-picked" : ""}`}>
              <input type="radio" name={name} value={n} checked={value === n} onChange={() => onChange(n)} />
              <span className="prod-star__glyph" aria-hidden="true">
                {on ? "★" : "☆"}
              </span>
              <span className="prod-star__n" aria-hidden="true">
                {n}
              </span>
              <span className="prod-sr">{n} of 5</span>
            </label>
          );
        })}
      </div>
      {hint && <span className="field__hint">{hint}</span>}
    </div>
  );
}

/** One supplier's block: what it did on the order, three star choices, a note, and its own Save. */
function RateBlock({ order, target, onSaved }: { order: OrderView; target: RatingTarget; onSaved: (name: string) => void }) {
  const name = target.supplier.name ?? "Supplier";
  const [quality, setQuality] = useState<Stars>(target.rating?.quality ?? null);
  const [timing, setTiming] = useState<Stars>(target.rating?.timing ?? target.suggested_timing);
  const [dealing, setDealing] = useState<Stars>(target.rating?.dealing ?? null);
  const [note, setNote] = useState(target.rating?.note ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const late = latenessWords(target.lateness_days);
  const base = `rate-${target.supplier.id}`;

  const edit = (set: (value: Stars) => void) => (value: number) => {
    set(value);
    setSaved(false);
  };

  async function save() {
    if (busy) return;
    if (quality === null || timing === null || dealing === null) {
      setError("Choose a star for quality, timing and dealing.");
      return;
    }
    setError(null);
    setSaved(false);
    setBusy(true);
    try {
      await api.put<unknown>(`/api/prod/orders/${order.id}/ratings/${target.supplier.id}`, {
        quality,
        timing,
        dealing,
        note: note.trim() ? note.trim() : null,
      });
      setSaved(true);
      onSaved(name);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The rating could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className="prod-rate"
      aria-label={`Rating for ${name}`}
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <div className="prod-rate__who">
        <b>{name}</b>
        <span className="prod-small">
          {RATING_ROLE_WORDS[target.role]}
          {late && (
            <>
              {" · "}
              <span className={late.late ? "prod-late" : undefined}>{late.text}</span>
            </>
          )}
        </span>
      </div>
      <div className="prod-rate__stars">
        <StarChoice label="Quality" name={`${base}-quality`} value={quality} onChange={edit(setQuality)} />
        <StarChoice
          label="Timing"
          name={`${base}-timing`}
          value={timing}
          onChange={edit(setTiming)}
          hint={target.suggested_timing !== null && !target.rating ? "Filled in from how late it was. Change it if you like." : undefined}
        />
        <StarChoice label="Dealing" name={`${base}-dealing`} value={dealing} onChange={edit(setDealing)} />
      </div>
      <TextBox
        label="Note (optional)"
        value={note}
        onChange={(value) => {
          setNote(value);
          setSaved(false);
        }}
        area
        wide
        max={1000}
      />
      {error && <Problem>{error}</Problem>}
      <div className="prod-actions">
        <button type="submit" className="button button--primary" disabled={busy}>
          {busy ? "Saving…" : "Save"}
          <span className="prod-sr">: {name}</span>
        </button>
        {saved && (
          <span className="prod-ok" role="status">
            Saved.
          </span>
        )}
      </div>
    </form>
  );
}

/**
 * The "Rate the suppliers" panel. `fresh` is when it has just opened after settling: the ratings can be
 * skipped, and the panel says so. Each supplier is saved on its own; the panel stays open for the rest.
 */
export function RatePanel({
  order,
  ratings,
  error,
  fresh,
  onSaved,
  onClose,
}: {
  order: OrderView;
  ratings: OrderRatings | null;
  error: string | null;
  fresh: boolean;
  onSaved: (name: string) => void;
  onClose: () => void;
}) {
  return (
    <PanelShell
      title="Rate the suppliers"
      intro={
        fresh
          ? "The order is settled. Rate each supplier who worked on it now, or skip and do it later from the order or the supplier's page."
          : "Each supplier is saved on its own. Change a rating whenever you like."
      }
      onClose={onClose}
    >
      {error && <Problem>{error}</Problem>}
      {!ratings && !error && (
        <p className="prod-small" role="status">
          Loading the suppliers…
        </p>
      )}
      {ratings && ratings.suppliers.length === 0 && <p className="prod-small">There is nobody to rate on this order.</p>}
      {ratings && ratings.suppliers.length > 0 && (
        <div className="prod-rates">
          {ratings.suppliers.map((target) => (
            <RateBlock key={target.supplier.id} order={order} target={target} onSaved={onSaved} />
          ))}
        </div>
      )}
      <div className="prod-actions prod-rates__end">
        <button type="button" className="button" onClick={onClose}>
          {fresh ? "Skip for now" : "Done"}
        </button>
      </div>
    </PanelShell>
  );
}

/** The "Ratings" card of a closed order: each supplier's stars and note, or "Not rated yet". */
export function RatingsCard({
  order,
  ratings,
  error,
  isOwner,
  onRate,
}: {
  order: OrderView;
  ratings: OrderRatings | null;
  error: string | null;
  isOwner: boolean;
  onRate: () => void;
}) {
  if (order.status !== "closed") return null;
  if (ratings && !ratings.ratable) return null;
  const rated = ratings?.suppliers.some((target) => target.rating) ?? false;
  return (
    <section className="prod-block" aria-labelledby="prod-ratings">
      <div className="prod-block__head">
        <h2 id="prod-ratings">Ratings</h2>
        {isOwner && ratings && ratings.suppliers.length > 0 && (
          <button type="button" className="button button--row" onClick={onRate}>
            {rated ? "Change ratings" : "Rate the suppliers"}
          </button>
        )}
      </div>
      {error && <Problem>{error}</Problem>}
      {!ratings && !error && (
        <p className="prod-small" role="status">
          Loading the ratings…
        </p>
      )}
      {ratings && ratings.suppliers.length === 0 && <p className="prod-small">Nobody is on this order to rate.</p>}
      {ratings && ratings.suppliers.length > 0 && (
        <ul className="prod-plain">
          {ratings.suppliers.map((target) => (
            <li key={target.supplier.id} className="prod-plain__row">
              <div>
                <Link to={`/production/next/suppliers/${target.supplier.id}`}>{target.supplier.name ?? "Supplier"}</Link>{" "}
                <span className="prod-small">· {RATING_ROLE_WORDS[target.role]}</span>
              </div>
              {target.rating ? (
                <>
                  <div className="prod-small">{starsWords(target.rating)}</div>
                  {target.rating.note && <div className="prod-small">“{target.rating.note}”</div>}
                </>
              ) : (
                <div className="prod-small">Not rated yet</div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
