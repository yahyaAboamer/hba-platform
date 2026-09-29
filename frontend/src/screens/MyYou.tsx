import { useState } from "react";
import { Link } from "react-router-dom";

import { signOutAndLeave } from "../lib/api";
import { formatMonth } from "../lib/money";
import { PAY_TYPE, describeDestination } from "../lib/payouts";
import { storeTheme } from "../lib/theme";
import type { Theme } from "../lib/theme";
import { Measurements, Notifications, Reveal, ShippingAddress } from "./MyDetails";
import type { Me } from "./MyDetails";
import { MyPayout } from "./MyPayout";
import "./MyYou.css";

/** The arrangement is for the server's working month, not the last month
 * opened on Home. Rates and amounts remain on their month page. */
const ARRANGEMENT_NOTE: Record<string, string> = {
  commission: "You earn a share of eligible sales attributed to your code.",
  fixed_plus_commission: "You receive both your monthly fixed amount and a share of eligible code sales.",
  base_guarantee: "You receive the larger of your commission or your guaranteed minimum when content targets are met and confirmed.",
};

const ARRANGEMENT_DETAIL: Record<string, string> = {
  commission: "Your pay comes from eligible sales attributed to your code. Your exact rate and amount are shown in the month's calculation.",
  fixed_plus_commission: "Your fixed amount and your commission are added together. Neither replaces the other. The exact amounts are shown in the month's calculation.",
  base_guarantee: "The guaranteed minimum is a floor, not an extra amount added to commission. It applies when your content targets for the month were met and HBA confirmed them. You receive whichever is larger: the minimum or your commission.",
};

type IconName = "payment" | "history" | "contact" | "sizes" | "notifications" | "help" | "appearance";

function YouIcon({ name }: { name: IconName }) {
  const paths = {
    payment: <><rect x="3" y="6" width="18" height="12" rx="2" /><path d="M3 10h18M7 14h4" /></>,
    history: <><path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3Z" /><path d="M9 8h6M9 12h6" /></>,
    contact: <><path d="M4 10.5 12 4l8 6.5V20H4v-9.5Z" /><path d="M9 20v-6h6v6" /></>,
    sizes: <><path d="M6 4v16M6 4h12v16H6M6 9h4M6 14h4M14 4v5M14 14v6" /></>,
    notifications: <><path d="M5 17h14l-2-3V9a5 5 0 0 0-10 0v5l-2 3Z" /><path d="M10 20h4" /></>,
    help: <><circle cx="12" cy="12" r="9" /><path d="M9.6 9a2.5 2.5 0 1 1 4.2 2c-1.2.9-1.8 1.4-1.8 2.6M12 17h.01" /></>,
    appearance: <><circle cx="12" cy="12" r="9" /><path d="M12 3a9 9 0 0 1 0 18Z" /></>,
  };
  return <span className="you__row-icon" aria-hidden="true"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg></span>;
}

function AccountRow({ to, icon, label, hint }: { to: string; icon: IconName; label: string; hint: string }) {
  return <Link className="you__row" to={to}>
    <YouIcon name={icon} />
    <span className="you__row-copy"><span className="you__row-label">{label}</span><span className="you__hint">{hint}</span></span>
    <span className="you__go" aria-hidden="true">›</span>
  </Link>;
}

