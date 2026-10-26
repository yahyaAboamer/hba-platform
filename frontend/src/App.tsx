import { useEffect, useState } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";

import { InboxLayout } from "./components/InboxLayout";
import { Layout } from "./components/Layout";
import { OperationsLayout } from "./components/OperationsLayout";
import { api, can, currentUser, deskFor } from "./lib/api";
import type { Session } from "./lib/api";
import { AcceptInvitation } from "./screens/AcceptInvitation";
import { ResetPassword } from "./screens/ResetPassword";
import { AffiliateDetail } from "./screens/AffiliateDetail";
import { AffiliatePortal } from "./screens/AffiliatePortal";
import { AffiliatePayments } from "./screens/AffiliatePayments";
import { AffiliatePayout } from "./screens/AffiliatePayout";
import { Affiliates } from "./screens/Affiliates";
import { Compensation } from "./screens/Compensation";
import { FirstRun } from "./screens/FirstRun";
import { Glossary } from "./screens/Glossary";
import { InboxChats } from "./screens/InboxChats";
import { InboxConfirmations } from "./screens/InboxConfirmations";
import { InvitePage } from "./screens/InvitePage";
import { OperationsDashboard } from "./screens/OperationsDashboard";
import { OrderDetail, Orders } from "./screens/Orders";
import { Overview } from "./screens/Overview";
import { ProductDetail, Products } from "./screens/Products";
import { PaymentReconcile } from "./screens/PaymentReconcile";
import { PortalPreview, PortalPreviewFrame, previewFrameFor } from "./screens/PortalPreview";
import { PaymentCorrection } from "./screens/PaymentCorrection";
import { PaymentDetail, PaymentReceipt } from "./screens/PaymentDetail";
import { PaymentRecord } from "./screens/PaymentRecord";
import { Payments } from "./screens/Payments";
import { Payroll } from "./screens/Payroll";
import { PayrollApprove } from "./screens/PayrollApprove";
import { Settings } from "./screens/Settings";
import { SignIn } from "./screens/SignIn";
import { TwoStepRequired } from "./screens/TwoStepRequired";
import { Targets } from "./screens/Targets";

/**
 * Operations' addresses (ADR 0057), for the operations manager and for the
 * admin who switches to it. `/operations` opens on Shopify.
 */
function operationsRoutes(session: Session) {
  return (
    <Route path="/operations" element={<OperationsLayout session={session} />}>
      <Route index element={<Navigate to="shopify" replace />} />
      <Route path=":tab" element={<OperationsDashboard />} />
    </Route>
  );
}

/**
 * The Inbox's addresses (ADR 0059), for customer service and for the
 * operations manager and the admin who switch to it. `/inbox` opens on Chats,
 * and a chat's own address is `/inbox/chats/<id>`.
 */
function inboxRoutes(session: Session) {
  return (
    <Route path="/inbox" element={<InboxLayout session={session} />}>
      <Route index element={<Navigate to="chats" replace />} />
      <Route path="chats" element={<InboxChats />} />
      <Route path="chats/:conversationId" element={<InboxChats />} />
      <Route path="confirmations" element={<InboxConfirmations />} />
      <Route path="*" element={<Navigate to="/inbox/chats" replace />} />
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
        ) : session && desk === "operations" ? (
          /*
           * ADR 0057: Operations and nothing else. Any other address - the
           * root after signing in or accepting an invitation, an old bookmark
           * to the affiliate side - lands on Shopify.
           */
          <>
            {operationsRoutes(session)}
            {/* ADR 0059: the Inbox too, for whoever holds it. */}
            {can(session, "inbox.use") && inboxRoutes(session)}
            <Route path="*" element={<Navigate to="/operations/shopify" replace />} />
          </>
        ) : session && desk === "inbox" ? (
          /*
           * ADR 0059: the Inbox and nothing else. Any other address lands on
           * Chats, as the operations manager's lands on Shopify.
           */
          <>
            {inboxRoutes(session)}
            <Route path="*" element={<Navigate to="/inbox/chats" replace />} />
          </>
        ) : session ? (
          <>
          {can(session, "order_ops.view") && operationsRoutes(session)}
          {can(session, "inbox.use") && inboxRoutes(session)}
          <Route element={<Layout session={session} />}>
            <Route path="/" element={<Overview session={session} />} />
            <Route path="/affiliates" element={<Affiliates />} />
            {/* Before the profile route so `invite` is never read as an id. */}
            <Route path="/affiliates/invite" element={<InvitePage session={session} />} />
            <Route
              path="/affiliates/:id"
              element={<AffiliateDetail session={session} />}
            />
            {can(session, "affiliates.view") && (
              <Route path="/affiliates/:id/portal" element={<PortalPreview />} />
            )}
            <Route
              path="/affiliates/:id/compensation"
              element={<Compensation />}
            />
            <Route
              path="/affiliates/:id/payments"
              element={<AffiliatePayments />}
            />
            <Route
              path="/affiliates/:id/payout-destination"
              element={<AffiliatePayout />}
            />
            <Route path="/products" element={<Products session={session} />} />
            <Route
              path="/products/:id"
              element={<ProductDetail session={session} />}
            />
            {/*
             * Off the sidebar since the redesign, and deliberately still
             * routed. Orders is linked from Home, Payroll from Payments -
             * S02 keeps every necessary operation reachable, and neither
             * screen was rebuilt in this batch, only moved.
             */}
            <Route path="/orders" element={<Orders session={session} />} />
            {/* The approved export opens an order into its own view. */}
            <Route path="/orders/:orderId" element={<OrderDetail />} />
            <Route path="/payroll" element={<Payroll session={session} />} />
            <Route path="/payroll/:month/approve" element={<PayrollApprove />} />
            <Route path="/payments" element={<Payments session={session} />} />
            {/* One model's month, as the approved export opens it: the
             *  figure, where to send it, the approval and the transfers. */}
            <Route
              path="/payments/:month/:affiliateId"
              element={<PaymentDetail session={session} />}
            />
            <Route
              path="/payments/:month/:affiliateId/record"
              element={<PaymentRecord />}
            />
            <Route
              path="/payments/:month/:affiliateId/receipts/:paymentId"
              element={<PaymentReceipt />}
            />
            <Route
              path="/payments/:month/:affiliateId/reconcile"
              element={<PaymentReconcile />}
            />
            <Route
              path="/payments/:month/:affiliateId/correction"
              element={<PaymentCorrection session={session} />}
            />
            <Route path="/targets" element={<Targets session={session} />} />
            <Route path="/settings" element={<Settings session={session} />} />
            <Route path="/glossary" element={<Glossary />} />
            {/*
             * An address that is not a screen - an old bookmark to the retired
             * reopening screen, say - says so inside the layout, rather than
             * rendering a blank page.
             */}
            <Route path="*" element={
              <div className="page__head">
                <div className="page__title">
                  <h1>Nothing here</h1>
                  <span className="page__subtitle">There is no screen at this address. <Link to="/">Home</Link></span>
                </div>
              </div>
            } />
          </Route>
          </>
        ) : (
          <Route path="*" element={<Navigate to="/sign-in" replace />} />
        )}
      </Routes>
    </BrowserRouter>
  );
}
