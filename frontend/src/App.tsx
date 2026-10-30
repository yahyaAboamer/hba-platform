import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { DEPARTMENTS, departmentsFor, startFor } from "./departments";
import { api, can, currentUser, deskFor } from "./lib/api";
import type { Session } from "./lib/api";
import { AcceptInvitation } from "./screens/AcceptInvitation";
import { ResetPassword } from "./screens/ResetPassword";
import { AffiliatePortal } from "./portal/AffiliatePortal";
import { Elsewhere, Start } from "./frame/Elsewhere";
import { Onward } from "./frame/Onward";
import { Frame } from "./frame/Frame";
import { TODAY, canOpenSettings, holdsToday } from "./frame/where";
import { FirstRun } from "./screens/FirstRun";
import { Glossary } from "./screens/Glossary";
import { Today } from "./departments/today/Today";
import { PortalPreviewFrame, previewFrameFor } from "./departments/affiliates/PortalPreview";
import { Settings } from "./screens/Settings";
import { SignIn } from "./screens/SignIn";
import { TwoStepRequired } from "./screens/TwoStepRequired";

/**
 * The staff routes (ADR 0068): one frame, and in it a department's routes for
 * each department the person holds. Everything else - an old address, a
 * department they do not hold, an address that is not a screen - is
 * `Elsewhere`, inside the frame.
 */
function staffRoutes(session: Session) {
  const held = departmentsFor(session);
  return (
    <Route element={<Frame session={session} departments={held} />}>
      <Route path="/" element={<Start session={session} departments={DEPARTMENTS} />} />
      {/* Today is for anyone holding two or more departments; one department's person starts in it. */}
      {holdsToday(held) ? (
        <Route path={TODAY} element={<Today />} />
      ) : (
        held.length === 1 && <Route path={TODAY} element={<Onward to={startFor(session)} />} />
      )}
      {held.map((department) => (
        <Route key={department.key} path={department.base}>
          {department.routes(session)}
        </Route>
      ))}
      {canOpenSettings(session) && (
        <>
          <Route path="/settings" element={<Settings session={session} />} />
          <Route path="/glossary" element={<Glossary />} />
        </>
      )}
      <Route path="*" element={<Elsewhere session={session} departments={DEPARTMENTS} />} />
    </Route>
  );
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);
  const [needsSetup, setNeedsSetup] = useState(false);
  // Said once, after signing in with a recovery code (see SignIn).
  const [signInNotice, setSignInNotice] = useState<string | null>(null);

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

  // Batch 1.3: while their access needs two-step sign-in and it is not on,
  // there is nothing to show but its set-up - the server refuses every other
  // call, so a desk would only be a page of errors.
  if (session?.actor.two_step?.must_set_up) {
    return (
      <TwoStepRequired
        onDone={() => {
          currentUser().then(setSession).catch(() => setSession(null));
        }}
      />
    );
  }

  // ADR 0064: the frame inside "View her portal". Her portal is decided before
  // the router, because it brings a router of its own - and only for somebody
  // who may open her profile; anybody else falls through to the routes below.
  const previewed = previewFrameFor(window.location.pathname);
  if (session && previewed !== null && can(session, "affiliates.view")) {
    return <PortalPreviewFrame affiliateId={previewed} session={session} />;
  }

  // ADR 0067: the screens a person gets follow from what they may do, never
  // from a role's name, so a person holding two roles gets both.
  const desk = session ? deskFor(session) : null;

  return (
    <BrowserRouter>
      {session && signInNotice && (
        <p className="notice notice--settled" role="status">
          {signInNotice}{" "}
          <button type="button" className="settings__link-button" onClick={() => setSignInNotice(null)}>
            Dismiss
          </button>
        </p>
      )}
      <Routes>
        <Route
          path="/sign-in"
          element={
            session ? (
              <Navigate to="/" replace />
            ) : (
              <SignIn
                onSignedIn={(signedIn, notice) => {
                  setSignInNotice(notice ?? null);
                  setSession(signedIn);
                }}
              />
            )
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
         * Unauthenticated for the same reason: somebody who has lost their
         * password has no session to check. Rendered whatever the session
         * state, because an already-signed-in person following a reset link
         * from their own inbox is an ordinary case, not a misuse.
         */}
        <Route
          path="/reset-password"
          element={
            <ResetPassword
              onSignedIn={(signedIn, notice) => {
                setSignInNotice(notice ?? null);
                setSession(signedIn);
              }}
            />
          }
        />
        {/*
         * §6.1. Somebody holding no staff permission at all - a model, or
         * somebody invited to become one - gets her portal. Every admin route
         * would refuse her, and a sidebar full of things that refuse you is a
         * sidebar that teaches you the tool is broken. Before this, a model
         * signing in landed on the maintainer's Overview and a 403.
         */}
        {session && desk === "portal" ? (
          <Route path="*" element={<AffiliatePortal session={session} />} />
        ) : session ? (
          staffRoutes(session)
        ) : (
          <Route path="*" element={<Navigate to="/sign-in" replace />} />
        )}
      </Routes>
    </BrowserRouter>
  );
}
