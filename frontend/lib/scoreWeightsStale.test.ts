import { describe, expect, it } from "vitest";

import { staleWeightsCount, staleWeightsMessage } from "@/lib/scoreWeightsStale";

describe("staleWeightsCount", () => {
  const rows = [{ weights_version: 1 }, { weights_version: 2 }, { weights_version: null }, {}, { weights_version: 3 }];
  it("counts rows scored with a version older than the current one", () => {
    expect(staleWeightsCount(rows, 3)).toBe(2);
    expect(staleWeightsCount(rows, 2)).toBe(1);
  });
  it("never counts a row with no version (scored before weights were adjustable) or a current one", () => {
    expect(staleWeightsCount(rows, 1)).toBe(0);
  });
  it("is 0 until both the rows and the current version are known", () => {
    expect(staleWeightsCount(undefined, 3)).toBe(0);
    expect(staleWeightsCount(rows, undefined)).toBe(0);
  });
});

describe("staleWeightsMessage", () => {
  it("says N scores, and 1 score for one", () => {
    expect(staleWeightsMessage(46)).toBe("46 scores are still on the previous weights");
    expect(staleWeightsMessage(1)).toBe("1 score is still on the previous weights");
  });
});
