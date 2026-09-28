// Resolves the design system's named --fathom-* color tokens (globals.css's `.dark` block) into plain color
// strings for lightweight-charts and any other canvas-based chart, which need literal color values, not CSS
// custom properties. Only safe to call from a client effect (never at module load, never on the server) --
// it reads `document`.

export interface ChartColors {
  chartUp: string;
  chartDown: string;
  chartEma21: string;
  chartSma50: string;
  chartSma200: string;
  chartStochK: string;
  chartBand: string;
  chartRefline: string;
  chartZoneBrokenSupport: string;
  chartZoneBrokenResistance: string;
  chartWarrenYellow: string;
  chartWarrenGray: string;
  chartEventEarnings: string;
  chartEventDividend: string;
  stageBase: string;
  stageAdvance: string;
  stageTop: string;
  stageDecline: string;
  /** Chart canvas background / page-level chrome. */
  page: string;
  /** Axis label text. */
  textSecondary: string;
  /** Axis lines, pane separators, card borders. */
  borderCard: string;
  borderSubtle: string;
}

// The only place raw color literals may remain for these tokens -- used whenever the corresponding `--fathom-*`
// custom property resolves empty (server-side render, jsdom/vitest, or a token genuinely missing from the page).
// The chart-*/stage-* values are the exact legacy palette these tokens were introduced to carry (globals.css's
// ".dark" block); the four chrome values are that same block's current oklch definitions for
// page/text-secondary/border-card/border-subtle, verbatim.
const FALLBACK_COLORS: ChartColors = {
  chartUp: "#10B981",
  chartDown: "#EF4444",
  chartEma21: "#3179F5",
  chartSma50: "#4CAF50",
  chartSma200: "#F23645",
  chartStochK: "#F23645",
  chartBand: "#808080",
  chartRefline: "#52525B",
  chartZoneBrokenSupport: "#FF9800",
  chartZoneBrokenResistance: "#E040FB",
  chartWarrenYellow: "#F59E0B",
  chartWarrenGray: "#A1A1AA",
  chartEventEarnings: "#22D3EE",
  chartEventDividend: "#A78BFA",
  stageBase: "#8FD99F",
  stageAdvance: "#1B9E3E",
  stageTop: "#E8A020",
  stageDecline: "#E03A3A",
  page: "oklch(15% 0.014 260)",
  textSecondary: "oklch(68% 0.012 260)",
  borderCard: "oklch(30% 0.016 260)",
  borderSubtle: "oklch(26% 0.014 260)",
};

const CSS_VAR_NAME: Record<keyof ChartColors, string> = {
  chartUp: "--fathom-chart-up",
  chartDown: "--fathom-chart-down",
  chartEma21: "--fathom-chart-ema21",
  chartSma50: "--fathom-chart-sma50",
  chartSma200: "--fathom-chart-sma200",
  chartStochK: "--fathom-chart-stoch-k",
  chartBand: "--fathom-chart-band",
  chartRefline: "--fathom-chart-refline",
  chartZoneBrokenSupport: "--fathom-chart-zone-broken-support",
  chartZoneBrokenResistance: "--fathom-chart-zone-broken-resistance",
  chartWarrenYellow: "--fathom-chart-warren-yellow",
  chartWarrenGray: "--fathom-chart-warren-gray",
  chartEventEarnings: "--fathom-chart-event-earnings",
  chartEventDividend: "--fathom-chart-event-dividend",
  stageBase: "--fathom-stage-base",
  stageAdvance: "--fathom-stage-advance",
  stageTop: "--fathom-stage-top",
  stageDecline: "--fathom-stage-decline",
  page: "--fathom-page",
  textSecondary: "--fathom-text-secondary",
  borderCard: "--fathom-border-card",
  borderSubtle: "--fathom-border-subtle",
};

/** Resolves every named chart color token from the document root, once. Falls back to FALLBACK_COLORS wherever
 * `document` is unavailable or a given token resolves empty. */
export function readChartColors(): ChartColors {
  if (typeof document === "undefined") return { ...FALLBACK_COLORS };
  const styles = getComputedStyle(document.documentElement);
  const result = { ...FALLBACK_COLORS };
  for (const key of Object.keys(CSS_VAR_NAME) as (keyof ChartColors)[]) {
    const value = styles.getPropertyValue(CSS_VAR_NAME[key]).trim();
    if (value) result[key] = value;
  }
  return result;
}
