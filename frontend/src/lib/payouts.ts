/**
 * Payout details, checked as they are typed.
 *
 * **The server is the authority.** `app/services/payouts.py` holds the same two
 * rules and every path to a payout row goes through it - the application, a
 * model changing where they are paid, and a maintainer correcting one. These
 * exist so somebody sees the problem while the field is still under their
 * finger, rather than after a submit that clears the form.
 *
 * They are kept deliberately trivial for that reason: eleven digits beginning
 * 01, and sixteen digits. Anything subtler would be worth writing once and
 * asking the server for, the way the password rules are.
 */

/** Just the digits. People type numbers with spaces, dashes and a +20. */
function digits(value: string): string {
  return value.replace(/\D/g, "");
}

/**
 * Why this is not a payable Egyptian mobile number, or null.
 *
 * Tolerant about how it is written and strict about what it is: `+20 106 123
 * 4567` and `01061234567` are the same number, and the first is how people
 * actually type it.
 */
export function mobileProblem(value: string, what: string): string | null {
  let only = digits(value);
  if (only.startsWith("20") && only.length === 12) only = `0${only.slice(2)}`;
  if (!only) return null; // Empty is "not finished", not "wrong".
  return /^01[0125]\d{8}$/.test(only)
    ? null
    : `${what} does not look like an Egyptian mobile number. It should be 11 digits starting 010, 011, 012 or 015.`;
}

/**
 * Why this is not a card number, or null.
 *
 * The card number rather than the account number, deliberately: Egyptian
 * account numbers vary in length by bank, so no single rule could check one
 * without refusing somebody's real account. Sixteen digits is true at every
 * bank and is what people are used to being asked for.
 */
export function cardProblem(value: string): string | null {
  const only = digits(value);
  if (!only) return null;
  return only.length === 16
    ? null
    : `A card number is 16 digits. That one has ${only.length}.`;
}

/**
 * What each payout field is called, everywhere it is called anything.
 *
 * **One map, because two disagreed.** The model's screen asked her for a
 * *card number* and the maintainer's profile showed it back as an *account
 * number* — the same column, the same digits, two different words, on two
 * screens read by two people about to move money between them. Nobody had
 * done anything wrong; there were simply two copies of this object and only
 * one of them got corrected.
 *
 * ## `bank_account_number` is a card number, and that is settled
 *
 * D06, answered 9 September 2026: *card number*. The question was put as
 * "when you send a bank transfer to a model, what do you type into the
 * banking app", and that is the answer.
 *
 * The column keeps its name because renaming it is a migration and a sweep in
 * exchange for a tidier identifier. The **label** is what a person reads, so
 * the label is what had to be right. `cardProblem` above already validated it
 * as sixteen digits and explains why an account number cannot be checked the
 * same way.
 *
 * The approved design says *account number*. It is superseded here, on
 * purpose: a label on a mockup does not change what somebody types when money
 * moves, and adopting it would either reject every real account number or
 * cost the field its only check.
 */
export const PAYOUT_FIELD_LABEL: Record<string, string> = {
  instapay_address_url: "InstaPay payment address",
  instapay_phone: "InstaPay number",
  bank_name: "Bank",
  bank_account_holder: "Account holder's name",
  bank_account_number: "Card number",
  wallet_provider: "Which wallet",
  wallet_phone: "Wallet number",
};

/** The payout methods, in their words rather than the column's. */
const METHOD_LABEL: Record<string, string> = {
  instapay: "InstaPay",
  bank: "Bank transfer",
  wallet: "Mobile wallet",
};

/**
 * Where their money goes, shortened.
 *
 * **One implementation, used by both screens that say it.** It lived on the
 * You screen alone until Payments needed it too, and the obvious move - a
 * second copy - is how the same account ends up described two different ways
 * on two tabs of the same portal.
 *
 * Shortened even to them: they supplied these, so the tail tells them nothing
 * they do not know, and a screen printing a full account number is one worth
 * photographing over their shoulder on a bus.
 */
