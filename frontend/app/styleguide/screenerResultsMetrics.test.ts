import { describe, expect, it } from "vitest";

import {
  BUTTON_WIDTH,
  LONGEST_SORT_LABEL,
  NAMING_BUTTON_ROW,
  OVERWRITE_BUTTON_ROW,
  SELECT_MEDIUM_WIDTH,
  SELECT_WIDE_WIDTH,
  overwriteMessageLines,
  rowWidth,
  selectTextRoom,
} from "./screenerResultsMetrics";
import { SIDEBAR_CONTENT_WIDTH, SIDEBAR_WIDTH } from "./screenerSidebarMetrics";

describe("screenerResultsMetrics", () => {
  it("medium clips the longest Sort label and wide fits it", () => {
    expect(selectTextRoom(SELECT_MEDIUM_WIDTH)).toBe(130);
    expect(LONGEST_SORT_LABEL.width).toBeGreaterThan(selectTextRoom(SELECT_MEDIUM_WIDTH));
    expect(LONGEST_SORT_LABEL.width).toBeLessThan(selectTextRoom(SELECT_WIDE_WIDTH));
  });

  it("the naming and overwrite button rows fit the 222px sidebar content width with room to spare", () => {
    expect(SIDEBAR_CONTENT_WIDTH).toBe(222);
    expect(NAMING_BUTTON_ROW).toBeLessThan(SIDEBAR_CONTENT_WIDTH);
    expect(OVERWRITE_BUTTON_ROW).toBeLessThan(SIDEBAR_CONTENT_WIDTH);
    expect(NAMING_BUTTON_ROW).toBeCloseTo(BUTTON_WIDTH.saveFailed + 8 + BUTTON_WIDTH.cancel, 5);
  });

  it("the overwrite message wraps to a second line at 222px and at 256px it still fits in two", () => {
    expect(overwriteMessageLines(SIDEBAR_CONTENT_WIDTH)).toBe(2);
    expect(overwriteMessageLines(SIDEBAR_WIDTH)).toBe(2);
  });

  it("rowWidth sums the widths and the 8px gaps", () => {
    expect(rowWidth(10, 20, 30)).toBe(76);
    expect(rowWidth(10)).toBe(10);
  });
});
