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
  it("computes one field and the eight-field grid (Overall is a multi-select above it)", () => {
    expect(rangeFieldHeight()).toBe(55);
    expect(rangeGridHeight()).toBe(524);
  });

  it("adds one hint row for the market-cap hint, and one row per error line", () => {
    expect(HINT_ROW).toBe(19);
    expect(ERROR_ROW).toBe(19);
    expect(rangeGridHeight(true)).toBe(543);
  });

  it("computes the whole Fundamental card, with and without the hint", () => {
    expect(fundamentalSectionHeight()).toBe(864);
    expect(fundamentalSectionHeight(true)).toBe(883);
  });

  it("fits a pair inside the 222px card content", () => {
    expect(SIDEBAR_CONTENT_WIDTH).toBe(222);
    expect(PAIR_WIDTH).toBeLessThanOrEqual(SIDEBAR_CONTENT_WIDTH);
  });
});
