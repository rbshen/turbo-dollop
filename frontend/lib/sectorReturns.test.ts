import { describe, expect, it } from "vitest";

import type { SectorHeatmapRowOut } from "@/lib/api/types";
import {
  axisPercent,
  computeReturnAxis,
  DEFAULT_CHART_WINDOWS,
  fmtAxisTick,
  RETURN_WINDOW_OPTIONS,
  sortByReturn,
  windowLabel,
} from "@/lib/sectorReturns";

function row(ticker: string, returns: Record<string, number | null>): SectorHeatmapRowOut {
  return {
    ticker,
    name: ticker,
    cells: Object.fromEntries(Object.entries(returns).map(([w, v]) => [w, { return_pct: v, base_date: v == null ? null : "2026-01-02" }])),
  };
}

describe("windows", () => {
  it("offers the eight windows, with 1d labelled Today, and defaults to Today / 1W / 1M", () => {
    expect(RETURN_WINDOW_OPTIONS.map((o) => o.label)).toEqual(["Today", "1W", "1M", "3M", "6M", "9M", "YTD", "1Y"]);
    expect(windowLabel("1d")).toBe("Today");
    expect(DEFAULT_CHART_WINDOWS).toEqual(["1d", "1w", "1m"]);
  });
});

describe("sortByReturn", () => {
  it("sorts descending, sinks missing values, and ties keep universe order", () => {
    const rows = [row("A", { "1d": 1 }), row("B", { "1d": null }), row("C", { "1d": 3 }), row("D", { "1d": 1 }), row("E", { "1d": -2 })];
    expect(sortByReturn(rows, "1d").map((r) => r.ticker)).toEqual(["C", "A", "D", "E", "B"]);
  });

  it("treats a window missing from a row's cells as no value", () => {
    expect(sortByReturn([row("A", {}), row("B", { "1d": 0 })], "1d").map((r) => r.ticker)).toEqual(["B", "A"]);
  });
});

describe("computeReturnAxis", () => {
  it("covers every value and zero, with ticks inside the axis", () => {
    const axis = computeReturnAxis([40.6, -5.93, 12]);
    expect(axis.min).toBeLessThan(-5.93);
    expect(axis.max).toBeGreaterThan(40.6);
    expect(axis.ticks[0]).toBe(axis.min);
    expect(axis.ticks.at(-1)).toBe(axis.max);
    expect(axis.ticks).toContain(0);
  });

  it("keeps zero inside the axis, padded, when every value is positive or every value is negative", () => {
    const pos = computeReturnAxis([1, 2, 3]);
    expect(pos.min).toBeLessThan(0);
    const neg = computeReturnAxis([-1, -2, -3]);
    expect(neg.max).toBeGreaterThan(0);
  });

  it("scales to its own range: a small-move chart gets a much tighter axis than a large-move one", () => {
    const small = computeReturnAxis([-1.35, 1.8, 0.08]);
    const large = computeReturnAxis([-20, 40.6]);
    expect(small.max - small.min).toBeLessThan(5);
    expect(large.max - large.min).toBeGreaterThan(50);
  });

  it("ignores nulls and survives no values / all zeros", () => {
    expect(computeReturnAxis([null, 2, null])).toEqual(computeReturnAxis([2]));
    for (const values of [[], [null], [0, 0]]) {
      const axis = computeReturnAxis(values);
      expect(Number.isFinite(axis.min) && Number.isFinite(axis.max)).toBe(true);
      expect(axis.max).toBeGreaterThan(axis.min);
      expect(axis.min).toBeLessThanOrEqual(0);
      expect(axis.max).toBeGreaterThanOrEqual(0);
    }
  });

  it("positions values linearly and formats ticks to the step's precision", () => {
    const axis = computeReturnAxis([-2, 2]);
    expect(axisPercent(axis.min, axis)).toBe(0);
    expect(axisPercent(axis.max, axis)).toBe(100);
    expect(axisPercent(0, axis)).toBeCloseTo(50, 5);
    expect(fmtAxisTick(0, axis)).toBe("0%");
    expect(fmtAxisTick(-0.5, computeReturnAxis([-0.4, 0.4]))).toMatch(/^-0\.\d+%$/);
  });
});
