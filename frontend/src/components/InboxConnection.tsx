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

/** Whether WhatsApp is being heard from, and how Meta rates the number. */
type WhatsAppHealth = {
  connected: boolean;
  last_heard_at: string | null;
  rating: string | null;
};

/** Meta's three colours, in the words its own screens use. */
const RATING: Record<string, string> = { GREEN: "high", YELLOW: "medium", RED: "low" };

/** What the server says. **Never a key**, only two keys' last four characters. */
type WhatsAppState = {
  connected: boolean;
  phone_number_id: string | null;
  business_account_id: string | null;
  display_number: string | null;
  verified_name: string | null;
  access_token_hint: string | null;
  app_secret_hint: string | null;
  verified_at: string | null;
  sending_enabled: boolean;
  problem: string | null;
  can_save: boolean;
  key_problem: string | null;
  test_numbers_only: boolean;
};

type TagsState = {
  connected: boolean;
  shop_domain: string | null;
  client_id_hint: string | null;
  client_secret_hint: string | null;
  verified_at: string | null;
  problem: string | null;
  can_save: boolean;
  key_problem: string | null;
};

type Both = { whatsapp: WhatsAppState; tags: TagsState };

const said = (caught: unknown, fallback: string) =>
  caught instanceof Error ? caught.message : fallback;

