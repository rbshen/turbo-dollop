import { describe, expect, it } from "vitest";

import { pillLabel, toneFor, toneForNullable, verdictDisplay, verdictLabel } from "@/lib/tierColor";

describe("pillLabel", () => {
  it.each([
    ["Strong Pass", "Strong pass"],
    ["Pass", "Pass"],
    ["Pass with caution", "Pass with caution"],
    ["Wide Moat", "Wide moat"],
    ["Speculative Growth", "Speculative growth"],
    ["Growth Rate · 25% · 92", "Growth rate · 25% · 92"],
    ["Economic Moat · N/A", "Economic moat · N/A"],
    ["Stage 2 · Advance", "Stage 2 · Advance"],
    ["5Y vs SPY", "5Y vs SPY"],
    ["S&P 500 · Nasdaq · Dow 30", "S&P 500 · Nasdaq · Dow 30"],
    ["Fairvalued", "Fairvalued"],
    ["Common Stock", "Common stock"],
    ["restricted by FMP", "Restricted by FMP"],
  ])("%s -> %s", (input, expected) => {
    expect(pillLabel(input)).toBe(expected);
  });
});

describe("toneFor", () => {
  it("checks Fail and Pass with caution before the score tiers", () => {
    expect(toneFor(95, "Fail")).toBe("not-pass");
    expect(toneFor(74, "Pass with caution")).toBe("caution");
  });

  it("tiers a plain Pass by score", () => {
    expect(toneFor(91, "Strong Pass")).toBe("strong");
    expect(toneFor(90, "Pass")).toBe("positive");
    expect(toneFor(75, "Pass")).toBe("positive");
    expect(toneFor(74, "Pass")).toBe("positive");
    expect(toneFor(72, "Pass")).toBe("positive");
    expect(toneFor(70, "Pass")).toBe("positive");
  });

  it("draws Fail in the slate not-pass tone at every score, and never in amber for a plain Pass", () => {
    for (const score of [0, 48, 69, 70, 100]) expect(toneFor(score, "Fail")).toBe("not-pass");
    // Any score under 70 resolves to the same tone whatever the verdict text says.
    for (const verdict of ["Pass", "Strong Pass", "", "insufficient_data"]) expect(toneFor(69, verdict)).toBe("not-pass");
    for (const score of [0, 1, 50, 69]) expect(toneForNullable(score, null)).toBe("not-pass");
    expect(toneFor(72, "Pass")).toBe("positive");
    for (const score of [70, 72, 74, 75, 90]) expect(toneFor(score, "Pass")).not.toMatch(/warn|caution/);
  });

  it("is neutral without a score", () => {
    expect(toneForNullable(null, "Pass")).toBe("neutral");
    expect(toneForNullable(80, null)).toBe("positive");
  });
});

describe("verdictLabel", () => {
  it("is pillLabel for every verdict (the moat_not_rated key was retired 2026-10-07)", () => {
    expect(verdictLabel("Strong Pass")).toBe("Strong pass");
    expect(verdictLabel("Pass with caution")).toBe("Pass with caution");
    expect(verdictLabel("Fail")).toBe("May not pass");
  });

  it("nothing is neutral while there is a score; no score is neutral", () => {
    for (const score of [70, 74, 75, 90, 91, 100]) expect(toneFor(score, "Pass")).not.toBe("neutral");
    expect(toneForNullable(null, "Fail")).toBe("neutral");
  });
});

describe("verdictDisplay", () => {
  it("reads the stored Fail key as May not pass and sentence-cases everything else", () => {
    expect(verdictDisplay("Fail")).toBe("May not pass");
    expect(verdictDisplay("Strong Pass")).toBe("Strong pass");
    expect(verdictDisplay("Pass")).toBe("Pass");
    expect(verdictDisplay("Pass with caution")).toBe("Pass with caution");
  });

  it("is display only: the raw Fail still drives the tone", () => {
    const stored = "Fail";
    expect(verdictDisplay(stored)).not.toBe(stored);
    expect(toneFor(48, stored)).toBe("not-pass");
    expect(toneForNullable(48, stored)).toBe("not-pass");
  });
});
