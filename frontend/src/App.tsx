import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { api, currentUser } from "./lib/api";
import type { Session } from "./lib/api";
import { AcceptInvitation } from "./screens/AcceptInvitation";
import { AffiliateDetail } from "./screens/AffiliateDetail";
import { AffiliatePortal } from "./screens/AffiliatePortal";
import { Affiliates } from "./screens/Affiliates";
import { Compensation } from "./screens/Compensation";
import { FirstRun } from "./screens/FirstRun";
import { Orders } from "./screens/Orders";
import { Overview } from "./screens/Overview";
import { PaymentReconcile } from "./screens/PaymentReconcile";
import { PaymentRecord } from "./screens/PaymentRecord";
import { Payments } from "./screens/Payments";
import { Payroll } from "./screens/Payroll";
import { PayrollApprove } from "./screens/PayrollApprove";
import { PayrollReopen } from "./screens/PayrollReopen";
import { Settings } from "./screens/Settings";
import { SignIn } from "./screens/SignIn";
import { Targets } from "./screens/Targets";

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);
  const [needsSetup, setNeedsSetup] = useState(false);

  useEffect(() => {
    currentUser()
      .then(async (found) => {
        setSession(found);
        // Only asked when nobody is signed in. A fresh deployment has no
        // account at all, and until this screen existed the first step of
        // standing one up had no interface - the API docs are switched off in
        // production, so it meant calling the endpoint by hand.
        if (found === null) {
          const state = await api
            .get<{ needs_setup: boolean }>("/api/auth/needs-setup")
            .catch(() => ({ needs_setup: false }));
          setNeedsSetup(state.needs_setup);
        }
      })
      .catch(() => setSession(null))
      .finally(() => setChecking(false));
  }, []);

  // Nothing is rendered until it is known whether somebody is signed in.
  // Flashing the sign-in screen at a signed-in person reads as being logged
  // out, which on a payroll tool is alarming rather than merely untidy.
  if (checking) return null;

  // Before the router: there is exactly one thing to do on a platform with
  // nobody in it, and offering a sign-in form for accounts that do not exist
  // teaches somebody their password is wrong.
  if (!session && needsSetup) {
    return (
      <FirstRun
        onSignedIn={(created) => {
          setSession(created);
          setNeedsSetup(false);
        }}
      />
    );
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/sign-in"
          element={
            session ? <Navigate to="/" replace /> : <SignIn onSignedIn={setSession} />
          }
        />
        {/*
         * Reachable whether or not somebody is already signed in - an
         * existing admin opening their own invite link to check it is a real
         * scenario, not a misuse, and accepting replaces whichever session
         * was live either way.
         */}
        <Route
          path="/accept-invitation"
          element={<AcceptInvitation onSignedIn={setSession} />}
        />
        {/*
         * §6.1. The split is on **what the session is**, not on what it may
         * do. A model holds no staff permission at all, so every admin route
         * would refuse them - but a sidebar full of things that refuse you is a
         * sidebar that teaches you the tool is broken. Before this, a model
         * signing in landed on the maintainer's Overview and a 403.
         */}
        {session && session.actor.role === "affiliate" ? (
          <Route path="*" element={<AffiliatePortal session={session} />} />
        ) : session ? (
          <Route element={<Layout session={session} />}>
            <Route path="/" element={<Overview session={session} />} />
            <Route path="/affiliates" element={<Affiliates />} />
            <Route
              path="/affiliates/:id"
              element={<AffiliateDetail session={session} />}
            />
            <Route
              path="/affiliates/:id/compensation"
              element={<Compensation />}
            />
            <Route path="/orders" element={<Orders session={session} />} />
            <Route path="/payroll" element={<Payroll session={session} />} />
            <Route path="/payroll/:month/approve" element={<PayrollApprove />} />
            <Route path="/payroll/:month/reopen" element={<PayrollReopen />} />
            <Route path="/payments" element={<Payments session={session} />} />
            <Route
              path="/payments/:month/:affiliateId"
              element={<PaymentRecord />}
            />
            <Route
              path="/payments/:month/:affiliateId/reconcile"
              element={<PaymentReconcile />}
            />
            <Route path="/targets" element={<Targets session={session} />} />
            <Route path="/settings" element={<Settings session={session} />} />
          </Route>
        ) : (
          <Route path="*" element={<Navigate to="/sign-in" replace />} />
        )}
      </Routes>
    </BrowserRouter>
  );
}
