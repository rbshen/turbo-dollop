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

describe("screener sidebar metrics", () => {
  it("reproduces today's measured 555px range grid", () => {
    expect(rangeFieldHeight("today")).toBe(51);
    expect(rangeGridHeight("today")).toBe(555);
  });

  it("keeps the underline variant at today's height and the boxed variant 36px taller", () => {
    expect(rangeGridHeight("underline")).toBe(555);
    expect(rangeGridHeight("boxed")).toBe(591);
  });

  it("adds one hint row for the market-cap hint, and one row per error line", () => {
    expect(HINT_ROW).toBe(19);
    expect(ERROR_ROW).toBe(19);
    expect(rangeGridHeight("boxed", true)).toBe(610);
  });

  it("computes the whole Fundamental card", () => {
    expect(fundamentalSectionHeight("today")).toBe(847);
    expect(fundamentalSectionHeight("underline")).toBe(847);
    expect(fundamentalSectionHeight("boxed")).toBe(883);
  });

  it("fits a pair inside the 222px card content", () => {
    expect(SIDEBAR_CONTENT_WIDTH).toBe(222);
    expect(PAIR_WIDTH).toBeLessThanOrEqual(SIDEBAR_CONTENT_WIDTH);
  });
});
