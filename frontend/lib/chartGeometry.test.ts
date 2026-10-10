import { describe, expect, it } from "vitest";

import {
  bandPosition,
  divergingGeometry,
  divergingScale,
  divergingTone,
  gaugeGeometry,
  gaugeState,
  groupStageRuns,
  priceRangeGeometry,
  sparklineGeometry,
  stageSincePosition,
  tierScaleGeometry,
} from "@/lib/chartGeometry";

describe("gaugeState", () => {
  it("ceiling: ok up to the pass line, monitor between the lines, breach past the hard limit", () => {
    expect(gaugeState(3.0, 3.0, 4.0, "ceiling")).toBe("ok"); // at the pass line still passes
    expect(gaugeState(3.5, 3.0, 4.0, "ceiling")).toBe("monitor");
    expect(gaugeState(4.0, 3.0, 4.0, "ceiling")).toBe("monitor");
    expect(gaugeState(4.1, 3.0, 4.0, "ceiling")).toBe("breach");
  });
  it("floor: ok from the pass line up, monitor between, breach under the hard limit", () => {
    expect(gaugeState(1.0, 1.0, 0.7, "floor")).toBe("ok");
    expect(gaugeState(0.85, 1.0, 0.7, "floor")).toBe("monitor");
    expect(gaugeState(0.7, 1.0, 0.7, "floor")).toBe("monitor");
    expect(gaugeState(0.69, 1.0, 0.7, "floor")).toBe("breach");
  });
  it("one line only (gearing, CET1, NPL): past it is a breach, there is no monitor zone", () => {
    expect(gaugeState(45, 45, 45, "ceiling")).toBe("ok");
    expect(gaugeState(45.1, 45, 45, "ceiling")).toBe("breach");
    expect(gaugeState(9.9, 10, 10, "floor")).toBe("breach");
  });
});

describe("gaugeGeometry", () => {
  it("places the lines and the zone on one scale and clamps an extreme value", () => {
    const g = gaugeGeometry(2.0, 3.0, 4.0, "ceiling");
    expect(g.scaleMax).toBe(6);
    expect(g.passPct).toBeCloseTo(50);
    expect(g.limitPct).toBeCloseTo(66.67, 1);
    expect(g.zone!.leftPct).toBeCloseTo(50);
    expect(g.zone!.widthPct).toBeCloseTo(16.67, 1);
    expect(g.fillPct).toBeCloseTo(33.33, 1);
    expect(g.overflow).toBe(false);
    const wild = gaugeGeometry(84.56, 3.0, 4.0, "ceiling");
    expect(wild.fillPct).toBe(100);
    expect(wild.overflow).toBe(true);
    expect(wild.state).toBe("breach");
  });
  it("has no zone when the two lines coincide and no fill without a value", () => {
    const g = gaugeGeometry(null, 45, 45, "ceiling");
    expect(g.zone).toBeNull();
    expect(g.fillPct).toBeNull();
    expect(g.state).toBeNull();
  });
  it("floor zone sits between the hard limit and the pass line", () => {
    const g = gaugeGeometry(1.8, 1.0, 0.7, "floor");
    expect(g.scaleMax).toBe(2);
    expect(g.zone!.leftPct).toBeCloseTo(35);
    expect(g.zone!.widthPct).toBeCloseTo(15);
  });
  it("a negative value extends the track to the left and fills between the value and zero", () => {
    const g = gaugeGeometry(-3, 3, 4, "ceiling");
    expect(g.scaleMin).toBeCloseTo(-3.45);
    expect(g.fillLeftPct).toBeCloseTo(4.76, 1); // the value sits just inside the left edge
    expect(g.fillLeftPct! + g.fillPct!).toBeCloseTo(((0 - g.scaleMin) / (g.scaleMax - g.scaleMin)) * 100); // and the fill ends at zero
    expect(g.fillLeftPct! + g.fillPct!).toBeLessThan(g.passPct);
  });
  it("a line at zero (FCF after stock comp) scales from the value", () => {
    const g = gaugeGeometry(8, 0, 0, "floor");
    expect(g.scaleMax).toBe(12);
    expect(g.passPct).toBe(0);
    expect(g.state).toBe("ok");
    expect(gaugeGeometry(-2, 0, 0, "floor").state).toBe("breach");
    expect(gaugeGeometry(null, 0, 0, "floor").scaleMax).toBe(1);
  });
});

