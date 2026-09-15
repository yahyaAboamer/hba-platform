import { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes, useSearchParams } from "react-router-dom";

import { AffiliateLayout, PortalHeader } from "../components/AffiliateLayout";
import type { PortalContext } from "../components/AffiliateLayout";
import { api } from "../lib/api";
import type { Session } from "../lib/api";
import { MyBestSellers, MyWardrobe } from "./MyWardrobe";
import { storedTheme } from "../lib/theme";
import { Apply } from "./Apply";
import { Glossary } from "./Glossary";
import { MyDetails } from "./MyDetails";
import type { Me } from "./MyDetails";
import { MyCalculation } from "./MyCalculation";
import { MyMonth } from "./MyMonth";
import { MyOrders } from "./MyOrders";
import { MyPayments } from "./MyPayments";
import { MyPolicy } from "./MyPolicy";
import { MyRanking } from "./MyRanking";
import { MyTargets } from "./MyTargets";
import "./Apply.css";
import "./AffiliateHome.css";

type Mine = { applied: boolean; status: string | null };

/**
 * Where a model lands after signing in, and everything they can reach.
 *
 * The routing splits on **what the session is**, not on what it may do: a
 * model never sees the maintainer's navigation, and not because those screens
 * would refuse them. A menu full of things that refuse you is a menu that
 * teaches you the tool is broken.
 *
 * **A pending application gets no tabs.** They are not on the programme yet, so
 * an Earnings tab would open on a month with no pay terms and tell their HBA has
 * not set their rate — true, and a worse answer than "we are checking your
 * application". Tabs appear when there is something behind them.
 */
export function AffiliatePortal({ session }: { session: Session }) {
  const [mine, setMine] = useState<Mine | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [months, setMonths] = useState<string[]>([]);
  const [month, setMonth] = useState<string | null>(null);
  /**
   * A month named in the address, so a receipt can link to the month that
   * explains it (AC41).
   *
   * Read once into state rather than driving the picker from the URL: moving
   * between months is the most-used control in the portal, and putting a
   * history entry behind every tap would turn the phone's back button into a
   * walk through every month she looked at.
   *
   * **Honoured only if it is a month she can actually see.** The list comes
   * from the server; anything else in the query string is ignored rather than
   * loaded, so a mistyped or stale link opens her working month instead of an
   * empty screen she cannot explain.
   */
  const [addressed] = useSearchParams();
  const wanted = addressed.get("month");
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
        // asking before they have applied would be a guaranteed 403.
        if (!body.applied) return undefined;
        return Promise.all([
          api.get<Me>("/api/me"),
          api.get<{ months: string[] }>("/api/me/months"),
        ]).then(([detail, calendar]) => {
          setMe(detail);
          setMonths(calendar.months);
          // Opens on the working month and stays wherever they move it. The
          // server decides which month that is - the browser's clock is not
          // in Cairo and is not authoritative about anything (ADR 0005).
          setMonth(
            (was) =>
              was ??
              (wanted && calendar.months.includes(wanted) ? wanted : null) ??
              calendar.months[0] ??
              null,
          );
        });
      })
      .catch((caught) => setError(caught.message));
  }, [wanted]);

  // Wrapped rather than passed: `load` returns a promise now, and an effect
  // callback returning one is read by React as a cleanup function.
  useEffect(() => {
    void load();
  }, [load]);

  /**
   * Which theme this device is in.
   *
   * Read once, stamped on the portal root, and changed from the You screen.
   * It lives here rather than in the layout because the screens a model sees
   * *before* they are on the programme - loading, waiting on an application -
   * are outside the layout and would otherwise paint in the wrong theme for
   * the split second before the real one arrived.
   */
  const [theme, setTheme] = useState(storedTheme);
  // What the month on screen is, in a word, for the bar above it. Held here
  // rather than in the bar because only the screen that loaded the month has
  // the figure — the bar has no data of its own and must never guess.
  const [monthState, setMonthState] = useState<string | null>(null);

  const firstCode = me?.codes?.[0] ?? null;
  const header = (
    <PortalHeader
      name={me?.name || session.actor.display_name || session.actor.email}
      code={firstCode?.code ?? null}
      month={month ?? undefined} months={months} onMonth={setMonth}
      codePending={firstCode ? !firstCode.verified : false}
    />
  );

  if (error) {
    return (
      <main className="affiliate" data-theme={theme}>
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      </main>
    );
  }

  if (mine === null) {
    return (
      <main className="affiliate" data-theme={theme}>
        <p className="empty">Loading…</p>
      </main>
    );
  }

  // Invited, accepted, and not yet applied. The form is the whole screen -
  // there is nothing else for them to do until it is sent.
  if (!mine.applied) return <Apply onApplied={load} />;

  if (me === null || month === null) {
    return (
      <main className="affiliate" data-theme={theme}>
        {header}
        <p className="empty">Loading…</p>
      </main>
    );
  }

  // "Waiting" and "nothing here yet" are completely different messages to the
  // one person they are about, so they are never the same screen.
  if (mine.status === "pending") {
    return (
      <main className="affiliate" data-theme={theme}>
        {header}
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

  const context: PortalContext = {
    me,
    month,
    months,
    setMonth,
    reload: load,
    monthState,
    setMonthState,
  };

  return (
    <main className="affiliate" data-theme={theme}>
      {/*
       * True across every tab, so it sits above them rather than on one. §8:
       * *not earning, may return* - and anything they were already owed still
       * stands, which is the part they will be worried about.
       */}
      {mine.status === "inactive" && (
        <p className="notice affiliate__paused">
          Your code is paused, so new sales are not being counted. Anything you
          were already owed still stands.
        </p>
      )}

      <Routes>
        <Route element={<AffiliateLayout context={context} header={header} />}>
          <Route index element={<MyMonth />} />
          <Route path="earnings" element={<MyCalculation />} />
          <Route path="orders" element={<MyOrders />} />
          <Route path="wardrobe" element={<MyWardrobe />} />
          <Route path="best" element={<MyBestSellers />} />
          <Route path="targets" element={<MyTargets />} />
          <Route path="ranking" element={<MyRanking />} />

          {/*
           * Off the tab bar since the redesign, and deliberately still here.
           * Payments is linked from You, Year and Grow from Home. A receipt
           * email and a bookmark both still land on the screen they name.
           */}
          <Route path="payments" element={<MyPayments />} />
          <Route path="year" element={<Navigate to="/" replace />} />
          <Route path="grow" element={<Navigate to="/" replace />} />
          <Route
            path="you"
            element={
              <MyDetails
                me={me}
                onChanged={load}
                theme={theme}
                onTheme={setTheme}
              />
            }
          />
          <Route path="policy/:id" element={<MyPolicy />} />
          <Route path="glossary" element={<Glossary />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </main>
  );
}