export function describeDestination(
  destination: Record<string, string | null> | null,
): string {
  if (!destination) return "Nothing on file yet";
  /* The scheme is noise in a 210px column: `https://` is eight characters
     that identify nothing, and truncating them away leaves *https://ipn…*,
     which identifies nothing either. */
  const shown = (
    destination.instapay_address_url ??
    destination.bank_account_number ??
    destination.wallet_phone ??
    ""
  ).replace(/^https?:\/\//, "");
  return `${destinationHolder(destination)} · ${shown}`;
}

/**
 * *Orange Money*, not *Mobile wallet*.
 *
 * The export names the actual provider, and so should we: somebody sending
 * twenty transfers picks the app before they pick the number, and four
 * wallets that all read *Mobile wallet* make them open the profile to find
 * out which. `wallet_provider` and `bank_name` are already on the record and
 * are not credentials — `mask_destination` has always passed them through in
 * full.
 */
export function destinationHolder(
  destination: Record<string, string | null>,
): string {
  const method = destination.method ?? "";
  if (method === "wallet") {
    return destination.wallet_provider || METHOD_LABEL.wallet || "Wallet";
  }
  if (method === "bank") {
    return destination.bank_name || METHOD_LABEL.bank || "Bank";
  }
  return METHOD_LABEL[method] ?? method;
}

/**
 * What the *Copy* button puts on the clipboard.
 *
 * The number alone, not the sentence around it. The next thing that happens
 * to this string is being pasted into a banking app, and a paste that reads
 * *InstaPay · ipn.eg/nour* into an account-number field is a paste somebody
 * has to edit by hand — which is the step this button exists to remove.
 */
export function copyableDestination(
  destination: Record<string, string | null>,
): string {
  return (
    destination.instapay_address_url ??
    destination.bank_account_number ??
    destination.wallet_phone ??
    ""
  );
}

/**
 * The three arrangements, in the words the screens use.
 *
 * One table, because it was three: Payments, the profile and Targets each
 * carried a copy, and a copy is how *Salary plus commission* and *Salary +
 * commission* end up on two tabs of the same tool.
 */
export const PAY_TYPE: Record<string, string> = {
  commission: "Commission",
  fixed_plus_commission: "Salary + commission",
  base_guarantee: "Guaranteed minimum",
};

/**
 * The banks a model is likely to hold an account with.
 *
 * **A dropdown, with a way out.** The field was free text and collected
 * things like "cib" and "بنك مصر" and "Bank" — none of them wrong exactly,
 * and none of them the same as each other when somebody is trying to send
 * twenty transfers at month end.
 *
 * Not validated on the server, and "Another bank" is a real option: this list
 * will be out of date the first time a bank merges, and a model who cannot
 * name their own bank cannot be paid. Constraining the common case is worth
 * doing; refusing the uncommon one is not.
 */
export const EGYPTIAN_BANKS = [
  "Banque Misr",
  "National Bank of Egypt",
  "Commercial International Bank (CIB)",
  "Banque du Caire",
  "QNB Alahli",
  "Arab African International Bank",
  "Alex Bank",
  "HSBC Egypt",
  "Crédit Agricole Egypt",
  "Faisal Islamic Bank",
  "Housing and Development Bank",
  "Al Baraka Bank Egypt",
  "Attijariwafa Bank Egypt",
  "Emirates NBD Egypt",
  "Abu Dhabi Islamic Bank",
  "Suez Canal Bank",
  "Bank of Alexandria",
  "Export Development Bank of Egypt",
] as const;

/**
 * Which wallet.
 *
 * All four take the same eleven-digit Egyptian mobile number, so the number
 * alone does not say where a transfer should go — whoever sends it has been
 * guessing from the prefix, and prefixes have been portable for years.
 */
export const WALLET_PROVIDERS = [
  "Vodafone Cash",
  "Orange Money",
  "Etisalat Cash",
  "WE Pay",
] as const;

/** The option that means "not on the list". Kept in one place so both forms
 *  agree on the exact string, which is what ends up in the database. */
export const OTHER_BANK = "Another bank";

/**
 * Why this is not the name on an account, or null.
 *
 * **The field accepted sixteen digits as a name**, which is what somebody
 * does when two number fields sit next to each other and one is labelled in a
 * language they read second. The transfer then goes out addressed to a
 * number and the bank returns it.
 *
 * Mirrors `account_holder_problem` in `app/services/payouts.py`, which is the
 * authority — three paths reach the same row and only the server sees all
 * three. This exists so the problem is said while the field is still under
 * their finger.
 *
 * Deliberately not a name *format* check: Arabic and Latin both pass, one
 * name passes, a hyphen passes. The rule is only that a name has letters in
 * it, because the failure worth catching is a number in the wrong box.
 */
export function accountHolderProblem(value: string): string | null {
  const text = value.trim();
  if (!text) return null; // Empty is "not finished", not "wrong".
  const letters = text.match(/\p{L}/gu) ?? [];
  return letters.length >= 2
    ? null
    : "That does not look like a name. This is the name printed on the account, not its number.";
}
