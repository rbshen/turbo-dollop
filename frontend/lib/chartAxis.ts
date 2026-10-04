import type { ChartRange } from "@/lib/api/types";

// Shared Chart-tab axis readability options. Four independent toggles, all off by default; with all four off the
// axes are exactly what the chart drew before they existed (every function below returns the original value then).
// Browser-session state only (sessionStorage; no DB, no localStorage), so they survive a tab or ticker change while
// comparing but are off again in a new session.
//
// The options are chart-level config, not 2H-specific: TickerChart applies them to every price scale it was told
// about (see the AxisPane list in TickerChart.tsx). Which ranges offer the dropdown at all is AXIS_OPTION_RANGES --
// extending the toggles to another range is adding it there (and, for the daily/weekly ranges, handing their RSI /
// Stochastic sub-panes to the same AxisPane list; docs/specs/chart-tab.md, "Axis options").

export interface AxisOptions {
  /** Hide any regular tick label that would overlap a price tag (current price, LP levels, a sub-pane's level tag). */
  hideOverlap: boolean;
  /** Brighter axis label color and a larger font. */
  brighter: boolean;
  /** Lower tick density: about twice the spacing between price tick labels. */
  fewerTicks: boolean;
  /** Monospace (equal-width) digits so the numbers line up. */
  tabular: boolean;
}

export const DEFAULT_AXIS_OPTIONS: AxisOptions = {
  hideOverlap: false,
  brighter: false,
  fewerTicks: false,
  tabular: false,
};

export const AXIS_OPTION_ITEMS: { key: keyof AxisOptions; label: string }[] = [
  { key: "hideOverlap", label: "Hide overlapping labels" },
  { key: "brighter", label: "Brighter and larger" },
  { key: "fewerTicks", label: "Fewer ticks" },
  { key: "tabular", label: "Tabular numerals" },
];

const AXIS_STORAGE_KEY = "fathom-chart-axis-options";

export function loadAxisOptions(): AxisOptions {
  if (typeof window === "undefined") return DEFAULT_AXIS_OPTIONS;
  try {
    const raw = window.sessionStorage.getItem(AXIS_STORAGE_KEY);
    if (!raw) return DEFAULT_AXIS_OPTIONS;
    const parsed = JSON.parse(raw);
    const result = { ...DEFAULT_AXIS_OPTIONS };
    for (const key of Object.keys(result) as (keyof AxisOptions)[]) {
      if (typeof parsed?.[key] === "boolean") result[key] = parsed[key];
    }
    return result;
  } catch {
    return DEFAULT_AXIS_OPTIONS;
  }
}

export function saveAxisOptions(options: AxisOptions) {
  try {
    window.sessionStorage.setItem(AXIS_STORAGE_KEY, JSON.stringify(options));
  } catch {
    // Storage unavailable: the in-memory state still applies for this page view.
  }
}

/** Ranges that offer the Axis dropdown. Anything else is told DEFAULT_AXIS_OPTIONS, i.e. behaves as it always did. */
export const AXIS_OPTION_RANGES: ReadonlySet<ChartRange> = new Set<ChartRange>(["2H_90D"]);

export function axisOptionsOffered(range: ChartRange): boolean {
  return AXIS_OPTION_RANGES.has(range);
}

/** What the chart is told: the user's choices on a range that offers them, all off on every other range. */
export function effectiveAxisOptions(options: AxisOptions, range: ChartRange): AxisOptions {
  return axisOptionsOffered(range) ? options : DEFAULT_AXIS_OPTIONS;
}

// --- Font and color (chart-wide: lightweight-charts has one `layout` for every price scale AND the time axis) ---

export const AXIS_FONT_SIZE = 12;
export const AXIS_FONT_SIZE_LARGER = 14;
/** The design system's text-primary (oklch(93% 0.006 260)) as the plain hex Tailwind's fallback declaration carries;
 * a literal for the same reason the other chrome colors are (lib/chartTokens.ts: lab() is not parseable). */
