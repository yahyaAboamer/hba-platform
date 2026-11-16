/**
 * The supplier page's "Factory login" card (batch 6b): invite the factory to
 * sign in for itself, see where that stands, send the invitation again, and
 * switch it off (which signs it out at once).
 *
 * Drawn only for somebody who holds `production.suppliers`, and only when the
 * server sent `factory_login` at all - the key is absent for everybody else.
 * What the factory may then do is its own business (`/factory`): it sees only
 * its own orders, no prices, costs or payments.
 */
import { useId, useRef, useState } from "react";
import type { FormEvent } from "react";

import { api } from "../../../lib/api";
import { dayWords } from "../../../factory/logic";
import type { FactoryLogin } from "./types";
import { Problem, TextBox } from "./ui";

/** Told to the page after a write: what the server answered, and what to say. */
export type LoginChanged = (answer: unknown, said: string) => void;

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function InviteForm({ supplierId, label, onChanged }: { supplierId: string; label: string; onChanged: LoginChanged }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const flying = useRef(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (flying.current) return;
    const address = email.trim();
    const problem = !EMAIL.test(address) ? "Give the factory's email address." : !name.trim() ? "Give a name for the person who will sign in." : null;
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    flying.current = true;
    setBusy(true);
    try {
      const answer = await api.post<unknown>(`/api/prod/suppliers/${supplierId}/factory-login`, { email: address, name: name.trim() });
      setEmail("");
      setName("");
      onChanged(answer, `Invitation sent to ${address}.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The invitation could not be sent.");
    } finally {
      flying.current = false;
      setBusy(false);
    }
  }

  return (
    <form className="prod-form" onSubmit={submit} noValidate>
      <TextBox label="Email" value={email} onChange={setEmail} max={254} />
      <TextBox label="Name" value={name} onChange={setName} max={120} />
      <div className="prod-wide">
        {error && <Problem>{error}</Problem>}
        <div className="prod-actions">
          <button type="submit" className="button button--primary" disabled={busy}>
            {busy ? "Sending…" : label}
          </button>
        </div>
      </div>
    </form>
  );
}

export function FactoryLoginCard({ supplierId, login, onChanged }: { supplierId: string; login: FactoryLogin | null; onChanged: LoginChanged }) {
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const flying = useRef(false);
  const heading = useId();

  async function act(request: () => Promise<unknown>, said: string) {
    if (flying.current) return;
    flying.current = true;
    setBusy(true);
    setError(null);
    try {
      const answer = await request();
      setConfirming(false);
      onChanged(answer, said);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "That did not work.");
    } finally {
      flying.current = false;
      setBusy(false);
    }
  }

  const state = login?.state ?? null;
  return (
    <section className="prod-block" aria-labelledby={heading}>
      <div className="prod-block__head">
        <h2 id={heading}>Factory login</h2>
      </div>

      {login === null && (
        <>
          <p className="prod-small">
            Let this factory sign in for itself. It sees only its own orders: it tells HBA how many pieces it cut and moves its delivery
            date, and sees no prices, costs or payments.
          </p>
          <InviteForm supplierId={supplierId} label="Send the invitation" onChanged={onChanged} />
        </>
      )}

      {login !== null && state === "invited" && (
        <p>
          Invited <b>{login.email}</b> on {dayWords(login.invited_at)}. Waiting for them to accept.
        </p>
      )}
      {login !== null && state === "active" && (
        <p>
          <b>{login.email}</b> can sign in. Last seen {login.last_seen_at ? dayWords(login.last_seen_at) : "never"}.
        </p>
      )}
      {login !== null && state === "off" && (
        <>
          <p>
            The login for <b>{login.email}</b> is switched off. It cannot sign in. To invite the factory again, use another email address.
          </p>
          <InviteForm supplierId={supplierId} label="Invite again" onChanged={onChanged} />
        </>
      )}

      {login !== null && (state === "invited" || state === "active") && !confirming && (
        <div className="prod-actions">
          {state === "invited" && (
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() => void act(() => api.post<unknown>(`/api/prod/suppliers/${supplierId}/factory-login/resend`), `Invitation sent again to ${login.email}.`)}
            >
              Resend the invitation
            </button>
          )}
          <button type="button" className="button button--danger" disabled={busy} onClick={() => setConfirming(true)}>
            Switch off
          </button>
        </div>
      )}

      {confirming && login !== null && (
        <div role="alertdialog" aria-label="Switch off the factory login" className="prod-flag prod-flag--refused">
          <p>
            {state === "invited"
              ? `Switch off the invitation to ${login.email}? The link in the email stops working.`
              : `Switch off the login for ${login.email}? It is signed out at once and that address cannot be used again; to give the factory a login later, invite another address.`}
          </p>
          <div className="prod-actions">
            <button
              type="button"
              className="button button--danger"
              disabled={busy}
              onClick={() => void act(() => api.del<unknown>(`/api/prod/suppliers/${supplierId}/factory-login`), "The factory login is switched off.")}
            >
              {busy ? "Switching off…" : "Yes, switch it off"}
            </button>
            <button type="button" className="button" disabled={busy} onClick={() => setConfirming(false)}>
              Keep it
            </button>
          </div>
        </div>
      )}

      {error && <Problem>{error}</Problem>}
    </section>
  );
}
