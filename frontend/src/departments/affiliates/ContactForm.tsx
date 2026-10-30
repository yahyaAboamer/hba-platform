import { useState } from "react";

import { api } from "../lib/api";
import "./ContactForm.css";

export type ContactShipping = {
  shipping_name: string | null;
  shipping_phone: string | null;
  shipping_line1: string | null;
  shipping_line2: string | null;
  shipping_city: string | null;
  shipping_governorate: string | null;
  shipping_notes: string | null;
};

type Contact = {
  id: number;
  name: string;
  phone: string | null;
  /** Her sign-in. Shown, never edited here. */
  email: string | null;
  shipping: ContactShipping;
};

/** The export's five slots (`mFields`), with *Email* as D07's *Signs in with*. */
const MAIN: [keyof ContactShipping, string][] = [
  ["shipping_line1", "Shipping address"],
  ["shipping_city", "City"],
];

/** What the courier also needs, which the export's two address slots cannot hold (D11). */
const MORE: [keyof ContactShipping, string][] = [
  ["shipping_line2", "Flat, floor (optional)"],
  ["shipping_governorate", "Governorate"],
  ["shipping_name", "Name on the parcel"],
  ["shipping_phone", "Phone on the parcel"],
  ["shipping_notes", "Anything the courier needs"],
];

const blank = (value: string | null | undefined) => value ?? "";

/**
 * *Contact and shipping* - the export's editable card (`mFields`,
 * `saveProfile`, Admin lines 871-881).
 *
 * **Contact details are not her sign-in.** The export's *Email* field is her
 * login here (`update_details`: the account she signs in with moves), so it is
 * shown as *Signs in with* (D07) and is not an input: a contact edit must not
 * be able to move somebody's login. Name, phone and address are hers to have
 * corrected by staff (D11); her measurements are hers alone (A05) and are not
 * here.
 *
 * One request for the whole card, and the server applies it in one
 * transaction: a refused parcel phone saves nothing, not the name without it.
 * Only fields that changed are sent. A refusal keeps everything typed.
 */
export function ContactForm({ contact, canEdit, onSaved }: {
  contact: Contact;
  canEdit: boolean;
  onSaved: () => void;
}) {
  const [name, setName] = useState(contact.name);
  const [phone, setPhone] = useState(blank(contact.phone));
  const [shipping, setShipping] = useState<Record<string, string>>(
    Object.fromEntries([...MAIN, ...MORE].map(([key]) => [key, blank(contact.shipping[key])])),
  );
  const [moreOpen, setMoreOpen] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const changedShipping = Object.fromEntries(
    Object.entries(shipping).filter(([key, value]) =>
      value.trim() !== blank(contact.shipping[key as keyof ContactShipping]).trim()),
  );
  const nameChanged = name.trim() !== contact.name;
  const phoneChanged = phone.trim() !== blank(contact.phone).trim();
  const dirty = nameChanged || phoneChanged || Object.keys(changedShipping).length > 0;

  function edit<T>(set: (value: T) => void) {
    return (value: T) => {
      set(value);
      setSaved(false);
      setError(null);
    };
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) {
      setError("A name is needed. Nothing was saved.");
      return;
    }
    if (!dirty) {
      setSaved(true);
      return;
    }
    setWorking(true);
    setError(null);
    try {
      await api.patch(`/api/affiliates/${contact.id}`, {
        ...(nameChanged ? { name: name.trim() } : {}),
        ...(phoneChanged ? { phone: phone.trim() } : {}),
        ...(Object.keys(changedShipping).length ? { shipping: changedShipping } : {}),
      });
      setSaved(true);
      onSaved();
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Could not save.";
      setError(/nothing (was )?saved/i.test(message) ? message : `${message} Nothing was saved.`);
    } finally {
      setWorking(false);
    }
  }

  const field = (label: string, value: string, onChange: (v: string) => void, key: string) => (
    <label className="contact-form__field" key={key}>
      <span className="contact-form__label">{label}</span>
      {canEdit ? (
        <input className="contact-form__input" type="text" value={value}
          onChange={(e) => onChange(e.target.value)} />
      ) : (
        <span className="contact-form__value">{value || "Not given"}</span>
      )}
    </label>
  );

  return (
    <form className="contact-form" onSubmit={save} noValidate>
      {field("Full name", name, edit(setName), "name")}
      <div className="contact-form__field">
        <span className="contact-form__label">Signs in with</span>
        <span className="contact-form__value">{contact.email ?? "—"}</span>
        <span className="contact-form__note">
          Her sign-in, not a contact detail - it is not changed from this form.
        </span>
      </div>
      {field("Phone", phone, edit(setPhone), "phone")}
      {MAIN.map(([key, label]) =>
        field(label, shipping[key], edit((v: string) => setShipping((s) => ({ ...s, [key]: v }))), key))}
      <button type="button" className="contact-form__more" aria-expanded={moreOpen}
        onClick={() => setMoreOpen(!moreOpen)}>
        {moreOpen ? "Fewer address details" : "More address details"}
      </button>
      {moreOpen && MORE.map(([key, label]) =>
        field(label, shipping[key], edit((v: string) => setShipping((s) => ({ ...s, [key]: v }))), key))}
      {error && <p className="contact-form__error" role="alert">{error}</p>}
      {canEdit && (
        <button type="submit" className="contact-form__save" disabled={working}>
          {working ? "Saving…" : saved ? "Saved" : "Save details"}
        </button>
      )}
    </form>
  );
}
