import { describe, expect, it } from "vitest";

import { fractionToPercentText, percentToFraction } from "@/lib/percentFraction";

describe("fractionToPercentText", () => {
  it.each([
    [0.03608, "3.608"],
    [0.02728, "2.728"],
    [0.036085, "3.6085"],
    [0.05, "5"],
    [0, "0"],
    [-0.01, "-1"],
  ])("shows %j as %j, at full precision with no float noise", (fraction, text) => {
    expect(fractionToPercentText(fraction)).toBe(text);
  });

  it("does not round to three decimals", () => {
    expect(fractionToPercentText(0.0361234)).toBe("3.61234");
  });

  it("never produces exponent notation, which the number field would reject", () => {
    for (const f of [1e-9, 1.5e-10]) {
      expect(fractionToPercentText(f)).not.toMatch(/e/);
    }
  });
});

describe("percentToFraction", () => {
  it.each([
    ["3.608", 0.03608],
    ["2.728", 0.02728],
    ["3.6085", 0.036085],
    ["5", 0.05],
  ])("converts %j to exactly %j", (text, fraction) => {
    expect(percentToFraction(Number(text))).toBe(fraction);
  });

  it("round-trips the stored values exactly, unlike the old toFixed(3)/100 path", () => {
    for (const stored of [0.03608, 0.02728, 0.036085]) {
      expect(percentToFraction(Number(fractionToPercentText(stored)))).toBe(stored);
    }
    // the old path, for the record: 0.02728 came back as 0.027280000000000002
    expect(parseFloat((0.02728 * 100).toFixed(3)) / 100).not.toBe(0.02728);
  });
});