describe("diverging bar", () => {
  it("is in line inside the band (inclusive), ahead above, behind below", () => {
    expect(divergingTone(2, 2)).toBe("in_line");
    expect(divergingTone(-2, 2)).toBe("in_line");
    expect(divergingTone(2.1, 2)).toBe("ahead");
    expect(divergingTone(-2.1, 2)).toBe("behind");
  });
  it("shares one symmetric scale across a stack and keeps the band visible", () => {
    expect(divergingScale([12, -30, null], 2)).toBeCloseTo(34.5);
    expect(divergingScale([0.4], 2)).toBe(6); // three bands
    expect(divergingScale([], 0.5)).toBe(5); // the floor
  });
  it("draws from the centre toward the sign and clamps past the scale", () => {
    const up = divergingGeometry(10, 2, 20);
    expect(up.barFromPct).toBe(50);
    expect(up.barWidthPct).toBeCloseTo(25);
    expect(up.bandLeftPct).toBeCloseTo(45);
    expect(up.bandWidthPct).toBeCloseTo(10);
    const down = divergingGeometry(-30, 2, 20);
    expect(down.barFromPct).toBe(0);
    expect(down.barWidthPct).toBe(50);
    expect(down.overflow).toBe(true);
    expect(divergingGeometry(null, 2, 20).tone).toBeNull();
  });
});

describe("stage timeline", () => {
  const weeks = [
    { week: "2026-01-05", stage: "advance" },
    { week: "2026-01-12", stage: "advance" },
    { week: "2026-01-19", stage: "top" },
    { week: "2026-01-26", stage: "decline" },
    { week: "2026-02-02", stage: "decline" },
  ];
  it("groups consecutive weeks of one stage into runs", () => {
    expect(groupStageRuns(weeks)).toEqual([
      { stage: "advance", weeks: 2, start: 0 },
      { stage: "top", weeks: 1, start: 2 },
      { stage: "decline", weeks: 2, start: 3 },
    ]);
    expect(groupStageRuns([])).toEqual([]);
    expect(groupStageRuns([{ week: "a", stage: null }, { week: "b", stage: "base" }]).map((r) => r.stage)).toEqual([null, "base"]);
  });
  it("positions the since date on the strip, and flags one outside the window", () => {
    expect(stageSincePosition(weeks, "2026-01-26")).toEqual({ pct: 60, inside: true });
    expect(stageSincePosition(weeks, "2025-06-01")).toEqual({ pct: 0, inside: false });
    expect(stageSincePosition(weeks, "2026-03-01")).toEqual({ pct: 100, inside: false });
    expect(stageSincePosition(weeks, null)).toBeNull();
    expect(stageSincePosition([], "2026-01-26")).toBeNull();
  });
});

describe("price range", () => {
  it("reads the band with the valuation verdict's own rule", () => {
    expect(bandPosition(90, 100, 0.9, 1.1)).toBe("below"); // at 0.9x reads undervalued
    expect(bandPosition(90.01, 100, 0.9, 1.1)).toBe("inside");
    expect(bandPosition(110, 100, 0.9, 1.1)).toBe("above");
    expect(bandPosition(100, 100, 0.9, 1.1)).toBe("inside");
  });
  it("always puts the price on the track and centres the band around fair value", () => {
    const g = priceRangeGeometry(60, 100, 0.9, 1.1);
    expect(g.position).toBe("below");
    expect(g.premiumPct).toBeCloseTo(-40);
    expect(g.pricePct).toBeGreaterThan(0);
    expect(g.pricePct).toBeLessThan(g.bandLeftPct);
    expect(g.bandLeftPct + g.bandWidthPct).toBeGreaterThan(g.fairPct);
    const high = priceRangeGeometry(250, 100, 0.9, 1.1);
    expect(high.pricePct).toBeLessThan(100);
    expect(high.position).toBe("above");
  });
});

describe("sparkline", () => {
  it("maps values into a 100 x 100 box with y flipped and gives the end dot", () => {
    const g = sparklineGeometry([1, 2, 3]);
    expect(g.points).toBe("0.00,100.00 50.00,50.00 100.00,0.00");
    expect(g.last).toEqual({ xPct: 100, yPct: 0 });
  });
  it("draws a flat series mid-box without dividing by zero, skips gaps, and gives up under two points", () => {
    expect(sparklineGeometry([5, 5, 5]).points).toBe("0.00,100.00 50.00,100.00 100.00,100.00");
    expect(sparklineGeometry([1, null, 3]).points).toBe("0.00,100.00 100.00,0.00");
    expect(sparklineGeometry([1]).points).toBeNull();
    expect(sparklineGeometry([]).last).toBeNull();
  });
});

describe("tier scale", () => {
  it("places the tier lines on a 0-20 scale and clamps", () => {
    const g = tierScaleGeometry(12, 20, [5, 10, 15]);
    expect(g.fillPct).toBe(60);
    expect(g.ticks.map((t) => t.pct)).toEqual([25, 50, 75]);
    expect(tierScaleGeometry(35, 20, [5]).overflow).toBe(true);
    expect(tierScaleGeometry(-4, 20, [5]).fillPct).toBe(0);
    expect(tierScaleGeometry(null, 20, [5]).fillPct).toBeNull();
  });
});
