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