function CannotProtect({ reason }: { reason: string | null }) {
  return (
    <p className="sync__error">
      This server cannot protect a saved key yet ({reason ?? "SETTINGS_ENCRYPTION_KEY is not set"}).
    </p>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  secret = false,
  hint,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  secret?: boolean;
  hint?: string;
}) {
  return (
    <label className="shop-conn__field" htmlFor={id}>
      <span className="shop-conn__label">{label}</span>
      <input
        id={id}
        className="shop-conn__input"
        type={secret ? "password" : "text"}
        inputMode={secret ? undefined : "numeric"}
        autoComplete="off"
        spellCheck={false}
        value={value}
        placeholder={hint}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

/**
 * The WhatsApp connection in Settings → Shopify (ADR 0059; the approved
 * mockup's frame 6).
 *
 * No key is ever sent to this page: the card shows the number, its name and
 * the last four characters of two keys. New keys are tried against Meta
 * before they are saved, so a refusal means the connection in use has not
 * changed - and the fields keep what was typed. A secret left blank keeps the
 * saved one.
 */
function WhatsAppCard({ state, onChanged }: { state: WhatsAppState; onChanged: (both: Both) => void }) {
  const [open, setOpen] = useState(false);
  const [numberId, setNumberId] = useState(state.phone_number_id ?? "");
  const [accountId, setAccountId] = useState(state.business_account_id ?? "");
  const [accessToken, setAccessToken] = useState("");
  const [appSecret, setAppSecret] = useState("");
  const [verifyToken, setVerifyToken] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [health, setHealth] = useState<WhatsAppHealth | null>(null);

  // When WhatsApp was last heard from, and Meta's own rating of the number
  // (the mockup's frame 6). Read apart from the card, and again after a save,
  // so a slow answer from Meta holds up this one line and nothing else.
  useEffect(() => {
    if (!state.connected) return;
    let wanted = true;
    api
      .get<WhatsAppHealth>("/api/inbox/connection/health")
      .then((found) => {
        if (wanted && typeof found?.connected === "boolean") setHealth(found);
      })
      .catch(() => undefined);
    return () => {
      wanted = false;
    };
  }, [state.connected, state.verified_at]);

  function close() {
    // The keys leave the page as soon as they have done their job.
    setAccessToken("");
    setAppSecret("");
    setVerifyToken("");
    setError(null);
    setOpen(false);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    setSaved(null);
    try {
      const body = await api.put<Both>("/api/inbox/connection/whatsapp", {
        phone_number_id: numberId.trim(),
        business_account_id: accountId.trim(),
        access_token: accessToken,
        app_secret: appSecret,
        verify_token: verifyToken,
      });
      onChanged(body);
      close();
      setSaved("Saved. WhatsApp answered with these details. Sending is a separate switch.");
    } catch (caught) {
      setError(said(caught, "The connection was not changed."));
    } finally {
      setWorking(false);
    }
  }

  async function switchSending(enabled: boolean) {
    setWorking(true);
    setError(null);
    setSaved(null);
    try {
      onChanged(await api.put<Both>("/api/inbox/connection/sending", { enabled }));
      setSaved(enabled ? "Sending is on." : "Sending is off. Nothing will be sent.");
    } catch (caught) {
      setError(said(caught, "Sending was not changed."));
    } finally {
      setWorking(false);
    }
  }

  const keep = state.connected ? "Leave blank to keep the saved one" : undefined;
  const title = [state.verified_name, state.display_number].filter(Boolean).join(" · ");

  return (
    <section className="pay-detail__card sync__card" aria-labelledby="inbox-whatsapp-title">
      <h2 className="pay-detail__card-title" id="inbox-whatsapp-title">
        WhatsApp
      </h2>
      <p className="shop-conn__meta">
        {state.connected ? "Connected" : "Not connected"}
        {state.connected && title && ` · ${title}`}
        {state.connected && state.verified_at && ` · checked ${checkedWhen(state.verified_at)}`}
      </p>
      {state.connected && (
        <p className="shop-conn__meta">
          Access key ends in {state.access_token_hint ?? "…"} · app secret ends in{" "}
          {state.app_secret_hint ?? "…"}
        </p>
      )}
      {state.connected && (
        <p className="shop-conn__meta">
          Sending is {state.sending_enabled ? "on" : "off"}
          {state.test_numbers_only && " · this server only messages its test numbers"}
        </p>
      )}
      {state.connected && health && (
        <p className="shop-conn__meta">
          {health.last_heard_at
            ? `Last heard from ${checkedWhen(health.last_heard_at)}`
            : "Not heard from yet"}
          {" · number rating "}
          {RATING[health.rating ?? ""] ?? "not known"}
        </p>
      )}
      {state.problem && <p className="sync__error">{state.problem}</p>}
      {!state.can_save && <CannotProtect reason={state.key_problem} />}
      {saved && (
        <p className="sync__notice" role="status">
          {saved}
        </p>
      )}
      {open ? (
        <form className="shop-conn" onSubmit={save}>
          <Field id="inbox-number-id" label="WhatsApp number ID" value={numberId} onChange={setNumberId} />
          <Field id="inbox-account-id" label="WhatsApp business account ID" value={accountId} onChange={setAccountId} />
          <Field id="inbox-access-token" label="Access key" value={accessToken} onChange={setAccessToken} secret hint={keep} />
          <Field id="inbox-app-secret" label="App secret" value={appSecret} onChange={setAppSecret} secret hint={keep} />
          <Field id="inbox-verify-token" label="Check word" value={verifyToken} onChange={setVerifyToken} secret hint={keep} />
          <p className="sync__hint">
            The two IDs and the access key are in Meta → WhatsApp → API setup. The app secret is in
            the Meta app's basic settings. The check word is any phrase you choose; Meta asks for
            the same one when the callback address is set.
          </p>
          {error && (
            <p className="sync__error" role="alert">
              {error}
            </p>
          )}
          <button
            type="submit"
            className="button shop-conn__submit"
            disabled={working || !numberId.trim() || !accountId.trim() || !state.can_save}
          >
            {working ? "Checking with WhatsApp…" : "Check and save"}
          </button>{" "}
          <button type="button" className="button button--quiet shop-conn__submit" onClick={close}>
            Cancel
          </button>
        </form>
      ) : (
        <>
          {error && (
            <p className="sync__error" role="alert">
              {error}
            </p>
          )}
          <button
            type="button"
            className="button button--quiet shop-conn__submit"
            disabled={!state.can_save}
            onClick={() => {
              setSaved(null);
              setOpen(true);
            }}
          >
            {state.connected ? "Change keys" : "Connect WhatsApp"}
          </button>{" "}
          {state.connected && (
            <button
              type="button"
              className="button button--quiet shop-conn__submit"
              disabled={working}
              onClick={() => switchSending(!state.sending_enabled)}
            >
              {state.sending_enabled ? "Turn sending off" : "Turn sending on"}
            </button>
          )}
        </>
      )}
    </section>
  );
}

/**
 * The second Shopify app, used only to tag an order's confirmation
 * (ADR 0059, point 11). The app the platform reads money with stays
 * read-only, so the server refuses it here.
 */
function TagsCard({ state, onChanged }: { state: TagsState; onChanged: (both: Both) => void }) {
  const [open, setOpen] = useState(false);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  function close() {
    setClientId("");
    setClientSecret("");
    setError(null);
    setOpen(false);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    setSaved(null);
    try {
      const body = await api.put<Both>("/api/inbox/connection/tags", {
        client_id: clientId.trim(),
        client_secret: clientSecret,
      });
      onChanged(body);
      close();
      setSaved("Saved. Shopify answered, and this app may change orders.");
    } catch (caught) {
      setError(said(caught, "The connection was not changed."));
    } finally {
      setWorking(false);
    }
  }

  return (
    <section className="pay-detail__card sync__card" aria-labelledby="inbox-tags-title">
      <h2 className="pay-detail__card-title" id="inbox-tags-title">
        Shopify, for order tags
      </h2>
      <p className="shop-conn__meta">
        {state.connected ? "Connected" : "Not connected"}
        {state.shop_domain && ` · ${state.shop_domain}`}
        {state.connected && state.client_secret_hint && ` · secret ends in ${state.client_secret_hint}`}
        {state.connected && state.verified_at && ` · checked ${checkedWhen(state.verified_at)}`}
      </p>
      <p className="sync__hint">
        A second Shopify app, used only to add and remove an order's confirmation tags. It must not
        be the app the platform reads Shopify with, which stays read-only.
      </p>
      {state.problem && <p className="sync__error">{state.problem}</p>}
      {!state.can_save && <CannotProtect reason={state.key_problem} />}
      {saved && (
        <p className="sync__notice" role="status">
          {saved}
        </p>
      )}
      {open ? (
        <form className="shop-conn" onSubmit={save}>
          <label className="shop-conn__field" htmlFor="inbox-tags-client-id">
            <span className="shop-conn__label">Client ID</span>
            <input
              id="inbox-tags-client-id"
              className="shop-conn__input"
              type="text"
              autoComplete="off"
              spellCheck={false}
              value={clientId}
              onChange={(event) => setClientId(event.target.value)}
            />
          </label>
          <Field id="inbox-tags-client-secret" label="Client secret" value={clientSecret} onChange={setClientSecret} secret />
          {error && (
            <p className="sync__error" role="alert">
              {error}
            </p>
          )}
          <button
            type="submit"
            className="button shop-conn__submit"
            disabled={working || !clientId.trim() || !clientSecret.trim() || !state.can_save}
          >
            {working ? "Checking with Shopify…" : "Check and save"}
          </button>{" "}
          <button type="button" className="button button--quiet shop-conn__submit" onClick={close}>
            Cancel
          </button>
        </form>
      ) : (
        <button
          type="button"
          className="button button--quiet shop-conn__submit"
          disabled={!state.can_save}
          onClick={() => {
            setSaved(null);
            setOpen(true);
          }}
        >
          {state.connected ? "Replace app" : "Connect the second app"}
        </button>
      )}
    </section>
  );
}

/** The inbox's two connections, beside the Shopify connection. */
export function InboxConnections() {
  const [both, setBoth] = useState<Both | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Both>("/api/inbox/connection")
      .then(setBoth)
      .catch((caught) => setError(said(caught, "The inbox's connections could not be read.")));
  }, []);

  if (error) {
    return (
      <section className="pay-detail__card sync__card" aria-labelledby="inbox-whatsapp-title">
        <h2 className="pay-detail__card-title" id="inbox-whatsapp-title">
          WhatsApp
        </h2>
        {/* Loading failed: a note, not an alert - nothing was asked. */}
        <p className="sync__error">{error}</p>
      </section>
    );
  }
  if (!both) return null;
  return (
    <>
      <WhatsAppCard state={both.whatsapp} onChanged={setBoth} />
      <TagsCard state={both.tags} onChanged={setBoth} />
    </>
  );
}
