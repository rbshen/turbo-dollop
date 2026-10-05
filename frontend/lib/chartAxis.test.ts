// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

import {
  AXIS_FONT_SIZE,
  AXIS_OPTION_ITEMS,
  AXIS_TEXT_COLOR,
  AXIS_TICK_MARK_DENSITY,
  axisLayout,
  axisTagHeightPx,
  BASE_TICK_MARK_DENSITY,
  DEFAULT_AXIS_OPTIONS,
  FEWER_TICKS_FACTOR,
  formatAxisPrice,
  loadAxisOptions,
  nudgeTagYs,
  overlapClearancePx,
  overlappingTicks,
  saveAxisOptions,
  tickLabelsHidingOverlap,
} from "@/lib/chartAxis";

describe("the one toggle", () => {
  it("is 'Hide overlapping labels', ON by default, and the only item in the dropdown", () => {
    expect(DEFAULT_AXIS_OPTIONS).toEqual({ hideOverlap: true });
    expect(AXIS_OPTION_ITEMS).toEqual([{ key: "hideOverlap", label: "Hide overlapping labels" }]);
  });
});

describe("the permanent settings", () => {
  it("brighter is a color only: #e5e8ec at the unchanged 12 px, in the given monospace family", () => {
    expect(AXIS_TEXT_COLOR).toBe("#e5e8ec");
    expect(axisLayout("Mono, monospace")).toEqual({ textColor: "#e5e8ec", fontSize: 12, fontFamily: "Mono, monospace" });
    expect(AXIS_FONT_SIZE).toBe(12);
  });

  it("fewer ticks is a density rule: twice the library's minimum label spacing", () => {
    expect(AXIS_TICK_MARK_DENSITY).toBe(BASE_TICK_MARK_DENSITY * FEWER_TICKS_FACTOR);
    expect(AXIS_TICK_MARK_DENSITY).toBe(5);
  });
});

describe("overlap hiding", () => {
  it("flags a tick within the clearance of any tag, and nothing else", () => {
    const c = overlapClearancePx(12);
    expect(c).toBe(16);
    expect(overlappingTicks([100, 130, 160, null], [135], c)).toEqual([false, true, false, false]);
    expect(overlappingTicks([100, 130], [], c)).toEqual([false, false]);
    expect(overlappingTicks([100], [100 + c], c)).toEqual([false]); // exactly the clearance away: clear
    expect(overlappingTicks([100], [100 + c - 1], c)).toEqual([true]);
  });

  it("clearance grows with the font size", () => {
    expect(overlapClearancePx(14)).toBeGreaterThan(overlapClearancePx(12));
  });

  it("blanks the overlapping labels and formats the rest like the default two-decimal format", () => {
    // 4 px per $1: the tick at 20 (y 80) sits 1.6px from the tag at 20.4; the others are 18px+ away.
    const yOf = (p: number) => p * 4;
    expect(tickLabelsHidingOverlap([10, 15, 20, 25], yOf, [20.4], 16)).toEqual(["10.00", "15.00", "", "25.00"]);
    expect(tickLabelsHidingOverlap([10, 15], () => null, [10], 16)).toEqual(["10.00", "15.00"]); // unplaceable: kept
    expect(formatAxisPrice(-3.456)).toBe("−3.46");
    expect(formatAxisPrice(0.4)).toBe("0.40");
  });
});

describe("nudging close axis tags", () => {
  const H = axisTagHeightPx(12);

  it("a tag is 17 px tall at 12 px (font plus the library's padding)", () => {
    expect(H).toBe(17);
    expect(axisTagHeightPx(14)).toBeGreaterThan(H);
  });

  it("separates a colliding pair symmetrically: upper tag up, lower tag down, half the shortfall each", () => {
    // RSI 84.75 (upper, y 30) and 80.81 (lower, y 34), 4 px apart; input order is [80.81, 84.75].
    const out = nudgeTagYs([34, 30], H, 8.5, 91.5);
    expect(out[1]).toBeCloseTo(30 - 6.5); // 84.75: up
    expect(out[0]).toBeCloseTo(34 + 6.5); // 80.81: down
    expect(out[0]! - out[1]!).toBeCloseTo(H); // exactly one tag height apart: the minimum
  });

  it("leaves tags that already clear each other exactly where they are", () => {
    expect(nudgeTagYs([20, 20 + H, 90], H, 8.5, 91.5)).toEqual([20, 20 + H, 90]);
    expect(nudgeTagYs([50], H, 8.5, 91.5)).toEqual([50]);
  });

  it("keeps each tag's own slot (input order), passes null through, and stays inside the pane", () => {
    expect(nudgeTagYs([null, 40, 41], H, 8.5, 91.5).map((y) => y === null)).toEqual([true, false, false]);
    const top = nudgeTagYs([10, 9], H, 8.5, 91.5); // would be pushed above the pane top
    expect(Math.min(...(top as number[]))).toBeGreaterThanOrEqual(8.5);
    expect(top[1]!).toBeLessThan(top[0]!); // the tag of the higher line (smaller y) stays above
    expect(top[0]! - top[1]!).toBeGreaterThanOrEqual(H - 1e-9);
  });
});

describe("session persistence", () => {
  afterEach(() => window.sessionStorage.clear());
  const KEY = "fathom-chart-axis-options";

  it("with nothing stored the default is ON", () => {
    expect(loadAxisOptions()).toEqual({ hideOverlap: true });
  });

  it("a stored choice overrides the default, both ways: a stored off stays off for the session", () => {
    saveAxisOptions({ hideOverlap: false });
    expect(window.sessionStorage.getItem(KEY)).toBe('{"hideOverlap":false}');
    expect(loadAxisOptions()).toEqual({ hideOverlap: false });
    saveAxisOptions({ hideOverlap: true });
    expect(loadAxisOptions()).toEqual({ hideOverlap: true });
  });

  it("junk, or an entry without the field, falls back to the default (on)", () => {
    window.sessionStorage.setItem(KEY, "{not json");
    expect(loadAxisOptions()).toEqual({ hideOverlap: true });
    window.sessionStorage.setItem(KEY, JSON.stringify({ brighter: false }));
    expect(loadAxisOptions()).toEqual({ hideOverlap: true });
    window.sessionStorage.setItem(KEY, JSON.stringify({ hideOverlap: "no" }));
    expect(loadAxisOptions()).toEqual({ hideOverlap: true });
  });

  it("an entry saved by an older version keeps its hideOverlap value; its removed keys are ignored", () => {
    window.sessionStorage.setItem(KEY, JSON.stringify({ hideOverlap: false, brighter: true, fewerTicks: true, tabular: true, cleanSubPanes: true }));
    expect(loadAxisOptions()).toEqual({ hideOverlap: false });
    window.sessionStorage.setItem(KEY, JSON.stringify({ hideOverlap: true, brighter: true }));
    expect(loadAxisOptions()).toEqual({ hideOverlap: true });
  });
});
