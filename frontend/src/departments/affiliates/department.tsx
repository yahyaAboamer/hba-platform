import { Route } from "react-router-dom";

import { Onward } from "../../frame/Onward";
import type { Department } from "../types";
import { AffiliateDetail } from "./AffiliateDetail";
import { AffiliatePayments } from "./AffiliatePayments";
import { AffiliatePayout } from "./AffiliatePayout";
import { Affiliates } from "./Affiliates";
import { Compensation } from "./Compensation";
import { InvitePage } from "./InvitePage";
import { OrderDetail, Orders } from "./Orders";
import { Overview } from "./Overview";
import { PaymentCorrection } from "./PaymentCorrection";
import { PaymentDetail, PaymentReceipt } from "./PaymentDetail";
import { PaymentReconcile } from "./PaymentReconcile";
import { PaymentRecord } from "./PaymentRecord";
import { Payments } from "./Payments";
import { Payroll } from "./Payroll";
import { PayrollApprove } from "./PayrollApprove";
import { PortalPreview } from "./PortalPreview";
import { ProductDetail, Products } from "./Products";
import { Targets } from "./Targets";

/**
 * Affiliates: the roster, the catalogue, targets and money - what the
 * affiliate dashboard was before the frame (ADR 0068).
 *
 * Payroll and Orders are routed but not in the sidebar, as before: Orders is
 * linked from Overview, Payroll from Payments, and each shows its parent as
 * the current section.
 */
export const affiliates: Department = {
  key: "affiliates",
  name: "Affiliates",
  icon: "models",
  holds: "affiliates.view",
  base: "/affiliates",
  sections: [
    {
      slug: "overview",
      label: "Overview",
      to: "/affiliates/overview",
      also: ["/affiliates/orders"],
    },
    {
      slug: "models",
      label: "Models",
      to: "/affiliates/models",
      count: {
        key: "models_awaiting_approval",
        sentence: (count) => `${count} ${count === 1 ? "model" : "models"} awaiting approval`,
      },
    },
    { slug: "products", label: "Products", to: "/affiliates/products" },
    { slug: "targets", label: "Targets", to: "/affiliates/targets" },
    {
      slug: "payments",
      label: "Payments",
      to: "/affiliates/payments",
      also: ["/affiliates/payroll"],
      // The size of the *Awaiting approval* filter, counted by the same
      // function the Payments screen counts it with.
      count: {
        key: "payments_awaiting_approval",
        settled: true,
        sentence: (count) => `${count} ${count === 1 ? "payment" : "payments"} awaiting approval`,
      },
    },
  ],
  routes: (session) => (
    <>
      {/* `/affiliates` was the Models roster, and emails already sent and
          links like `?segment=applications` still mean it. */}
      <Route index element={<Onward to="/affiliates/models" />} />
      <Route path="overview" element={<Overview session={session} />} />
      <Route path="models" element={<Affiliates />} />
      {/* Before the profile route so `invite` is never read as an id. */}
      <Route path="models/invite" element={<InvitePage session={session} />} />
      <Route path="models/:id" element={<AffiliateDetail session={session} />} />
      <Route path="models/:id/portal" element={<PortalPreview />} />
      <Route path="models/:id/compensation" element={<Compensation />} />
      <Route path="models/:id/payments" element={<AffiliatePayments />} />
      <Route path="models/:id/payout-destination" element={<AffiliatePayout />} />
      <Route path="products" element={<Products session={session} />} />
      <Route path="products/:id" element={<ProductDetail session={session} />} />
      <Route path="orders" element={<Orders session={session} />} />
      {/* The approved export opens an order into its own view. */}
      <Route path="orders/:orderId" element={<OrderDetail />} />
      <Route path="payroll" element={<Payroll session={session} />} />
      <Route path="payroll/:month/approve" element={<PayrollApprove />} />
      <Route path="payments" element={<Payments session={session} />} />
      {/* One model's month, as the approved export opens it: the figure,
          where to send it, the approval and the transfers. */}
      <Route path="payments/:month/:affiliateId" element={<PaymentDetail session={session} />} />
      <Route path="payments/:month/:affiliateId/record" element={<PaymentRecord />} />
      <Route
        path="payments/:month/:affiliateId/receipts/:paymentId"
        element={<PaymentReceipt />}
      />
      <Route path="payments/:month/:affiliateId/reconcile" element={<PaymentReconcile />} />
      <Route
        path="payments/:month/:affiliateId/correction"
        element={<PaymentCorrection session={session} />}
      />
      <Route path="targets" element={<Targets session={session} />} />
    </>
  ),
  moved: [
    { from: "/affiliates", to: "/affiliates/models", exact: true },
    { from: "/affiliates/invite", to: "/affiliates/models/invite" },
    { from: "/affiliates/:id", to: "/affiliates/models/:id" },
    { from: "/products", to: "/affiliates/products" },
    { from: "/targets", to: "/affiliates/targets" },
    { from: "/payments", to: "/affiliates/payments" },
    { from: "/payroll", to: "/affiliates/payroll" },
    { from: "/orders", to: "/affiliates/orders" },
  ],
};
