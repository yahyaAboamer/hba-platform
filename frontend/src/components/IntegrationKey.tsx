import { useEffect, useState } from "react";

import { api } from "../lib/api";

/** "3 Oct, 14:02", in Cairo. */
function checkedWhen(iso: string): string {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: "Africa/Cairo",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(new Date(iso))
      .map((part) => [part.type, part.value]),
  );
  return `${parts.day} ${parts.month}, ${parts.hour}:${parts.minute}`;
}

/** What the server says about a key. **Never the key**, only its last four. */
type KeyState = {
  provider: "bosta" | "estebdal";
  label: string;
  source: "saved" | "environment" | null;
  hint: string | null;
  verified_at: string | null;
  problem: string | null;
  can_save: boolean;
  key_problem: string | null;
};

const STATE_WORDS: Record<string, string> = {
  saved: "Connected",
  environment: "From Railway",
  none: "Not connected",
};

const BUTTON_WORDS: Record<string, string> = {
  saved: "Replace key",
  environment: "Save a key here instead",
  none: "Add key",
};

/**
 * One of Operations' keys in Settings → Shopify (ADR 0057 §10; the approved
 * mockup's frame 6, beside the Shopify connection).
 *
 * The key is never sent to this page: the card shows where the key in use
 * comes from and its last four characters. A new key is tried against its
 * provider before it is saved, so a refusal here means the key in use has
 * not changed - and the field keeps what was typed.
 */
function KeyCard({ provider }: { provider: "bosta" | "estebdal" }) {
  const [state, setState] = useState<KeyState | null>(null);
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<KeyState>(`/api/order-ops/connections/${provider}`)
      .then(setState)
      .catch((caught) => setError(caught.message));
  }, [provider]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    setSaved(null);
    try {
      const body = await api.put<KeyState>(`/api/order-ops/connections/${provider}`, { key });
      setState(body);
      // The key leaves the page as soon as it has done its job.
      setKey("");
      setOpen(false);
      setSaved(`Key saved. ${body.label} answered with it.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The key was not changed.");
    } finally {
      setWorking(false);
    }
  }

  const label = state?.label ?? (provider === "bosta" ? "Bosta" : "E-stebdal");
  const source = state?.source ?? "none";
  const fieldId = `ops-key-${provider}`;

  return (
    <section className="pay-detail__card sync__card" aria-labelledby={`${fieldId}-title`}>
      <h2 className="pay-detail__card-title" id={`${fieldId}-title`}>
        {label}
      </h2>
      {state && (
        <p className="shop-conn__meta">
          {STATE_WORDS[source]}
          {state.hint &&
            ` · ${source === "environment" ? "set on the server, " : ""}${state.hint}`}
          {state.verified_at && ` · checked ${checkedWhen(state.verified_at)}`}
        </p>
      )}
      {state?.problem && <p className="sync__error">{state.problem}</p>}
      {state && !state.can_save && (
        <p className="sync__error">
          This server cannot protect a saved key yet (
          {state.key_problem ?? "SETTINGS_ENCRYPTION_KEY is not set"}).
        </p>
      )}
      {saved && (
        <p className="sync__notice" role="status">
          {saved}
        </p>
      )}
      {open ? (
        <form className="shop-conn" onSubmit={save}>
          <label className="shop-conn__field" htmlFor={fieldId}>
            <span className="shop-conn__label">New {label} key</span>
            <input
              id={fieldId}
              className="shop-conn__input"
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={key}
              onChange={(event) => setKey(event.target.value)}
            />
          </label>
          {provider === "bosta" && (
            <p className="sync__hint">
              Use a read-only key: Bosta → Settings → API Integration. Operations never writes to
              Bosta.
            </p>
          )}
          {error && (
            <p className="sync__error" role="alert">
              {error}
            </p>
          )}
          <button
            type="submit"
            className="button shop-conn__submit"
            disabled={working || !key.trim() || !state?.can_save}
          >
            {working ? `Checking with ${label}…` : "Check and save"}
          </button>{" "}
          <button
            type="button"
            className="button button--quiet shop-conn__submit"
            onClick={() => {
              setOpen(false);
              setKey("");
              setError(null);
            }}
          >
            Cancel
          </button>
        </form>
      ) : (
        <>
          {/* Loading the card failed: a note, not an alert - nothing was asked. */}
          {error && <p className="sync__error">{error}</p>}
          {state && (
            <button
              type="button"
              className="button button--quiet shop-conn__submit"
              disabled={!state.can_save}
              onClick={() => {
                setSaved(null);
                setOpen(true);
              }}
            >
              {BUTTON_WORDS[source]}
            </button>
          )}
        </>
      )}
    </section>
  );
}

/** Operations' two keys, beside the Shopify connection. */
export function IntegrationKeys() {
  return (
    <>
      <KeyCard provider="bosta" />
      <KeyCard provider="estebdal" />
    </>
  );
}
