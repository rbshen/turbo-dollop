import { describe, expect, it } from "vitest";

import {
  ERROR_ROW,
  HINT_ROW,
  PAIR_WIDTH,
  SIDEBAR_CONTENT_WIDTH,
  fundamentalSectionHeight,
  rangeFieldHeight,
  rangeGridHeight,
} from "./screenerSidebarMetrics";

describe("screener sidebar metrics (boxed)", () => {
  it("computes one field and the nine-field grid", () => {
    expect(rangeFieldHeight()).toBe(55);
    expect(rangeGridHeight()).toBe(591);
  });

  it("adds one hint row for the market-cap hint, and one row per error line", () => {
    expect(HINT_ROW).toBe(19);
    expect(ERROR_ROW).toBe(19);
    expect(rangeGridHeight(true)).toBe(610);
  });

  it("computes the whole Fundamental card, with and without the hint", () => {
    expect(fundamentalSectionHeight()).toBe(883);
    expect(fundamentalSectionHeight(true)).toBe(902);
  });

  it("fits a pair inside the 222px card content", () => {
    expect(SIDEBAR_CONTENT_WIDTH).toBe(222);
    expect(PAIR_WIDTH).toBeLessThanOrEqual(SIDEBAR_CONTENT_WIDTH);
  });
});