export function MyYou({ me, workingMonth, theme, onTheme }: {
  me: Me; workingMonth: string | null; theme: Theme; onTheme: (theme: Theme) => void;
}) {
  const arrangement = me.arrangement ? PAY_TYPE[me.arrangement] ?? me.arrangement : "Not set yet";
  const paymentHint = me.payout_abroad && !me.payout_destination
    ? "HBA arranges your payment directly"
    : me.payout_destination ? describeDestination(me.payout_destination) : "Add a payment method";
  const addressHint = me.shipping.shipping_line1
    ? [me.shipping.shipping_city, "Delivery address on file"].filter(Boolean).join(" · ")
    : "Add an address for parcels";

  let attention: { title: string; text: string; to?: string; action?: string } | null = null;
  if (!me.arrangement) attention = {
    title: "Your terms need HBA",
    text: "HBA has not recorded your terms for this working month. Ask your contact at HBA to set them; you cannot change them here.",
  };
  else if (!me.payout_destination && !me.payout_abroad) attention = {
    title: "Add where you are paid", text: "HBA needs a payment method for future transfers.", to: "/you/payout", action: "Add payment method",
  };
  else if (!me.shipping.shipping_line1) attention = {
    title: "Add your delivery address", text: "HBA needs an address to send you products.", to: "/you/details", action: "Add address",
  };

  function pick(next: Theme) { storeTheme(next); onTheme(next); }

  return <div className="you">
    <header className="you__hero">
      <span className="you__avatar" aria-hidden="true">{me.name.trim().charAt(0).toUpperCase() || "·"}</span>
      <span className="you__who"><h1 className="you__name">{me.name}</h1><span className="you__since">HBA ambassador{me.since ? ` since ${formatMonth(me.since)}` : ""}</span></span>
      <span className={`you__status${me.state === "paused" ? " you__status--paused" : ""}`}>{me.state === "paused" ? "Paused" : "Active"}</span>
    </header>

    {attention && <aside className="you__attention" aria-label="Account attention">
      <strong>{attention.title}</strong><p>{attention.text}</p>
      {attention.to && <Link to={attention.to}>{attention.action} →</Link>}
    </aside>}

    <div className="you__sections">
      <section className="you__section you__section--terms">
        <h2 className="you__section-title">Your terms{workingMonth ? ` · ${formatMonth(workingMonth)}` : ""}</h2>
        <div className="you__card you__terms-card">
          <div className="you__terms-top"><span>Current arrangement</span>{me.arrangement && <span>Set by HBA</span>}</div>
          <h3>{arrangement}</h3>
          <p>{me.arrangement ? ARRANGEMENT_NOTE[me.arrangement] ?? "HBA set these terms." : "A month cannot be worked out until HBA records your terms."}</p>
          <Link className="you__text-link" to="/you/terms">Understand these terms →</Link>
        </div>
      </section>

      <section className="you__section you__section--payments">
        <h2 className="you__section-title">Payments</h2>
        <nav className="you__rows" aria-label="Payments">
          <AccountRow to="/you/payout" icon="payment" label="Where you are paid" hint={paymentHint} />
          <AccountRow to="/payments" icon="history" label="Payment history" hint="Transfers, receipts and past months" />
        </nav>
      </section>

      <section className="you__section you__section--details">
        <h2 className="you__section-title">Your details</h2>
        <nav className="you__rows" aria-label="Your details">
          <AccountRow to="/you/details" icon="contact" label="Contact & delivery" hint={addressHint} />
          <AccountRow to="/you/sizes" icon="sizes" label="Height & weight" hint="Optional · used to send the right size" />
        </nav>
      </section>

      <section className="you__section you__section--preferences">
        <h2 className="you__section-title">Preferences & help</h2>
        <div className="you__rows">
          <AccountRow to="/you/notifications" icon="notifications" label="Notifications" hint="Month closed and payment emails" />
          <div className="you__row you__row--appearance">
            <YouIcon name="appearance" /><span className="you__row-copy"><span className="you__row-label">Appearance</span><span className="you__hint">Choose how the portal looks</span></span>
            <fieldset className="you__theme"><legend className="sr-only">Appearance</legend>
              {(["dark", "light"] as Theme[]).map((option) => <label key={option} className="you__theme-option"><input type="radio" name="portal-theme" checked={theme === option} onChange={() => pick(option)} /><span>{option === "dark" ? "Dark" : "Light"}</span></label>)}
            </fieldset>
          </div>
          <AccountRow to="/you/guide" icon="help" label="Dashboard guide" hint="Sales, pay and timing explained" />
        </div>
      </section>
    </div>
    <SignOut />
  </div>;
}

function SignOut() {
  const [asking, setAsking] = useState(false);
  if (!asking) return <button type="button" className="you__signout" onClick={() => setAsking(true)}>Sign out</button>;
  return <div className="you__confirm"><strong>Sign out of the HBA dashboard?</strong><p>You can return by signing in again.</p><div className="you__confirm-actions">
    <button type="button" className="you__stay" onClick={() => setAsking(false)}>Stay signed in</button>
    <button type="button" className="you__leave" onClick={signOutAndLeave}>Sign out</button>
  </div></div>;
}

