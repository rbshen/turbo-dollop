import type { ChartFvgOut } from "@/lib/api/types";

// Pure geometry for the Chart tab's fair value gap overlay (components/chart/FvgZonesPrimitive.ts draws it; backend
// analysis/fvg.py detects it). Logical coordinates: bar i's CENTER is logical i, its left edge i - 0.5 and its right edge
// i + 0.5, so a zone is a [left, right] span of logical edges that the primitive converts with logicalToCoordinate.

/** Fill alpha of a zone's rectangle, and of its dashed top/bottom edge lines. */
export const FVG_FILL_ALPHA = 0.14;
export const FVG_EDGE_ALPHA = 0.58;

export interface FvgSpan {
  /** Logical left edge: c4's left edge. */
  left: number;
  /** Logical right edge: the ending bar's right edge, or the last bar's right edge for an open zone. */
  right: number;
}

/** The zone's logical span over `barTimes` (the chart's bar times, oldest first), or null when it can't be placed (a
 * start or end time that isn't a bar). Wire format (ChartFvgOut): a null `end_time` is an open zone, drawn to the last
 * bar's right edge; when its `start_time` is after the last bar (c3 was the last bar, there is no c4 yet) it is drawn
 * one bar wide, one bar to the right of the last bar. */
export function fvgSpan(fvg: Pick<ChartFvgOut, "start_time" | "end_time">, barTimes: readonly string[]): FvgSpan | null {
  const n = barTimes.length;
  if (n === 0) return null;
  const indexOf = (t: string) => barTimes.indexOf(t);
  const start = indexOf(fvg.start_time);
  if (fvg.end_time === null) {
    if (start >= 0) return { left: start - 0.5, right: n - 1 + 0.5 };
    if (fvg.start_time > barTimes[n - 1]) return { left: n - 0.5, right: n + 0.5 };
    return null;
  }
  const end = indexOf(fvg.end_time);
  if (start < 0 || end < 0 || end < start) return null;
  return { left: start - 0.5, right: end + 0.5 };
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
