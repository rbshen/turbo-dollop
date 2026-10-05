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

// The chart-*/stage-* tokens above are authored directly as hex in globals.css's ".dark" block (e.g.
// `--fathom-chart-up: #10b981;`), so getComputedStyle always returns them as plain, unambiguous hex text -- safe
// to hand straight to lightweight-charts. The four CHROME keys below (page/textSecondary/borderCard/borderSubtle)
// are different: they're authored as oklch(...), and Tailwind's build (Lightning CSS) emits TWO declarations for
// each -- a plain hex fallback, then an oklch-derived `lab(...)` override for browsers that support it:
//   --fathom-page:#080b11;
//   --fathom-page:lab(3.01452% -.187993 -3.12249);
// A browser that parses the second wins the cascade, so getComputedStyle returns the LAB string, not the hex.
// Confirmed live (2026-09-28, Safari/macOS): lightweight-charts' own color parser -- getComputedStyle on a scratch
// element, matched against a strict rgb()/rgba() regex -- can't parse that `lab(...)` string and throws
// ("Failed to parse color: lab(62.840099 -0.596315 -4.46798)"), crashing the whole Chart tab on mount. A first
// attempt normalized every resolved value through a canvas 2D `fillStyle` get/set (spec-guaranteed to canonicalize
// any color canvas can parse) before handing it to the chart -- also failed on the same Safari build: its canvas
// fillStyle setter doesn't accept `lab(...)` either, so the round-trip silently no-ops and the raw lab() string
// still reaches lightweight-charts unchanged. Every browser-based normalization route (DOM computed-style, canvas
// fillStyle) is therefore unreliable for this specific CSS Color 4 syntax, on at least one real, current browser.
//
// Fix: these four are a documented, permanent literal exception, exactly like WEINSTEIN_MA_COLOR in
// lib/chartWeinstein.ts -- never resolved from `--fathom-*` at all, always this hex (the same value Tailwind's own
// hex fallback declares, i.e. the accurate sRGB rendering of the oklch source -- not a guess). This is safe
// because this app is dark-only with no live re-theming: these four values cannot change at runtime, so nothing
// is lost by not reading them from the DOM.
const CHART_CHROME: Pick<ChartColors, "page" | "textSecondary" | "borderCard" | "borderSubtle"> = {
  page: "#080b11",
  textSecondary: "#9499a0",
  borderCard: "#292e36",
  borderSubtle: "#20242b",
};

// The only place raw color literals may remain for the CSS-resolved (chart-*/stage-*) tokens -- used whenever the
// corresponding `--fathom-*` custom property resolves empty (server-side render, jsdom/vitest, or a token
// genuinely missing from the page). Values are the exact legacy palette these tokens were introduced to carry.
const FALLBACK_COLORS: Omit<ChartColors, keyof typeof CHART_CHROME> = {
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
  chartWarrenYellow: "#FFFF00",
  chartWarrenGray: "#A1A1AA",
  chartEventEarnings: "#22D3EE",
  chartEventDividend: "#A78BFA",
  stageBase: "#8FD99F",
  stageAdvance: "#1B9E3E",
  stageTop: "#E8A020",
  stageDecline: "#E03A3A",
};

const CSS_VAR_NAME: Record<keyof typeof FALLBACK_COLORS, string> = {
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
};

/** Resolves every named chart color token. The 18 chart- and stage-prefixed tokens are read live from the
 * document root (falling back to FALLBACK_COLORS wherever `document` is unavailable or a token resolves empty);
 * the four chrome tokens are always the fixed CHART_CHROME literal -- see its own comment for why. */
export function readChartColors(): ChartColors {
  if (typeof document === "undefined") return { ...FALLBACK_COLORS, ...CHART_CHROME };
  const styles = getComputedStyle(document.documentElement);
  const result = { ...FALLBACK_COLORS };
  for (const key of Object.keys(CSS_VAR_NAME) as (keyof typeof FALLBACK_COLORS)[]) {
    const value = styles.getPropertyValue(CSS_VAR_NAME[key]).trim();
    if (value) result[key] = value;
  }
  return { ...result, ...CHART_CHROME };
}
