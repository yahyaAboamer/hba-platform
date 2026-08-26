/**
 * Money on the client.
 *
 * `parseEgp` turns what somebody typed into the integer piastres that reach
 * the payment ledger. It is the one piece of logic on this side of the wire
 * where a bug is money, so it is tested the way the server's arithmetic is.
 */
import { describe, expect, it } from "vitest";

import { egpPlain, formatEgp, parseEgp } from "../money";

describe("parseEgp", () => {
  it("reads a plain figure", () => {
    expect(parseEgp("5512")).toBe(551_200);
  });

  it("reads piastres exactly", () => {
    // parseFloat("5512.35") * 100 is 551234.9999999999. Text, digit by digit,
    // is the only way this is reliably 551235 (ADR 0002).
    expect(parseEgp("5512.35")).toBe(551_235);
  });

  it("accepts what a person actually types", () => {
    expect(parseEgp("E£5,512.35")).toBe(551_235);
    expect(parseEgp(" 5 512.35 ")).toBe(551_235);
    expect(parseEgp("0.05")).toBe(5);
    expect(parseEgp(".5")).toBe(50);
    expect(parseEgp("7.")).toBe(700);
  });

  it("treats one decimal place as tenths, not hundredths", () => {
    expect(parseEgp("5512.3")).toBe(551_230);
  });

  it("refuses anything it would have to guess at", () => {
    expect(parseEgp("")).toBeNull();
    expect(parseEgp("   ")).toBeNull();
    expect(parseEgp("-")).toBeNull();
    expect(parseEgp("abc")).toBeNull();
    expect(parseEgp("5512.356")).toBeNull();
    expect(parseEgp("5,5,1,2..3")).toBeNull();
    expect(parseEgp("1e5")).toBeNull();
  });

  it("survives a round trip through the formatter", () => {
    for (const piastres of [0, 5, 100, 551_235, 1_234_567_89]) {
      expect(parseEgp(formatEgp(piastres))).toBe(piastres);
    }
  });
});

describe("egpPlain", () => {
  it("is what goes into an editable amount field", () => {
    expect(egpPlain(551_235)).toBe("5512.35");
    expect(egpPlain(551_200)).toBe("5512.00");
    expect(egpPlain(5)).toBe("0.05");
    expect(egpPlain(0)).toBe("0.00");
  });

  it("round-trips, so a pre-filled field submits the figure it was given", () => {
    for (const piastres of [0, 5, 100, 551_235, 1_234_567_89]) {
      expect(parseEgp(egpPlain(piastres))).toBe(piastres);
    }
  });
});

describe("formatEgp", () => {
  it("always shows two decimals, so a column can be scanned", () => {
    expect(formatEgp(551_200)).toBe("E£5,512.00");
    expect(formatEgp(5)).toBe("E£0.05");
  });
});
