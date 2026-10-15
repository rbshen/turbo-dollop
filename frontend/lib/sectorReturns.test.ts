import { describe, expect, it } from "vitest";

import type { SectorHeatmapRowOut } from "@/lib/api/types";
import {
  axisPercent,
  computeReturnAxis,
  computeSharedZero,
  DEFAULT_CHART_WINDOWS,
  fmtAxisTick,
  RETURN_WINDOW_OPTIONS,
  sortByReturn,
  windowLabel,
  ZERO_MIN,
  ZERO_MAX,
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

const fraction = (axis: { min: number; max: number }) => -axis.min / (axis.max - axis.min);

describe("computeSharedZero", () => {
  it("is the max over charts of L / (L + R)", () => {
    // chart A: L=5, R=15 -> 0.25; chart B: L=30, R=10 -> 0.75
    expect(computeSharedZero([[-5, 15], [-30, 10]])).toBeCloseTo(0.75, 9);
    expect(computeSharedZero([[-5, 15]])).toBeCloseTo(0.25, 9);
  });

  it("clamps so zero is never jammed against an edge", () => {
    expect(computeSharedZero([[1, 2, 3]])).toBe(ZERO_MIN); // all positive: 0 -> clamped up
    expect(computeSharedZero([[-1, -2]])).toBe(ZERO_MAX); // all negative: 1 -> clamped down
    expect(computeSharedZero([[-0.1, 100]])).toBe(ZERO_MIN);
  });

  it("ignores charts with nothing to draw and centres when none draws", () => {
    expect(computeSharedZero([[null, null], [0, 0], [-3, 1]])).toBeCloseTo(0.75, 9);
    for (const charts of [[], [[]], [[null]], [[0, 0]], [[null], [0]]]) expect(computeSharedZero(charts)).toBe(0.5);
  });
});

describe("computeReturnAxis", () => {
  it("puts zero exactly at the shared fraction whatever the data", () => {
    for (const zero of [0.12, 0.3, 0.5, 0.88]) {
      for (const values of [[40.6, -5.93], [1, 2], [-1, -2], [null], [0, 0], []]) {
        expect(fraction(computeReturnAxis(values, zero))).toBeCloseTo(zero, 9);
      }
    }
  });

  it("fits both sides without clipping: every value is inside the axis, with padding", () => {
    for (const values of [[40.6, -5.93, 12], [-20, 3], [7, 9], [-4, -8]]) {
      const axis = computeReturnAxis(values, computeSharedZero([values]));
      expect(axis.min).toBeLessThan(Math.min(0, ...values));
      expect(axis.max).toBeGreaterThan(Math.max(0, ...values));
    }
  });

  it("keeps each chart's own scale: a small-move chart is tighter than a large one at the same zero", () => {
    const small = computeReturnAxis([-1.35, 1.8], 0.4);
    const large = computeReturnAxis([-20, 40.6], 0.4);
    expect(small.max - small.min).toBeLessThan(6);
    expect(large.max - large.min).toBeGreaterThan(50);
  });

  it("has round ticks on both sides of zero, inside the axis", () => {
    const axis = computeReturnAxis([-8, 20], 0.3);
    expect(axis.ticks).toContain(0);
    expect(axis.ticks.some((t) => t < 0)).toBe(true);
    expect(axis.ticks.some((t) => t > 0)).toBe(true);
    expect(axis.ticks.every((t) => t >= axis.min && t <= axis.max)).toBe(true);
  });

  it("survives no values, all zeros and a non-finite zero without NaN", () => {
    for (const [values, zero] of [[[], 0.5], [[null], 0.5], [[0, 0], 0.5], [[1], NaN]] as const) {
      const axis = computeReturnAxis(values, zero);
      expect([axis.min, axis.max, ...axis.ticks].every(Number.isFinite)).toBe(true);
      expect(axis.max).toBeGreaterThan(axis.min);
    }
  });

  it("positions values linearly and formats ticks to the step's precision", () => {
    const axis = computeReturnAxis([-2, 2], 0.5);
    expect(axisPercent(axis.min, axis)).toBe(0);
    expect(axisPercent(axis.max, axis)).toBe(100);
    expect(axisPercent(0, axis)).toBeCloseTo(50, 5);
    expect(fmtAxisTick(0, axis)).toBe("0%");
    expect(fmtAxisTick(-0.5, computeReturnAxis([-0.4, 0.4], 0.5))).toMatch(/^-0\.\d+%$/);
  });
});
