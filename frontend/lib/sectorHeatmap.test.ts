import { describe, expect, it } from "vitest";

import type { SectorHeatmapRowOut } from "@/lib/api/types";
import {
  cellBackground,
  columnScale,
  DEFAULT_HEATMAP_SORT,
  MIN_COLUMN_SCALE_PP,
  nextSort,
  sortHeatmapRows,
  windowLabel,
} from "@/lib/sectorHeatmap";

function row(ticker: string, returns: Record<string, number | null>): SectorHeatmapRowOut {
  return {
    ticker,
    name: ticker,
    cells: Object.fromEntries(Object.entries(returns).map(([w, v]) => [w, { return_pct: v, base_date: v == null ? null : "2026-01-02" }])),
  };
}

const ROWS = [row("AAA", { "1m": 5, "3m": -10 }), row("BBB", { "1m": -2, "3m": 20 }), row("CCC", { "1m": null, "3m": 20 }), row("DDD", { "1m": 9, "3m": null })];

describe("windowLabel", () => {
  it("upper-cases the window keys and spells YTD", () => {
    expect(["1d", "1w", "1m", "3m", "6m", "9m", "ytd", "1y"].map(windowLabel)).toEqual([
      "1D", "1W", "1M", "3M", "6M", "9M", "YTD", "1Y",
    ]);
  });
});

describe("columnScale", () => {
  it("is the column's own largest absolute move, regardless of sign", () => {
    expect(columnScale(ROWS, "3m")).toBe(20);
    expect(columnScale(ROWS, "1m")).toBe(9);
  });

  it("never drops below the floor, so a flat column isn't painted at full intensity", () => {
    expect(columnScale([row("A", { "1w": 0.2 })], "1w")).toBe(MIN_COLUMN_SCALE_PP);
    expect(columnScale([], "1w")).toBe(MIN_COLUMN_SCALE_PP);
  });
});

describe("cellBackground", () => {
  it("leaves null and flat values untinted", () => {
    expect(cellBackground(null, 10)).toBeUndefined();
    expect(cellBackground(0, 10)).toBeUndefined();
    expect(cellBackground(0.01, 10)).toBeUndefined();
  });

  it("uses the positive token for gains and the negative token for losses", () => {
    expect(cellBackground(5, 10)).toContain("--color-positive-strong");
    expect(cellBackground(-5, 10)).toContain("--color-negative");
  });

  it("tints proportionally to magnitude, capping at the column scale", () => {
    const pct = (css: string | undefined) => Number(css?.match(/\) (\d+)%/)?.[1]);
    expect(pct(cellBackground(1, 10))).toBeLessThan(pct(cellBackground(5, 10)));
    expect(pct(cellBackground(5, 10))).toBeLessThan(pct(cellBackground(10, 10)));
    expect(pct(cellBackground(50, 10))).toBe(pct(cellBackground(10, 10)));
    // Sign doesn't change strength.
    expect(pct(cellBackground(-5, 10))).toBe(pct(cellBackground(5, 10)));
  });
});

describe("sortHeatmapRows", () => {
  it("sorts descending by the chosen window, ties keeping universe order", () => {
    expect(sortHeatmapRows(ROWS, { window: "3m", direction: "desc" }).map((r) => r.ticker)).toEqual(["BBB", "CCC", "AAA", "DDD"]);
  });

  it("sorts ascending", () => {
    expect(sortHeatmapRows(ROWS, { window: "1m", direction: "asc" }).map((r) => r.ticker)).toEqual(["BBB", "AAA", "DDD", "CCC"]);
  });

  it("sinks null cells to the bottom in both directions", () => {
    expect(sortHeatmapRows(ROWS, { window: "1m", direction: "desc" }).map((r) => r.ticker)).toEqual(["DDD", "AAA", "BBB", "CCC"]);
  });

  it("does not mutate its input", () => {
    const before = ROWS.map((r) => r.ticker);
    sortHeatmapRows(ROWS, { window: "3m", direction: "desc" });
    expect(ROWS.map((r) => r.ticker)).toEqual(before);
  });
});

describe("nextSort", () => {
  it("flips direction on the active column", () => {
    expect(nextSort({ window: "3m", direction: "desc" }, "3m")).toEqual({ window: "3m", direction: "asc" });
    expect(nextSort({ window: "3m", direction: "asc" }, "3m")).toEqual({ window: "3m", direction: "desc" });
  });

  it("starts a newly clicked column best-first", () => {
    expect(nextSort({ window: "3m", direction: "asc" }, "1y")).toEqual({ window: "1y", direction: "desc" });
  });

  it("defaults to 3M descending", () => {
    expect(DEFAULT_HEATMAP_SORT).toEqual({ window: "3m", direction: "desc" });
  });
});
