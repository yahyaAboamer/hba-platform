import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { currentUser } from "./lib/api";
import type { Session } from "./lib/api";
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
            <Route path="/" element={<Overview />} />
            <Route
              path="/affiliates"
              element={<NotBuiltYet name="Affiliates" phase="Next." />}
            />
            <Route
              path="/orders"
              element={<NotBuiltYet name="Orders" phase="After affiliates." />}
            />
            <Route
              path="/payroll"
              element={<NotBuiltYet name="Payroll" phase="After orders." />}
            />
            <Route
              path="/payments"
              element={<NotBuiltYet name="Payments" phase="After payroll." />}
            />
            <Route
              path="/targets"
              element={<NotBuiltYet name="Targets" phase="After payments." />}
            />
            <Route
              path="/settings"
              element={<NotBuiltYet name="Settings" phase="Last." />}
            />
          </Route>
        ) : (
          <Route path="*" element={<Navigate to="/sign-in" replace />} />
        )}
      </Routes>
    </BrowserRouter>
  );
}
