import { useEffect, useState } from "react";

import { api, signOut } from "../lib/api";
import type { Session } from "../lib/api";
import { Apply } from "./Apply";
import { MyPayout } from "./MyPayout";
import "./Apply.css";
import "./AffiliateHome.css";

type Mine = { applied: boolean; status: string | null };

type Me = {
  name: string;
  phone: string | null;
  status: string;
  state: string;
  codes: { code: string; verified: boolean }[];
  payout_destination: Record<string, string | null> | null;
  required_fields: Record<string, string[]>;
};

/**
 * Where a model lands after signing in.
 *
 * The routing splits on **what the session is**, not on what it may do: a
 * model never sees the maintainer's navigation, and not because those screens
 * would refuse her. A menu full of things that refuse you is a menu that
 * teaches you the tool is broken.
 *
 * This phase gives her three states and nothing else. Earnings, orders and
 * payment history arrive in Phase 9, and the screen says so plainly rather
 * than showing empty panels that look like she has earned nothing.
 */
export function AffiliateHome({ session }: { session: Session }) {
  const [mine, setMine] = useState<Mine | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [changing, setChanging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function load() {
    api
      .get<Mine>("/api/applications/mine")
      .then((body) => {
        setMine(body);
        // Only once a profile exists - `/api/me` is gated on owning one, so
        // asking before she has applied would be a guaranteed 403.
        if (body.applied) {
          return api.get<Me>("/api/me").then((detail) => {
            setMe(detail);
            setChanging(false);
          });
        }
        return undefined;
      })
      .catch((caught) => setError(caught.message));
  }

  useEffect(load, []);

  if (error) {
    return (
      <main className="affiliate">
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      </main>
    );
  }

  if (mine === null) {
    return (
      <main className="affiliate">
        <p className="empty">Loading…</p>
      </main>
    );
  }

  // Invited, accepted, and not yet applied. The form is the whole screen -
  // there is nothing else for her to do until it is sent.
  if (!mine.applied) return <Apply onApplied={load} />;

  return (
    <main className="affiliate">
      <div className="affiliate__head">
        <div>
          <span className="affiliate__mark">HBA</span>
          <h1 className="affiliate__title">
            {session.actor.display_name || session.actor.email}
          </h1>
        </div>
        <button
          type="button"
          className="affiliate__sign-out"
          onClick={() => signOut().then(() => window.location.assign("/sign-in"))}
        >
          Sign out
        </button>
      </div>

      {/*
       * "Waiting" and "nothing here yet" are completely different messages to
       * the one person they are about, so they are never the same screen.
       */}
      {mine.status === "pending" && (
        <section className="panel affiliate__panel">
          <h2 className="panel__title">We have your application</h2>
          <p className="affiliate__lead">
            Someone at HBA is checking your discount code against the shop. You
            will hear from us once that is done — there is nothing else for you
            to do right now.
          </p>
        </section>
      )}

      {mine.status === "active" && (
        <section className="panel affiliate__panel">
          <h2 className="panel__title">You are on the programme</h2>
          <p className="affiliate__lead">
            Your code is live and your sales are being counted.
          </p>
          <p className="affiliate__lead affiliate__soon">
            What you have earned, the orders behind it, and what you have been
            paid are coming to this page shortly.
          </p>
        </section>
      )}

      {mine.status === "inactive" && (
        <section className="panel affiliate__panel">
          <h2 className="panel__title">Your code is paused</h2>
          <p className="affiliate__lead">
            New sales are not being counted at the moment. Anything you were
            already owed still stands — speak to HBA if this is unexpected.
          </p>
        </section>
      )}

      {me && !changing && (
        <section className="panel affiliate__panel affiliate__details">
          <h2 className="panel__title">Your details</h2>
          <dl className="affiliate__list">
            <div>
              <dt>Your code</dt>
              <dd>
                {me.codes.length === 0 ? (
                  "—"
                ) : (
                  me.codes.map((entry) => (
                    <span key={entry.code} className="affiliate__code">
                      <span className="code">{entry.code}</span>
                      {!entry.verified && (
                        <span className="affiliate__pending-code">
                          being checked
                        </span>
                      )}
                    </span>
                  ))
                )}
              </dd>
            </div>
            <div>
              <dt>Paid to</dt>
              <dd>{describeDestination(me.payout_destination)}</dd>
            </div>
          </dl>
          {/*
           * Shortened even to her. She supplied it, so it tells her nothing
           * she does not know - and a screen printing a full account number is
           * one worth photographing over her shoulder on a bus.
           */}
          <p className="affiliate__note">
            Shortened on purpose. You gave us these, so this is only here for
            you to recognise which account it is.
          </p>
          <button
            type="button"
            className="button"
            onClick={() => setChanging(true)}
          >
            Change where I am paid
          </button>
        </section>
      )}

      {me && changing && (
        <MyPayout
          current={me.payout_destination}
          required={me.required_fields}
          onChanged={load}
          onCancel={() => setChanging(false)}
        />
      )}
    </main>
  );
}

function describeDestination(
  destination: Record<string, string | null> | null,
): string {
  if (!destination) return "Nothing on file yet";
  const label: Record<string, string> = {
    instapay: "InstaPay",
    bank: "Bank transfer",
    wallet: "Mobile wallet",
  };
  const method = destination.method ?? "";
  const shown =
    destination.instapay_address_url ??
    destination.bank_account_number ??
    destination.wallet_phone ??
    "";
  return `${label[method] ?? method} · ${shown}`;
}