export function YouTerms({ me, workingMonth }: { me: Me; workingMonth: string | null }) {
  return <div className="you__detail">
    <div className="you__section-title">Working month{workingMonth ? ` · ${formatMonth(workingMonth)}` : ""}</div>
    <section className="you__detail-card">
      <span className="you__eyebrow">Your arrangement · set by HBA</span>
      <h1>{me.arrangement ? PAY_TYPE[me.arrangement] ?? me.arrangement : "Not set yet"}</h1>
      <p>{me.arrangement ? ARRANGEMENT_DETAIL[me.arrangement] ?? "HBA set these terms." : "HBA has not recorded your terms for this working month. Ask your contact at HBA to set them. No rate is assumed."}</p>
      <p className="you__detail-note">Terms can differ in another month. The figure for each month is on that month's calculation, not this account page.</p>
      {workingMonth && <Link className="you__text-link" to={`/earnings?month=${workingMonth}`}>See this month's calculation →</Link>}
    </section>
    {me.arrangement === "base_guarantee" && <section className="you__detail-card"><h2>When does the minimum apply?</h2><p>HBA must record and confirm that your content targets were met. Until then, the guarantee is not an amount you have been promised for that month.</p><Link className="you__text-link" to="/targets">See your targets →</Link></section>}
  </div>;
}

export function YouPayout({ me, onChanged }: { me: Me; onChanged: () => void | Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  if (editing) return <div className="you__detail you__detail--form"><MyPayout current={me.payout_destination} required={me.required_fields} onChanged={async () => {
    await onChanged(); setEditing(false); setSaved(true);
  }} onCancel={() => setEditing(false)} /></div>;

  const abroad = me.payout_abroad && !me.payout_destination;
  const missing = !me.payout_destination && !abroad;
  return <div className="you__detail">
    {saved && <p className="notice notice--settled" role="status">Payment details saved. This is where future payments will be sent.</p>}
    <div className="you__section-title">Your current payment method</div>
    <section className="you__detail-card">
      <h1>{abroad ? "HBA arranges your payment directly" : missing ? "No payment method on file" : describeDestination(me.payout_destination)}</h1>
      <p>{abroad ? "HBA is arranging how to pay you outside Egypt. If you now have an Egyptian payment method, you can add it here." : missing ? "Add where HBA should send future payments." : "These details are shortened until you choose to see them in full."}</p>
      {me.payout_destination && <Reveal />}
    </section>
    <section className="you__detail-card"><h2>{missing || abroad ? "Add a payment method" : "Change where you are paid"}</h2>
      <p>Choose the method, check the old and new details, then confirm with your password. HBA is alerted when a current method changes.</p>
      <button type="button" className="you__primary" onClick={() => { setSaved(false); setEditing(true); }}>{missing || abroad ? "Add payment method" : "Change payment method"}</button>
    </section>
    <section className="you__detail-card"><h2>Past payments stay accurate</h2><p>Payment history keeps the destination recorded when each transfer was sent, even if you change your current method.</p><Link className="you__text-link" to="/payments">View payment history →</Link></section>
  </div>;
}

export function YouDetails({ me, onChanged }: { me: Me; onChanged: () => void }) {
  const [saved, setSaved] = useState(false);
  return <div className="you__detail">
    {saved && <p className="notice notice--settled" role="status">Delivery address updated.</p>}
    <div className="you__section-title">How we contact you</div>
    <section className="you__detail-card"><h1>Personal details</h1><dl className="you__facts">
      <div><dt>Name</dt><dd>{me.name}</dd></div>
      <div><dt>You sign in with</dt><dd>{me.email}</dd></div>
      <div><dt>Contact phone</dt><dd>{me.phone || "Not on file"}</dd></div>
    </dl><p className="you__detail-note">Your sign-in address is shown for reference and cannot be changed here.</p></section>
    <div className="you__section-title">Where we send products</div>
    <ShippingAddress me={me} onChanged={() => { setSaved(true); onChanged(); }} />
    <p className="you__detail-foot">You and HBA staff can correct the parcel address. Your optional height and weight are edited only by you.</p>
  </div>;
}

export function YouSizes({ me, onChanged }: { me: Me; onChanged: () => void }) {
  const [saved, setSaved] = useState(false);
  return <div className="you__detail">
    {saved && <p className="notice notice--settled" role="status">Measurements updated.</p>}
    <div className="you__section-title">Optional measurements</div>
    <Measurements me={me} onChanged={() => { setSaved(true); onChanged(); }} />
    <section className="you__detail-card"><h2>You are in control</h2><p>You can change or remove either measurement later. HBA uses them to send products that fit.</p></section>
  </div>;
}

export function YouNotifications() { return <div className="you__detail you__notifications"><div className="you__section-title">Messages you can choose</div><Notifications /></div>; }

export function YouGuide() {
  return <div className="you__detail you__guide">
    <p className="you__guide-intro">A few answers for the parts of the dashboard that can be easy to misread.</p>
    <section className="you__detail-card"><h1>Why can sales and pay differ?</h1><p>Sales describe orders attributed to your code. Your pay follows the terms HBA set for that month, which may include commission, a fixed amount, or a guaranteed minimum. An open month's figure can still change.</p><Link className="you__text-link" to="/">See your current month →</Link></section>
    <section className="you__detail-card"><h2>When is a month final?</h2><p>While a month is in progress, its amount is still adding up. HBA later approves the month and its agreed amount stays fixed. If something changes after approval, you will see a separate correction.</p><Link className="you__text-link" to="/payments">See payment history →</Link></section>
    <section className="you__detail-card"><h2>Where can I check a transfer?</h2><p>Payment history shows when HBA recorded it, where it was sent at the time, and a transfer screenshot when one is attached. An open month is separate from money already agreed and owed.</p><Link className="you__text-link" to="/payments">Open payment history →</Link></section>
    <section className="you__detail-card"><h2>What if a target has no result yet?</h2><p>It means no result has been recorded. It does not mean you missed the target. The Targets tab shows what HBA has recorded and when it was confirmed.</p><Link className="you__text-link" to="/targets">Open Targets →</Link></section>
  </div>;
}

export function YouSkeleton() {
  return <div className="you you--skeleton" aria-label="Loading your account" role="status">
    <div className="you__hero"><span className="you__avatar you__placeholder" /><span className="you__who"><span className="you__placeholder you__placeholder--name" /><span className="you__placeholder you__placeholder--sub" /></span></div>
    <div className="you__sections">{[1, 2, 3, 4].map((item) => <section className="you__section" key={item}><span className="you__placeholder you__placeholder--label" /><div className="you__card"><span className="you__placeholder you__placeholder--line" /><span className="you__placeholder you__placeholder--sub" /><span className="you__placeholder you__placeholder--line" /></div></section>)}</div>
  </div>;
}
