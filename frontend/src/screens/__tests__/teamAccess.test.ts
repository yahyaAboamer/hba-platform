import { describe, expect, it } from "vitest";

import { NOT_GIVEN, PERMISSION_PHRASE, givesSentence } from "../settings/teamAccess";
import { ALL, ROLE_PERMISSIONS } from "./teamFixture";

// The fixture is the server's own `ROLES` (app/core/permissions.py, this batch).
describe("What this gives", () => {
  it("has a phrase for every permission any role grants", () => {
    const granted = new Set(Object.values(ROLE_PERMISSIONS).flat());
    for (const permission of granted) expect(PERMISSION_PHRASE[permission], permission).toBeTruthy();
    // ...and for every permission that exists, so a new role needs no new words.
    for (const permission of ALL) expect(PERMISSION_PHRASE[permission], permission).toBeTruthy();
    // No phrase for a permission the server does not know.
    for (const permission of Object.keys(PERMISSION_PHRASE)) expect(ALL).toContain(permission);
  });

  it("never lets one phrase hide inside another", () => {
    const phrases = Object.values(PERMISSION_PHRASE);
    for (const a of phrases) for (const b of phrases) if (a !== b) expect(b.includes(a), `${a} / ${b}`).toBe(false);
  });

  for (const role of ["affiliate_manager", "content_manager", "operations_manager", "customer_service"]) {
    it(`names exactly what ${role} is granted, and what it is not`, () => {
      const sentence = givesSentence("Mona", [role], ROLE_PERMISSIONS);
      const held = ROLE_PERMISSIONS[role];
      for (const [permission, phrase] of Object.entries(PERMISSION_PHRASE)) {
        expect(sentence.includes(phrase), `${role} / ${permission}`).toBe(held.includes(permission));
      }
      for (const [words, permissions] of NOT_GIVEN) {
        const said = sentence.toLowerCase().includes(words.toLowerCase());
        expect(said, `${role} / ${words}`).toBe(!permissions.some((permission) => held.includes(permission)));
      }
    });
  }

  it("reads two levels together as everything they grant", () => {
    const sentence = givesSentence("Dina", ["affiliate_manager", "customer_service"], ROLE_PERMISSIONS);
    expect(sentence).toContain("approving a month's pay");
    expect(sentence).toContain("reading and replying to customers");
    expect(sentence).toContain("building the Khazenly confirmation file");
    expect(sentence).not.toContain("recording payments");
  });

  it("says plainly when there is nothing, and calls the owner the owner", () => {
    expect(givesSentence("Mona", [], ROLE_PERMISSIONS)).toBe("Mona has no access to any department.");
    expect(givesSentence("Yahya", ["admin"], ROLE_PERMISSIONS)).toBe("Yahya is the owner: every department, Settings and money.");
  });
});
