import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../lib/api";

/**
 * Giving HBA10 - or any code that is not a person - an account of its own.
 *
 * **A model's onboarding, minus the model.** Inviting a model is three
 * separate acts on purpose (§8, §10.4): accept an invitation, register a
 * code, get approved - each one waiting for somebody to come back and do the
 * next thing. A house account has nobody to come back. It has no password to
 * set, no payout destination, no compensation to wait on - a house code is
 * never paid, so the only thing standing between it and *active* is a code
 * Shopify can confirm exists. So this does all three in one press: create
 * the account, register the code, verify it, and approve it if it verifies.
 *
 * **Not on the same button as inviting a model.** The two are opposite in
 * the one way that matters - one creates a person who signs in and gets
 * paid, the other creates a code that never does either - and putting them
 * behind one control invites exactly the mistake this exists to prevent:
 * approving a real customer's discount code as though it were a colleague.
 */
export function AddHouseCode({ onCreated }: { onCreated: () => void }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    try {
      const created = await api.post<{ id: number }>("/api/affiliates/house", {
        name: name.trim(),
        code: code.trim(),
      });
      setOpen(false);
      setName("");
      setCode("");
      onCreated();
      navigate(`/affiliates/${created.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save that.");
    } finally {
      setWorking(false);
    }
  }

  if (!open) {
    return (
      <button type="button" className="button" onClick={() => setOpen(true)}>
        Add a house code
      </button>
    );
  }

  return (
    <section className="panel invite">
      <div className="panel__head">
        <h2 className="panel__title">Add a house code</h2>
      </div>

      <div className="invite__body">
        {error && (
          <p className="notice notice--refused" role="alert">
            {error}
          </p>
        )}

        <p className="invite__lead">
          For a code that is HBA's own, not a model's - real customers use it
          and its sales are counted, but it is never paid a commission and
          never appears in a ranking. Shopify is asked about the code before
          anything is saved, the same as registering one for a model.
        </p>

        <form onSubmit={submit} className="invite__form">
          <label className="field invite__field">
            <span className="field__label">What is it called?</span>
            <input
              className="input"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="HBA10"
              required
            />
          </label>

          <label className="field invite__field">
            <span className="field__label">The code</span>
            <input
              className="input"
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder="HBA10"
              required
            />
            <span className="field__hint">
              Checked against Shopify on save. Approved immediately if it is
              confirmed there; recorded either way.
            </span>
          </label>

          <div className="invite__actions">
            <button
              type="button"
              className="button"
              onClick={() => {
                setOpen(false);
                setError(null);
              }}
              disabled={working}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="button button--primary"
              disabled={working || !name.trim() || !code.trim()}
            >
              {working ? "Asking Shopify…" : "Create it"}
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}
