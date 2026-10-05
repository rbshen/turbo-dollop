// Chart-tab axis readability, shared by every range.
//
// Three settings are PERMANENT on every chart (price pane and every sub-pane), with no toggle:
//   - Brighter: the axis label color is AXIS_TEXT_COLOR (the size is untouched, 12 px);
//   - Fewer ticks: every price scale uses AXIS_TICK_MARK_DENSITY (twice the library's minimum label spacing);
//   - Tabular numerals: the axis font is the page's concrete monospace family (equal-width digits).
// One option stays a toggle, default off, in the Chart toolbar's "Axis" dropdown so it can be compared before/after:
//   - Hide overlapping labels: blank any regular tick label that would overlap a price tag.
// The toggle is browser-session state only (sessionStorage; no DB, no localStorage).

export interface AxisOptions {
  /** Hide any regular tick label that would overlap a price tag (current price, LP levels, the Weinstein MA, a sub-pane's level tags). */
  hideOverlap: boolean;
}

export const DEFAULT_AXIS_OPTIONS: AxisOptions = {
  hideOverlap: false,
};

export const AXIS_OPTION_ITEMS: { key: keyof AxisOptions; label: string }[] = [{ key: "hideOverlap", label: "Hide overlapping labels" }];

const AXIS_STORAGE_KEY = "fathom-chart-axis-options";

export function loadAxisOptions(): AxisOptions {
  if (typeof window === "undefined") return DEFAULT_AXIS_OPTIONS;
  try {
    const raw = window.sessionStorage.getItem(AXIS_STORAGE_KEY);
    if (!raw) return DEFAULT_AXIS_OPTIONS;
    const parsed = JSON.parse(raw);
    // Only the known keys are read: entries saved when there were five options carry extra fields, which are ignored.
    return { hideOverlap: parsed?.hideOverlap === true };
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

// --- Permanent layout ---------------------------------------------------------------------------------------------

export const AXIS_FONT_SIZE = 12;
/** The design system's text-primary (oklch(93% 0.006 260)) as the plain hex Tailwind's fallback declaration carries;
 * a literal for the same reason the other chrome colors are (lib/chartTokens.ts: lab() is not parseable). */
export const AXIS_TEXT_COLOR = "#e5e8ec";
const MONO_FALLBACK = "ui-monospace, monospace";

/** The page's concrete monospace family (the next/font `--font-mono` value), e.g. `'IBM Plex Mono', 'IBM Plex Mono
 * Fallback'`. A canvas `ctx.font` cannot resolve `var(...)`, so the axis font names the family itself. Client only
 * (reads `document`); falls back to the generic monospace stack where it can't resolve. */
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

export function axisLayout(monoFamily: string): AxisLayout {
  return { textColor: AXIS_TEXT_COLOR, fontSize: AXIS_FONT_SIZE, fontFamily: monoFamily };
}

// --- Tick density -----------------------------------------------------------------------------------------------

/** lightweight-charts' own default `tickMarkDensity` (a tick needs ceil(fontSize * density) px of height). */
export const BASE_TICK_MARK_DENSITY = 2.5;
/** Fewer ticks = this many times the minimum pixel spacing between tick labels. The library snaps the resulting
 * price step to a 1/2/2.5/5/10 ladder, so doubling the pixel spacing takes a $5 step to $10 (and $0.50 to $1) at
 * any price level, rather than hardcoding a price step. */
export const FEWER_TICKS_FACTOR = 2;
export const AXIS_TICK_MARK_DENSITY = BASE_TICK_MARK_DENSITY * FEWER_TICKS_FACTOR;

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

// --- Close axis tags: nudging -------------------------------------------------------------------------------------

/** Height of a price-axis tag in px: the font plus the library's vertical padding (2.5 px each side at 12 px). */
export function axisTagHeightPx(fontSize: number): number {
  return Math.ceil(fontSize + (2 * 2.5 * fontSize) / 12);
}

/** Tag y positions pushed apart just enough that no two tags (each `height` px tall) overlap. A pair closer than
 * `height` is separated symmetrically: the upper tag moves up and the lower tag down by half the shortfall each, the
 * minimum total movement. Tags already clear of each other do not move. Results keep the input order (and so each tag
 * stays tied to its own line); null stays null. The result is clamped to [min, max] so a tag never leaves the pane. */
export function nudgeTagYs(ys: (number | null)[], height: number, min: number, max: number): (number | null)[] {
  const order = ys
    .map((y, i) => ({ y, i }))
    .filter((e): e is { y: number; i: number } => e.y !== null)
    .sort((a, b) => a.y - b.y);
  const pos = order.map((e) => e.y);
  for (let pass = 0; pass < pos.length * 2; pass++) {
    let moved = false;
    for (let k = 1; k < pos.length; k++) {
      const gap = pos[k] - pos[k - 1];
      if (gap < height - 1e-9) {
        const half = (height - gap) / 2;
        pos[k - 1] -= half;
        pos[k] += half;
        moved = true;
      }
    }
    if (!moved) break;
  }
  // Keep inside the pane, then restore spacing against the pane edge (top-down, then bottom-up).
  for (let k = 0; k < pos.length; k++) pos[k] = Math.min(max, Math.max(min, pos[k]));
  for (let k = 1; k < pos.length; k++) pos[k] = Math.max(pos[k], pos[k - 1] + height);
  for (let k = pos.length - 2; k >= 0; k--) pos[k] = Math.min(pos[k], pos[k + 1] - height);
  const out: (number | null)[] = ys.map(() => null);
  order.forEach((e, k) => {
    out[e.i] = pos[k];
  });
  return out;
}
