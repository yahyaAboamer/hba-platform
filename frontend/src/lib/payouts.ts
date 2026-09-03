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
  const method = destination.method ?? "";
  const shown =
    destination.instapay_address_url ??
    destination.bank_account_number ??
    destination.wallet_phone ??
    "";
  return `${METHOD_LABEL[method] ?? method} · ${shown}`;
}

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
