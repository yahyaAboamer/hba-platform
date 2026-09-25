import { useEffect, useState } from "react";

import { api } from "../lib/api";

/** What the server says about the connection. **Never a secret.** */
export type ShopifyConnectionState = {
  source: "saved" | "environment" | null;
  shop_domain: string | null;
  client_id_hint: string | null;
  secret_saved: boolean;
  verified_at: string | null;
  shop_name: string | null;
  problem: string | null;
  can_save: boolean;
};

/**
 * The export's *Connection* card (`syncCreds` and *Update connection*),
 * with HBA's credentials in it - *Store domain*, *Client ID*, *Client
 * secret* - because HBA's app is a Dev Dashboard app with no permanent Admin
 * API key (ADR 0015; the owner chose these fields on 25 September).
 *
 * The client ID and secret are never sent to this page. Their fields start
 * empty; left empty, the saved ones stay. The server tries a new connection
 * against Shopify before saving anything, so a refusal here means the
 * connection in use has not changed - and the form keeps what was typed.
 */
export function ShopifyConnection({ onChanged }: { onChanged?: (state: ShopifyConnectionState) => void }) {
  const [state, setState] = useState<ShopifyConnectionState | null>(null);
  const [domain, setDomain] = useState("");
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ShopifyConnectionState>("/api/operations/shopify-connection")
      .then((body) => {
        setState(body);
        setDomain(body.shop_domain ?? "");
        onChanged?.(body);
      })
      .catch((caught) => setError(caught.message));
    // Once, on arrival; `onChanged` is the parent's setter.
  }, []);

  async function update(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    setSaved(null);
    try {
      const body = await api.put<ShopifyConnectionState>("/api/operations/shopify-connection", {
        shop_domain: domain,
        client_id: clientId || null,
        client_secret: secret || null,
      });
      setState(body);
      // The secret leaves the page as soon as it has done its job.
      setSecret("");
      setClientId("");
      setSaved(body.shop_name ? `Connection updated. Shopify answered as ${body.shop_name}.` : "Connection updated.");
      onChanged?.(body);
    } catch (caught) {
      // Nothing was saved, and nothing typed is thrown away.
      setError(caught instanceof Error ? caught.message : "The connection was not changed.");
    } finally {
      setWorking(false);
    }
  }

  const saving = state?.source === "saved";
  return (
    <section className="pay-detail__card sync__card">
      <h2 className="pay-detail__card-title">Connection</h2>
      <form className="shop-conn" onSubmit={update}>
        <label className="shop-conn__field">
          <span className="shop-conn__label">Store domain</span>
          <input className="shop-conn__input" type="text" autoComplete="off" spellCheck={false}
            placeholder="your-store.myshopify.com" value={domain} onChange={(e) => setDomain(e.target.value)} />
        </label>
        <label className="shop-conn__field">
          <span className="shop-conn__label">Client ID</span>
          <input className="shop-conn__input" type="text" autoComplete="off" spellCheck={false}
            placeholder={saving && state?.client_id_hint ? `Saved ${state.client_id_hint} - leave blank to keep` : ""}
            value={clientId} onChange={(e) => setClientId(e.target.value)} />
        </label>
        <label className="shop-conn__field">
          <span className="shop-conn__label">Client secret</span>
          <input className="shop-conn__input" type="password" autoComplete="new-password"
            placeholder={saving && state?.secret_saved ? "Saved - leave blank to keep" : ""}
            value={secret} onChange={(e) => setSecret(e.target.value)} />
        </label>
        {state?.problem && <p className="sync__error">{state.problem}</p>}
        {state && !state.can_save && (
          <p className="sync__error">This server cannot protect a saved secret yet (SETTINGS_ENCRYPTION_KEY is not set).</p>
        )}
        {error && <p className="sync__error" role="alert">{error}</p>}
        {saved && <p className="sync__notice" role="status">{saved}</p>}
        <button type="submit" className="button shop-conn__submit" disabled={working || !state?.can_save || !domain.trim()}>
          {working ? "Checking with Shopify…" : "Update connection"}
        </button>
      </form>
    </section>
  );
}
