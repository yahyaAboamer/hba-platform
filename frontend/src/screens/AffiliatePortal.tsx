import { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { AffiliateLayout } from "../components/AffiliateLayout";
import type { PortalContext } from "../components/AffiliateLayout";
import { api, signOutAndLeave } from "../lib/api";
import type { Session } from "../lib/api";
import { Apply } from "./Apply";
import { MyDetails } from "./MyDetails";
import type { Me } from "./MyDetails";
import { MyMonth } from "./MyMonth";
import { MyOrders } from "./MyOrders";
import { MyPayments } from "./MyPayments";
import "./Apply.css";
import "./AffiliateHome.css";

type Mine = { applied: boolean; status: string | null };

/**
 * Where a model lands after signing in, and everything she can reach.
 *
 * The routing splits on **what the session is**, not on what it may do: a
 * model never sees the maintainer's navigation, and not because those screens
 * would refuse her. A menu full of things that refuse you is a menu that
 * teaches you the tool is broken.
 *
 * **A pending application gets no tabs.** She is not on the programme yet, so
 * an Earnings tab would open on a month with no pay terms and tell her HBA has
 * not set her rate — true, and a worse answer than "we are checking your
 * application". Tabs appear when there is something behind them.
 */
export function AffiliatePortal({ session }: { session: Session }) {
  const [mine, setMine] = useState<Mine | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [months, setMonths] = useState<string[]>([]);
  const [month, setMonth] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    // Returned, so a caller can wait for it. Changing where you are paid used
    // to close its form the instant the write returned, leaving the old
    // destination on screen until this landed - and somebody watching that saw
    // nothing happen at all.
    return api
      .get<Mine>("/api/applications/mine")
      .then((body) => {
        setMine(body);
        // Only once a profile exists - `/api/me` is gated on owning one, so
        // asking before she has applied would be a guaranteed 403.
        if (!body.applied) return undefined;
        return Promise.all([
          api.get<Me>("/api/me"),
          api.get<{ months: string[] }>("/api/me/months"),
        ]).then(([detail, calendar]) => {
          setMe(detail);
          setMonths(calendar.months);
          // Opens on the working month and stays wherever she moves it. The
          // server decides which month that is - the browser's clock is not
          // in Cairo and is not authoritative about anything (ADR 0005).
          setMonth((was) => was ?? calendar.months[0] ?? null);
        });
      })
      .catch((caught) => setError(caught.message));
  }, []);

  // Wrapped rather than passed: `load` returns a promise now, and an effect
  // callback returning one is read by React as a cleanup function.
  useEffect(() => {
    void load();
  }, [load]);

  const head = (
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
        onClick={signOutAndLeave}
      >
        Sign out
      </button>
    </div>
  );

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

  if (me === null || month === null) {
    return (
      <main className="affiliate">
        {head}
        <p className="empty">Loading…</p>
      </main>
    );
  }

  // "Waiting" and "nothing here yet" are completely different messages to the
  // one person they are about, so they are never the same screen.
  if (mine.status === "pending") {
    return (
      <main className="affiliate">
        {head}
        <section className="panel affiliate__panel">
          <h2 className="panel__title">We have your application</h2>
          <p className="affiliate__lead">
            Someone at HBA is checking your discount code against the shop. You
            will hear from us once that is done — there is nothing else for you
            to do right now.
          </p>
        </section>
        <MyDetails me={me} onChanged={load} />
      </main>
    );
  }

  const context: PortalContext = { month, months, setMonth, reload: load };

  return (
    <main className="affiliate">
      {head}

      {/*
       * True across every tab, so it sits above them rather than on one. §8:
       * *not earning, may return* - and anything she was already owed still
       * stands, which is the part she will be worried about.
       */}
      {mine.status === "inactive" && (
        <p className="notice affiliate__paused">
          Your code is paused, so new sales are not being counted. Anything you
          were already owed still stands.
        </p>
      )}

      <Routes>
        <Route element={<AffiliateLayout context={context} />}>
          <Route index element={<MyMonth />} />
          <Route path="orders" element={<MyOrders />} />
          <Route path="payments" element={<MyPayments />} />
          <Route path="you" element={<MyDetails me={me} onChanged={load} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </main>
  );
}
