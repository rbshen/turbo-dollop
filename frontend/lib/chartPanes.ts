import type { ChartOut } from "@/lib/api/types";

// Which sub-panes sit under the Chart tab's price pane, per range. The daily/weekly ranges keep their RSI(14) and
// Full Stochastic panes (each only when its series has data); the 2H·90D range replaces them with three panes drawn
// from the backend's Warren series -- RSI, ADX with +DI/-DI, and WVF -- so the panes always match the arrows.

export type PaneId = "rsi" | "stochastic" | "warren-rsi" | "warren-adx" | "warren-wvf";

export interface PaneLegendItem {
  text: string;
  /** Tailwind text color class (a design-system chart token) matching the series' color. */
  className: string;
}

export interface PaneSpec {
  id: PaneId;
  label: string;
  /** Pixel height used as the pane's stretch factor (ratios), like the main pane's. */
  height: number;
  legend?: PaneLegendItem[];
}

export const MAIN_PANE_HEIGHT = 580;
export const SUB_PANE_HEIGHT = 100;
// lightweight-charts' fixed pane-separator height.
export const PANE_SEPARATOR_HEIGHT = 1;

/** Formats a reference level for a pane label: integers bare, others with two decimals (0.4 -> "0.40"). */
export function formatLevel(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}

type PaneData = Pick<
  ChartOut,
  "timeframe" | "rsi" | "stochastic" | "warren_rsi" | "warren_adx" | "warren_plus_di" | "warren_minus_di" | "warren_wvf" | "warren_levels"
>;

export function subPaneSpecs(data: PaneData): PaneSpec[] {
  if (data.timeframe === "2h") {
    const levels = data.warren_levels;
    const specs: PaneSpec[] = [];
    if (data.warren_rsi.length > 0) {
      const lv = levels ? ` · ${levels.rsi.map(formatLevel).join(" · ")}` : "";
      specs.push({ id: "warren-rsi", label: `Warren RSI (14)${lv}`, height: SUB_PANE_HEIGHT });
    }
    if (data.warren_adx.length > 0) {
      const lv = levels ? ` · ${levels.adx.map(formatLevel).join(" · ")}` : "";
      specs.push({
        id: "warren-adx",
        label: `Warren ADX (14)${lv}`,
        height: SUB_PANE_HEIGHT,
        legend: [
          { text: "ADX", className: "text-chart-ema21" },
          { text: "+DI", className: "text-chart-up" },
          { text: "-DI", className: "text-chart-down" },
        ],
      });
    }
    if (data.warren_wvf.length > 0) {
      const lv = levels ? ` · ${levels.wvf.map(formatLevel).join(" · ")}` : "";
      specs.push({ id: "warren-wvf", label: `Warren WVF (22)${lv}`, height: SUB_PANE_HEIGHT });
    }
    return specs;
  }
  const specs: PaneSpec[] = [];
  if (data.rsi.length > 0) specs.push({ id: "rsi", label: "RSI (14)", height: SUB_PANE_HEIGHT });
  if (data.stochastic.length > 0) specs.push({ id: "stochastic", label: "Full Stochastic (5, 3, 3) EMA", height: SUB_PANE_HEIGHT });
  return specs;
}

/** Total chart height: the main pane plus each sub-pane and its separator. */
export function totalChartHeight(specs: PaneSpec[]): number {
  return MAIN_PANE_HEIGHT + specs.reduce((sum, s) => sum + PANE_SEPARATOR_HEIGHT + s.height, 0);
}

/** Pre-layout label tops (the chart's real post-layout geometry overwrites them): the sum of every pane above plus
 * a separator per pane boundary. Index k is the k-th sub-pane (pane index k+1). */
export function nominalLabelTops(specs: PaneSpec[]): number[] {
  const tops: number[] = [];
  let y = MAIN_PANE_HEIGHT + PANE_SEPARATOR_HEIGHT;
  for (const s of specs) {
    tops.push(y);
    y += s.height + PANE_SEPARATOR_HEIGHT;
  }
  return tops;
}

// Room reserved at the top of each 2H sub-pane (as a price-scale margin) so its label (top-left, 10px text) never
// sits on a reference line: autoscale always includes every reference level (extendAutoscale), so the highest line
// can be no closer to the pane top than margin * height pixels. 0.22 * 100px = 22px against a label that ends about
// 16px down -- a structural guarantee, independent of the data.
export const SUB_PANE_SCALE_MARGINS_2H = { top: 0.22, bottom: 0.08 };
export const PANE_LABEL_BAND_PX = 18;

export function topLevelClearsLabel(paneHeight: number, topMargin: number = SUB_PANE_SCALE_MARGINS_2H.top): boolean {
  return topMargin * paneHeight >= PANE_LABEL_BAND_PX;
}

export interface AutoscaleInfo {
  priceRange: { minValue: number; maxValue: number };
  margins?: { above: number; below: number };
}

/** Widens a series' autoscale range to include every reference level (and optionally clamps it), so the lines are
 * always inside the visible scale. Pure; TickerChart wires it into `autoscaleInfoProvider`. */
export function extendAutoscale(info: AutoscaleInfo | null, levels: number[], clamp?: { min?: number; max?: number }): AutoscaleInfo | null {
  if (!info) return info;
  let min = Math.min(info.priceRange.minValue, ...levels);
  let max = Math.max(info.priceRange.maxValue, ...levels);
  if (clamp?.min !== undefined) min = Math.max(min, clamp.min);
  if (clamp?.max !== undefined) max = Math.min(max, clamp.max);
  return { ...info, priceRange: { minValue: min, maxValue: max } };
}
