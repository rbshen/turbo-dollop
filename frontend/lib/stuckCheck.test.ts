import { describe, expect, it } from "vitest";

import type { StuckFigure, StuckRow } from "@/lib/api/types";
import { formatFigure, rowsForGroup, STATUS_LABEL, STUCK_GROUPS } from "@/lib/stuckCheck";

const fig = (over: Partial<StuckFigure>): StuckFigure => ({ key: "k", label: "L", value: null, unit: "pct", text: null, ...over });

describe("formatFigure", () => {
  it.each([
    [{ unit: "pct", value: 22.14 }, "22.1%"],
    [{ unit: "pct", value: -3.06 }, "-3.1%"],
    [{ unit: "pp", value: 1.34 }, "+1.3 pp"],
    [{ unit: "pp", value: -36.5 }, "−36.5 pp"],
    [{ unit: "pp", value: 0 }, "0.0 pp"],
    [{ unit: "ratio", value: 0.66 }, "0.66"],
    [{ unit: "multiple", value: 2.5 }, "2.5×"],
    [{ unit: "money", value: 1_096_679_000 }, "$1.10B"],
    [{ unit: "money", value: -56_708_000_000 }, "-$56.71B"],
    [{ unit: "money", value: 5_000 }, "$5,000.00"],
  ])("formats %o as %s", (over, expected) => {
    expect(formatFigure(fig(over))).toBe(expected);
  });

  it("uses the reporting currency for money", () => {
    expect(formatFigure(fig({ unit: "money", value: 2_000_000_000 }), "CNY")).toMatch(/2\.00B$/);
    expect(formatFigure(fig({ unit: "money", value: 2_000_000_000 }), "CNY")).not.toMatch(/^\$/);
  });

  it("shows the word alone when there is no value, and beside the figure when there is one", () => {
    expect(formatFigure(fig({ value: null, text: "n/m" }))).toBe("n/m");
    expect(formatFigure(fig({ value: null, text: null }))).toBe("—");
    expect(formatFigure(fig({ unit: "pp", value: 107.07, text: "leads" }))).toBe("+107.1 pp · leads");
    expect(formatFigure(fig({ unit: "text", value: null, text: "No buybacks" }))).toBe("No buybacks");
    expect(formatFigure(fig({ unit: "count", value: 93, text: "93rd percentile" }))).toBe("93rd percentile");
  });

  it("draws the stored row-7 values in the app's own display words, never recomputed", () => {
    const text = (key: string, value: string) => formatFigure(fig({ key, unit: "text", text: value }));
    expect(text("overall_verdict", "Pass with caution")).toBe("Pass with caution");
    expect(text("overall_verdict", "Fail")).toBe("May not pass"); // the app-wide display word for a stored Fail
    expect(text("valuation_verdict", "undervalued")).toBe("Undervalued");
    expect(text("valuation_verdict", "fair")).toBe("Fairvalued");
    expect(text("weinstein_stage", "decline")).toBe("Stage 4 · Decline");
    expect(text("weinstein_since", "2026-03-02")).toBe("2026-03-02");
    expect(formatFigure(fig({ key: "perf_5y_vs_spy", unit: "pp", value: -12.5, text: "underperform" }))).toBe("−12.5 pp · underperform");
    expect(formatFigure(fig({ key: "perf_5y_vs_spy", unit: "pp", value: 0.2, text: "match" }))).toBe("+0.2 pp · in line");
  });
});

describe("labels and groups", () => {
  it("has exactly the four labels, none of them a verdict word", () => {
    expect(Object.values(STATUS_LABEL)).toEqual(["OK", "Flagged", "Not applicable", "Not reported"]);
  });

  it("splits rows into the three groups by number and drops nothing", () => {
    const rows = [1, 2, 3, 5, 6, 7, 8, 9, 10, 12].map((number) => ({ number }) as StuckRow);
    const grouped = STUCK_GROUPS.map((g) => rowsForGroup(rows, g.numbers).map((r) => r.number));
    expect(grouped).toEqual([[1, 2, 3, 5, 6], [7, 8], [9, 10, 12]]);
    expect(grouped.flat()).toHaveLength(rows.length);
  });
});
