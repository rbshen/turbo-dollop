import { describe, expect, it } from "vitest";

import { technicalCardScope } from "@/lib/technicalCardScope";

describe("technicalCardScope", () => {
  it("shows Bullish Reversal in full during a downtrend, collapsing Pullback Recovery", () => {
    const scope = technicalCardScope("downtrend");
    expect(scope.fullCard).toBe("reversal");
    expect(scope.collapsedLabel).toBe("Pullback recovery");
    expect(scope.collapsedSubline).toMatch(/uptrend/);
    expect(scope.collapsedSubline).toMatch(/currently in a downtrend/);
  });

  it("shows Pullback Recovery in full during an uptrend, collapsing Bullish Reversal", () => {
    const scope = technicalCardScope("uptrend");
    expect(scope.fullCard).toBe("continuation");
    expect(scope.collapsedLabel).toBe("Bullish reversal");
    expect(scope.collapsedSubline).toMatch(/downtrend/);
    expect(scope.collapsedSubline).toMatch(/currently in an uptrend/);
  });
});
