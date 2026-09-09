import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { PAYOUT_FIELD_LABEL } from "../payouts";

/**
 * **One name for the number somebody types into a banking app.**
 *
 * D06, answered 9 September 2026: `bank_account_number` holds a **card
 * number** — the sixteen digits on the front of the card. The question was put
 * as *when you send a bank transfer to a model, what do you type*, and that is
 * the answer.
 *
 * This exists because the platform had already got it wrong, quietly, for
 * months. There were two copies of the label map. The model's screen asked her
 * for a *card number*; the maintainer's profile and the payment screen showed
 * the same digits back as an *account number*. Nobody had done anything wrong —
 * one copy was corrected and the other was not, which is what a second copy is
 * for.
 *
 * The copies are gone; `PAYOUT_FIELD_LABEL` is the only one. This is the part
 * that keeps it that way, and it checks the two things a second copy would
 * break:
 *
 * 1. The shared map still says *card number*.
 * 2. **No file says "account number" at all.** That is the phrase the approved
 *    design uses and the phrase somebody will reach for again; it is
 *    superseded, and adopting it would either reject every real Egyptian
 *    account number or cost the field the only check it has (`cardProblem`).
 *
 * Narrow on purpose, in the manner of `accent-isolation.test.ts`: it asserts
 * nothing about payout wording in general, only that this one phrase does not
 * come back.
 */

const SRC = resolve(__dirname, "..", "..");

/** Comments stripped, so this file and its neighbours may explain themselves. */
function code(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

function walk(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      found.push(...walk(path));
    } else if (/\.(ts|tsx|css)$/.test(entry)) {
      found.push(path);
    }
  }
  return found;
}

describe("the bank field is a card number, and is called one", () => {
  it("says so in the one map that names payout fields", () => {
    expect(PAYOUT_FIELD_LABEL.bank_account_number).toBe("Card number");
  });

  const files = walk(SRC).filter(
    (path) => resolve(path) !== resolve(__filename),
  );

  it.each(files.map((path) => relative(SRC, path)))(
    "%s does not call it an account number",
    (relativePath) => {
      const body = code(readFileSync(resolve(SRC, relativePath), "utf8"));

      expect(
        /account number/i.test(body),
        `${relativePath} calls the bank field an "account number". D06 settled ` +
          "that it holds a card number - the sixteen digits on the front of " +
          "the card, which is what somebody types into a banking app. Take " +
          "the label from PAYOUT_FIELD_LABEL in lib/payouts.ts.",
      ).toBe(false);
    },
  );
});
