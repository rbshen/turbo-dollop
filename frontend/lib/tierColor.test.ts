import { describe, expect, it } from "vitest";

import { pillLabel, toneFor, toneForNullable, verdictLabel } from "@/lib/tierColor";

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
    expect(toneFor(95, "Fail")).toBe("negative");
    expect(toneFor(74, "Pass with caution")).toBe("caution");
  });

  it("tiers a plain Pass by score", () => {
    expect(toneFor(91, "Strong Pass")).toBe("strong");
    expect(toneFor(90, "Pass")).toBe("positive");
    expect(toneFor(75, "Pass")).toBe("positive");
    expect(toneFor(74, "Pass")).toBe("warn");
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
    expect(verdictLabel("Fail")).toBe("Fail");
  });

  it("nothing is neutral while there is a score; no score is neutral", () => {
    for (const score of [70, 74, 75, 90, 91, 100]) expect(toneFor(score, "Pass")).not.toBe("neutral");
    expect(toneForNullable(null, "Fail")).toBe("neutral");
  });
});
