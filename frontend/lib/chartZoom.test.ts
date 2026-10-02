import { describe, expect, it } from "vitest";

import {
  barSpacingForZoomLevel,
  clampToPanBounds,
  computePanBounds,
  computeRightOffset,
  computeZoomLevelMultipliers,
  MAX_BAR_SPACING_CAP,
  REFERENCE_D1Y_BAR_COUNT,
  TARGET_VISIBLE_BARS_AT_MAX_ZOOM,
} from "@/lib/chartZoom";

// 2H·90D: 90 calendar days x 4 candles a session ~ 252 candles -- the reference bar count D·1Y's margin was tuned on.
const N = 252;

describe("pan/zoom geometry for the 2H·90D range (252 candles)", () => {
  it("the candle count equals the D·1Y reference, so the right margin needs no per-range correction", () => {
    expect(N).toBe(REFERENCE_D1Y_BAR_COUNT);
    expect(computeRightOffset(N)).toBe(10);
  });

  it("pan bounds: left edge is the first candle, right edge the last candle plus the margin", () => {
    expect(computePanBounds(N)).toEqual({ minFrom: 0, maxTo: 261 });
  });

  it("clamps a pan past either edge back inside, preserving the span", () => {
    const { minFrom, maxTo } = computePanBounds(N);
    expect(clampToPanBounds(-40, 60, minFrom, maxTo)).toEqual({ from: 0, to: 60 }); // left: from clamps up
    expect(clampToPanBounds(240, 300, minFrom, maxTo)).toEqual({ from: 201, to: 261 }); // right: translated left
    expect(clampToPanBounds(-10, 400, minFrom, maxTo)).toEqual({ from: 0, to: 261 }); // wider than all data: shrunk
    expect(clampToPanBounds(100, 160, minFrom, maxTo)).toEqual({ from: 100, to: 160 }); // inside: untouched
  });

  it("three zoom levels: fit, a geometric middle step, and max zoom at ~50 visible candles", () => {
    const m = computeZoomLevelMultipliers(N, computeRightOffset(N));
    expect(m).toHaveLength(3);
    expect(m[0]).toBe(1);
    expect(m[2]).toBeCloseTo((N + 10) / TARGET_VISIBLE_BARS_AT_MAX_ZOOM, 10);
    expect(m[1]).toBeCloseTo(Math.sqrt(m[2]), 10);

    const paneWidth = 1000;
    const fit = paneWidth / (N + 10);
    const spacings = m.map((_, i) => barSpacingForZoomLevel(fit, i, m));
    expect(spacings[0]).toBeCloseTo(fit, 10); // level 0 is the full 90-day view
    expect(spacings[1]).toBeGreaterThan(spacings[0]);
    expect(spacings[2]).toBeGreaterThan(spacings[1]);
    expect(paneWidth / spacings[2]).toBeCloseTo(TARGET_VISIBLE_BARS_AT_MAX_ZOOM, 6); // ~50 candles, about 12 sessions
    expect(spacings[2]).toBeLessThanOrEqual(MAX_BAR_SPACING_CAP);
  });

  it("each zoom level anchors to the right edge and stays inside the pan bounds", () => {
    const { minFrom, maxTo } = computePanBounds(N);
    const m = computeZoomLevelMultipliers(N, computeRightOffset(N));
    const paneWidth = 1000;
    const fit = paneWidth / (N + 10);
    for (let i = 0; i < m.length; i++) {
      const visible = paneWidth / barSpacingForZoomLevel(fit, i, m);
      const { from, to } = clampToPanBounds(maxTo - visible, maxTo, minFrom, maxTo);
      expect(to).toBe(maxTo);
      expect(from).toBeGreaterThanOrEqual(minFrom);
    }
    // Level 0 shows everything: from clamps exactly to the first candle.
    expect(clampToPanBounds(maxTo - paneWidth / fit, maxTo, minFrom, maxTo).from).toBeCloseTo(0, 6);
  });
});
