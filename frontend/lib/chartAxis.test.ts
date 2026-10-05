// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

import {
  AXIS_FONT_FAMILY,
  AXIS_FONT_SIZE,
  AXIS_TEXT_BRIGHTER,
  AXIS_OPTION_ITEMS,
  axisLayout,
  axisOptionsOffered,
  BASE_TICK_MARK_DENSITY,
  DEFAULT_AXIS_OPTIONS,
  effectiveAxisOptions,
  FEWER_TICKS_FACTOR,
  formatAxisPrice,
  loadAxisOptions,
  overlapClearancePx,
  overlappingTicks,
  saveAxisOptions,
  tickLabelsHidingOverlap,
  tickMarkDensity,
} from "@/lib/chartAxis";

const ON = { hideOverlap: true, brighter: true, fewerTicks: true, tabular: true, cleanSubPanes: true };

describe("axis options: defaults and ranges", () => {
  it("every option is off by default", () => {
    expect(Object.values(DEFAULT_AXIS_OPTIONS)).toEqual([false, false, false, false, false]);
  });

  it("only 2H·90D offers them; every other range is told all-off whatever the user chose", () => {
    expect(axisOptionsOffered("2H_90D")).toBe(true);
    for (const r of ["D_6M", "D_1Y", "D_2Y", "W_4Y"] as const) {
      expect(axisOptionsOffered(r)).toBe(false);
      expect(effectiveAxisOptions(ON, r)).toBe(DEFAULT_AXIS_OPTIONS);
    }
    expect(effectiveAxisOptions(ON, "2H_90D")).toBe(ON);
  });
});

describe("axisLayout / tickMarkDensity", () => {
  it("all off = the chart's original axis color, size and font", () => {
    expect(axisLayout(DEFAULT_AXIS_OPTIONS, "#9499a0", "Mono, monospace")).toEqual({
      textColor: "#9499a0",
      fontSize: 12,
      fontFamily: "var(--font-mono), ui-monospace, monospace",
    });
    expect(tickMarkDensity(DEFAULT_AXIS_OPTIONS)).toBe(BASE_TICK_MARK_DENSITY);
  });

  it("brighter changes the color only (never the size); tabular changes the font only", () => {
    expect(AXIS_TEXT_BRIGHTER).toBe("#e5e8ec");
    expect(axisLayout({ ...DEFAULT_AXIS_OPTIONS, brighter: true }, "#9499a0", "Mono")).toEqual({
      textColor: AXIS_TEXT_BRIGHTER,
      fontSize: AXIS_FONT_SIZE,
      fontFamily: AXIS_FONT_FAMILY,
    });
    expect(axisLayout(ON, "#9499a0", "Mono").fontSize).toBe(AXIS_FONT_SIZE);
    expect(axisLayout({ ...DEFAULT_AXIS_OPTIONS, tabular: true }, "#9499a0", "Mono")).toEqual({
      textColor: "#9499a0",
      fontSize: 12,
      fontFamily: "Mono",
    });
  });

  it("fewer ticks multiplies the minimum label spacing (a rule, not a price step)", () => {
    expect(tickMarkDensity({ ...DEFAULT_AXIS_OPTIONS, fewerTicks: true })).toBe(BASE_TICK_MARK_DENSITY * FEWER_TICKS_FACTOR);
  });
});

describe("clean sub-pane axes option", () => {
  it("is the fifth item, labelled as in the dropdown, and only changes the sub-panes (no layout or density effect)", () => {
    expect(AXIS_OPTION_ITEMS.map((i) => i.label)).toEqual(["Hide overlapping labels", "Brighter", "Fewer ticks", "Tabular numerals", "Clean sub-pane axes"]);
    const clean = { ...DEFAULT_AXIS_OPTIONS, cleanSubPanes: true };
    expect(axisLayout(clean, "#9499a0", "Mono")).toEqual(axisLayout(DEFAULT_AXIS_OPTIONS, "#9499a0", "Mono"));
    expect(tickMarkDensity(clean)).toBe(BASE_TICK_MARK_DENSITY);
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

describe("session persistence", () => {
  afterEach(() => window.sessionStorage.clear());

  it("round-trips through sessionStorage and falls back to all-off on junk", () => {
    expect(loadAxisOptions()).toEqual(DEFAULT_AXIS_OPTIONS);
    saveAxisOptions({ ...DEFAULT_AXIS_OPTIONS, fewerTicks: true });
    expect(loadAxisOptions()).toEqual({ ...DEFAULT_AXIS_OPTIONS, fewerTicks: true });
    // An entry saved before the fifth option existed loads with it off.
    window.sessionStorage.setItem("fathom-chart-axis-options", JSON.stringify({ hideOverlap: true, brighter: true, fewerTicks: false, tabular: false }));
    expect(loadAxisOptions()).toEqual({ ...DEFAULT_AXIS_OPTIONS, hideOverlap: true, brighter: true });
    window.sessionStorage.setItem("fathom-chart-axis-options", "{not json");
    expect(loadAxisOptions()).toEqual(DEFAULT_AXIS_OPTIONS);
  });
});
