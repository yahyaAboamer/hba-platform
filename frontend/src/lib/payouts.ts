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