export const AXIS_TEXT_BRIGHTER = "#e5e8ec";
/** The chart's original axis font stack (what the chart has always been created with). */
export const AXIS_FONT_FAMILY = "var(--font-mono), ui-monospace, monospace";
const MONO_FALLBACK = "ui-monospace, monospace";

/** The page's concrete monospace family (the next/font `--font-mono` value), e.g. `'IBM Plex Mono', 'IBM Plex Mono
 * Fallback'`. A canvas `ctx.font` cannot resolve `var(...)`, so the tabular option names the family itself. Client
 * only (reads `document`); empty-safe where it can't resolve. */
export function readMonoFontFamily(): string {
  if (typeof document === "undefined") return MONO_FALLBACK;
  const resolved = getComputedStyle(document.documentElement).getPropertyValue("--font-mono").trim();
  return resolved ? `${resolved}, ${MONO_FALLBACK}` : MONO_FALLBACK;
}

export interface AxisLayout {
  textColor: string;
  fontSize: number;
  fontFamily: string;
}

export function axisLayout(options: AxisOptions, baseTextColor: string, monoFamily: string): AxisLayout {
  return {
    textColor: options.brighter ? AXIS_TEXT_BRIGHTER : baseTextColor,
    fontSize: options.brighter ? AXIS_FONT_SIZE_LARGER : AXIS_FONT_SIZE,
    fontFamily: options.tabular ? monoFamily : AXIS_FONT_FAMILY,
  };
}

// --- Tick density -----------------------------------------------------------------------------------------------

/** lightweight-charts' own default `tickMarkDensity` (a tick needs ceil(fontSize * density) px of height). */
export const BASE_TICK_MARK_DENSITY = 2.5;
/** Fewer ticks = this many times the minimum pixel spacing between tick labels. The library snaps the resulting
 * price step to a 1/2/2.5/5/10 ladder, so doubling the pixel spacing takes a $5 step to $10 (and $0.50 to $1) at
 * any price level, rather than hardcoding a price step. */
export const FEWER_TICKS_FACTOR = 2;

export function tickMarkDensity(options: AxisOptions): number {
  return options.fewerTicks ? BASE_TICK_MARK_DENSITY * FEWER_TICKS_FACTOR : BASE_TICK_MARK_DENSITY;
}

// --- Overlap ------------------------------------------------------------------------------------------------------

/** Minimum vertical distance (px, center to center) for a tick label and a price tag not to touch: half the tag box
 * (text plus its padding, about fontSize + 8) plus half the tick text (fontSize), rounded up. */
export function overlapClearancePx(fontSize: number): number {
  return Math.ceil(fontSize + 4);
}

/** For each tick (y in px, null = not placeable), whether it lies within `clearance` of any tag y. Pure. */
export function overlappingTicks(tickYs: (number | null)[], tagYs: number[], clearance: number): boolean[] {
  return tickYs.map((y) => y !== null && tagYs.some((t) => Math.abs(y - t) < clearance));
}

/** The default price formatting (what a `price` priceFormat of precision 2 draws): a true minus sign, two decimals. */
export function formatAxisPrice(price: number): string {
  return (price < 0 ? "−" : "") + Math.abs(price).toFixed(2);
}

/** Tick labels with the overlapping ones blanked. `yOf` maps a price to its pane y; `tagPrices` are the prices of
 * the tags currently drawn on that scale. A tick sitting exactly on a tag's price is the tag itself and is hidden too. */
export function tickLabelsHidingOverlap(
  prices: number[],
  yOf: (price: number) => number | null,
  tagPrices: number[],
  clearance: number,
): string[] {
  const tagYs = tagPrices.map(yOf).filter((y): y is number => y !== null);
  const hide = overlappingTicks(prices.map(yOf), tagYs, clearance);
  return prices.map((p, i) => (hide[i] ? "" : formatAxisPrice(p)));
}
