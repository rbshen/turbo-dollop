import type { ChartFvgOut } from "@/lib/api/types";

// Pure geometry for the Chart tab's fair value gap overlay (components/chart/FvgZonesPrimitive.ts draws it; backend
// analysis/fvg.py detects it). A zone is a span of whole BAR INDICES (bar i's center is logical i): lightweight-charts 5.2.0's
// timeScale().logicalToCoordinate() returns 0 for any non-integer input (untyped), so the primitive converts the integer
// indices and adds half a bar spacing for the left and right edges itself.

/** Fill alpha of a zone's rectangle, and of its dashed top/bottom edge lines. */
export const FVG_FILL_ALPHA = 0.14;
export const FVG_EDGE_ALPHA = 0.58;

export interface FvgSpan {
  /** Index of the first bar the zone covers: c4. The zone's left edge is this bar's left edge. */
  startIdx: number;
  /** Index of the last bar it covers: the ending bar, or the last bar for an open zone. Its right edge is the zone's right edge. */
  endIdx: number;
}

/** The zone's bar-index span over `barTimes` (the chart's bar times, oldest first), or null when it can't be placed (a
 * start or end time that isn't a bar). Wire format (ChartFvgOut): a null `end_time` is an open zone, drawn to the last
 * bar's right edge; when its `start_time` is after the last bar (c3 was the last bar, there is no c4 yet) it is the
 * one-bar span at index n (the bar count), one bar to the right of the last bar. */
export function fvgSpan(fvg: Pick<ChartFvgOut, "start_time" | "end_time">, barTimes: readonly string[]): FvgSpan | null {
  const n = barTimes.length;
  if (n === 0) return null;
  const indexOf = (t: string) => barTimes.indexOf(t);
  const start = indexOf(fvg.start_time);
  if (fvg.end_time === null) {
    if (start >= 0) return { startIdx: start, endIdx: n - 1 };
    if (fvg.start_time > barTimes[n - 1]) return { startIdx: n, endIdx: n };
    return null;
  }
  const end = indexOf(fvg.end_time);
  if (start < 0 || end < 0 || end < start) return null;
  return { startIdx: start, endIdx: end };
}

/** The zone's x extent in pixels from the converted CENTERS of its first and last bar (`xStart`, `xEnd`, from
 * logicalToCoordinate at integer indices) and the bar spacing (`xOne - xZero`, the centers of logical 1 and 0): left edge
 * is the first center minus half a spacing, right edge the last center plus half. Null when any input is null. */
export function fvgXEdges(
  xStart: number | null,
  xEnd: number | null,
  xZero: number | null,
  xOne: number | null
): { left: number; right: number } | null {
  if (xStart === null || xEnd === null || xZero === null || xOne === null) return null;
  const half = (xOne - xZero) / 2;
  return { left: xStart - half, right: xEnd + half };
}

export interface FvgRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** The zone's pixel rectangle from its four converted edges, or null when any coordinate is null (a price or logical
 * index the chart can't place) or the box is degenerate. Order-independent: prices map to y descending. */
export function fvgRect(xLeft: number | null, xRight: number | null, yTop: number | null, yBottom: number | null): FvgRect | null {
  if (xLeft === null || xRight === null || yTop === null || yBottom === null) return null;
  const x = Math.min(xLeft, xRight);
  const y = Math.min(yTop, yBottom);
  const width = Math.abs(xRight - xLeft);
  const height = Math.abs(yBottom - yTop);
  if (!(width > 0) || !(height > 0)) return null;
  return { x, y, width, height };
}

/** "#rrggbb" / "#rgb" to an rgba() string at `alpha`; any other color string comes back unchanged. */
export function withAlpha(color: string, alpha: number): string {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(color.trim());
  if (!m) return color;
  const hex = m[1].length === 3 ? m[1].replace(/./g, (c) => c + c) : m[1];
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
