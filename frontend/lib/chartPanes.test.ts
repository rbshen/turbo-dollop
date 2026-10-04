import { describe, expect, it } from "vitest";

import type { ChartOut } from "@/lib/api/types";
import {
  extendAutoscale,
  formatLevel,
  MAIN_PANE_HEIGHT,
  nominalLabelTops,
  PANE_LABEL_BAND_PX,
  PANE_SEPARATOR_HEIGHT,
  SUB_PANE_HEIGHT,
  SUB_PANE_SCALE_MARGINS_2H,
  subPaneSpecs,
  topLevelClearsLabel,
  totalChartHeight,
} from "@/lib/chartPanes";

const pt = [{ time: "2026-09-29T09:30:00", value: 1 }];
const LEVELS = { rsi: [12, 30, 70, 80.81, 84.75], adx: [40], wvf: [0.4] };

function data(over: Partial<ChartOut> = {}): ChartOut {
  return {
    timeframe: "daily",
    rsi: pt,
    stochastic: [{ time: "2026-09-29", k: 1, d: 1 }],
    warren_rsi: [],
    warren_adx: [],
    warren_plus_di: [],
    warren_minus_di: [],
    warren_wvf: [],
    warren_levels: null,
    ...over,
  } as unknown as ChartOut;
}

const twoH = (over: Partial<ChartOut> = {}) =>
  data({ timeframe: "2h", rsi: [], stochastic: [], warren_rsi: pt, warren_adx: pt, warren_plus_di: pt, warren_minus_di: pt, warren_wvf: pt, warren_levels: LEVELS, ...over });

describe("subPaneSpecs", () => {
  it("daily/weekly keep RSI then Stochastic, each only with data (unchanged)", () => {
    expect(subPaneSpecs(data()).map((s) => s.id)).toEqual(["rsi", "stochastic"]);
    expect(subPaneSpecs(data({ stochastic: [] })).map((s) => s.id)).toEqual(["rsi"]);
    expect(subPaneSpecs(data({ rsi: [], stochastic: [] }))).toEqual([]);
    expect(subPaneSpecs(data()).map((s) => s.label)).toEqual(["RSI (14)", "Full Stochastic (5, 3, 3) EMA"]);
  });

  it("2H·90D is exactly Warren RSI, ADX and WVF -- never the daily rsi/stochastic fields", () => {
    const specs = subPaneSpecs(twoH({ rsi: pt, stochastic: [{ time: "x", k: 1, d: 1 }] }));
    expect(specs.map((s) => s.id)).toEqual(["warren-rsi", "warren-adx", "warren-wvf"]);
    expect(specs.every((s) => s.height === SUB_PANE_HEIGHT)).toBe(true);
  });

  it("2H labels name the indicator and list the engine's reference levels", () => {
    const labels = subPaneSpecs(twoH()).map((s) => s.label);
    expect(labels).toEqual(["Warren RSI (14) · 12 · 80.81 · 84.75", "Warren ADX (14) · 40", "Warren WVF (22) · 0.40"]);
    expect(subPaneSpecs(twoH())[1].legend?.map((l) => l.text)).toEqual(["ADX"]);
  });

  it("2H omits a pane whose series is empty, and still labels without levels", () => {
    expect(subPaneSpecs(twoH({ warren_adx: [] })).map((s) => s.id)).toEqual(["warren-rsi", "warren-wvf"]);
    expect(subPaneSpecs(twoH({ warren_levels: null })).map((s) => s.label)).toEqual(["Warren RSI (14)", "Warren ADX (14)", "Warren WVF (22)"]);
  });

  it("formats levels: integers bare, others two decimals", () => {
    expect([12, 80.81, 0.4, 84.75].map(formatLevel)).toEqual(["12", "80.81", "0.40", "84.75"]);
  });
});

describe("pane geometry", () => {
  it("total height is the main pane plus each sub-pane and its separator", () => {
    expect(totalChartHeight([])).toBe(MAIN_PANE_HEIGHT);
    expect(totalChartHeight(subPaneSpecs(data()))).toBe(580 + 2 * 101); // unchanged from before
    expect(totalChartHeight(subPaneSpecs(twoH()))).toBe(580 + 3 * 101);
  });

  it("nominal label tops step down by pane + separator", () => {
    expect(nominalLabelTops(subPaneSpecs(twoH()))).toEqual([581, 682, 783]);
    expect(nominalLabelTops(subPaneSpecs(data()))).toEqual([581, 682]);
    expect(PANE_SEPARATOR_HEIGHT).toBe(1);
  });

  it("every 2H sub-pane keeps its highest reference line below its label band, by construction", () => {
    expect(topLevelClearsLabel(SUB_PANE_HEIGHT)).toBe(true);
    expect(SUB_PANE_SCALE_MARGINS_2H.top * SUB_PANE_HEIGHT).toBeGreaterThanOrEqual(PANE_LABEL_BAND_PX);
    expect(topLevelClearsLabel(60)).toBe(false); // a shorter pane would collide -- the guard is meaningful
  });
});

describe("extendAutoscale", () => {
  const info = (min: number, max: number) => ({ priceRange: { minValue: min, maxValue: max } });

  it("widens the range to include every level (a line is never outside the scale)", () => {
    expect(extendAutoscale(info(20, 60), LEVELS.rsi)?.priceRange).toEqual({ minValue: 12, maxValue: 84.75 });
    expect(extendAutoscale(info(5, 35), LEVELS.adx)?.priceRange).toEqual({ minValue: 5, maxValue: 40 });
    expect(extendAutoscale(info(2, 9), LEVELS.wvf)?.priceRange).toEqual({ minValue: 0.4, maxValue: 9 });
  });

  it("never narrows the data's own range", () => {
    expect(extendAutoscale(info(0, 100), LEVELS.rsi)?.priceRange).toEqual({ minValue: 0, maxValue: 100 });
  });

  it("clamps RSI to 0-100 and passes null through", () => {
    expect(extendAutoscale(info(-5, 120), LEVELS.rsi, { min: 0, max: 100 })?.priceRange).toEqual({ minValue: 0, maxValue: 100 });
    expect(extendAutoscale(null, LEVELS.rsi)).toBeNull();
  });
});
