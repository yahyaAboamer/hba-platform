import { describe, expect, it } from "vitest";

import { extractInstapayLink, instapayProblem } from "../Apply";

/*
 * Owner, 6 Nov 2026: InstaPay's share copies a sentence around the link and
 * models paste all of it. The form must accept that message (the server keeps
 * the link alone, `extract_instapay_link`), not tell the model to edit it.
 */
const LINK = "https://ipn.eg/S/nour.mahmoud/instapay/8Xk2Qp";

describe("a pasted InstaPay message", () => {
  it.each([
    `Send money to me via InstaPay: ${LINK}`,
    `Send money to me via InstaPay: ${LINK}.`,
    `حول لي على انستاباي ${LINK} شكرا`,
    `${LINK} (InstaPay)`,
  ])("is accepted, and its link found: %s", (pasted) => {
    expect(instapayProblem(pasted)).toBeNull();
    expect(extractInstapayLink(pasted)).toBe(LINK);
  });

  it("still refuses a link to somewhere else, even one mentioning ipn.eg", () => {
    expect(instapayProblem("https://facebook.com/?x=ipn.eg")).toMatch(/points at facebook\.com/);
    expect(instapayProblem("https://evil.example/ipn.eg/S/nour")).toMatch(/points at evil\.example/);
  });

  it("still names a phone number pasted in the link field", () => {
    expect(instapayProblem("01001234567")).toMatch(/phone number/);
  });
});
