import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { currentUser } from "./lib/api";
import type { Session } from "./lib/api";
import { AffiliateDetail } from "./screens/AffiliateDetail";
import { Affiliates } from "./screens/Affiliates";
import { Overview } from "./screens/Overview";
import { SignIn } from "./screens/SignIn";

/** A section that exists in the navigation and not yet in the platform. */
function NotBuiltYet({ name, phase }: { name: string; phase: string }) {
  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>{name}</h1>
        </div>
      </div>
      <p className="empty">
        {name} is built in the platform and does not have a screen yet. {phase}
      </p>
    </>
  );
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    currentUser()
      .then(setSession)
      .catch(() => setSession(null))
      .finally(() => setChecking(false));
  }, []);

  // Nothing is rendered until it is known whether somebody is signed in.
  // Flashing the sign-in screen at a signed-in person reads as being logged
  // out, which on a payroll tool is alarming rather than merely untidy.
  if (checking) return null;

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/sign-in"
          element={
            session ? <Navigate to="/" replace /> : <SignIn onSignedIn={setSession} />
          }
        />
        {session ? (
          <Route element={<Layout session={session} />}>
            <Route path="/" element={<Overview session={session} />} />
            <Route path="/affiliates" element={<Affiliates />} />
            <Route path="/affiliates/:id" element={<AffiliateDetail />} />
            <Route
              path="/orders"
              element={<NotBuiltYet name="Orders" phase="Coming after the payroll screens." />}
            />
            <Route
              path="/payroll"
              element={<NotBuiltYet name="Payroll" phase="Coming next, after affiliates." />}
            />
            <Route
              path="/payments"
              element={<NotBuiltYet name="Payments" phase="Coming after payroll." />}
            />
            <Route
              path="/targets"
              element={<NotBuiltYet name="Targets" phase="Coming after payments." />}
            />
            <Route
              path="/settings"
              element={<NotBuiltYet name="Settings" phase="Coming last." />}
            />
          </Route>
        ) : (
          <Route path="*" element={<Navigate to="/sign-in" replace />} />
        )}
      </Routes>
    </BrowserRouter>
  );
}
