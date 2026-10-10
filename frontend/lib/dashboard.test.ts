import { describe, expect, it } from "vitest";

import { cfoNotScoredText, fairValueUnavailableText, stepPill } from "@/lib/dashboard";

describe("stepPill", () => {
  it("draws the stored verdict with the existing labels and tones", () => {
    expect(stepPill(82, "Pass")).toEqual({ tone: "positive", label: "Pass", score: 82 });
    expect(stepPill(95, "Strong Pass")).toEqual({ tone: "strong", label: "Strong pass", score: 95 });
  });

  it("a stored Fail reads 'May not pass' in the slate tone, at any score", () => {
    expect(stepPill(55, "Fail")).toEqual({ tone: "not-pass", label: "May not pass", score: 55 });
    expect(stepPill(88, "Fail").tone).toBe("not-pass");
  });

  it("the Debt step's caution reads 'Pass, ratio in breach'; only Debt relabels it", () => {
    expect(stepPill(72, "Pass with caution", "debt")).toEqual({ tone: "caution", label: "Pass, ratio in breach", score: 72 });
    expect(stepPill(72, "Pass with caution").label).toBe("Pass with caution");
  });

  it("a missing score, a missing verdict, insufficient_data and not_supported are the neutral 'Not scored'", () => {
    const notScored = { tone: "neutral", label: "Not scored", score: null };
    expect(stepPill(null, null)).toEqual(notScored);
    expect(stepPill(undefined, "Pass")).toEqual(notScored);
    expect(stepPill(60, null)).toEqual(notScored);
    expect(stepPill(null, "insufficient_data")).toEqual(notScored);
    expect(stepPill(70, "insufficient_data")).toEqual(notScored);
    expect(stepPill(null, "not_supported", "debt")).toEqual(notScored);
  });
});

describe("text helpers", () => {
  it("names the Step 1 types whose CFO is not scored", () => {
    expect(cfoNotScoredText("Bank")).toBe("Not scored for a bank: revenue and net income only");
    expect(cfoNotScoredText("Property Developer")).toBe("Not scored for a REIT or property developer: revenue and net income only");
    expect(cfoNotScoredText(null)).toBeNull();
  });

  it("says why there is no fair value in plain words", () => {
    expect(fairValueUnavailableText({ unavailable_reason: "pass_method", unavailable_detail: "Losses and no P/B route." })).toBe(
      "no valuation method applies (Losses and no P/B route)",
    );
    expect(fairValueUnavailableText({ unavailable_reason: "pass_method", unavailable_detail: null })).toBe("no valuation method applies to this company");
    expect(fairValueUnavailableText({ unavailable_reason: "insufficient_data", unavailable_detail: null })).toContain("not enough cached history");
    expect(fairValueUnavailableText({ unavailable_reason: "no_price", unavailable_detail: null })).toContain("no price");
    expect(fairValueUnavailableText({ unavailable_reason: "not_scored", unavailable_detail: null })).toContain("not been scored");
  });
});
