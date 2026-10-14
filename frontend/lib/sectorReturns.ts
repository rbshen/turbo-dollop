import type { SectorHeatmapRowOut } from "@/lib/api/types";
import { niceStep } from "@/lib/charts";

// The stored/API window keys are unchanged ("1d" is what the page calls
// "Today"); only the labels are page copy.
export const RETURN_WINDOW_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "1d", label: "Today" },
  { value: "1w", label: "1W" },
  { value: "1m", label: "1M" },
  { value: "3m", label: "3M" },
  { value: "6m", label: "6M" },
  { value: "9m", label: "9M" },
  { value: "ytd", label: "YTD" },
  { value: "1y", label: "1Y" },
];

/** The three charts' starting windows, top to bottom. Not persisted: a reload returns here. */
export const DEFAULT_CHART_WINDOWS: readonly string[] = ["1d", "1w", "1m"];

export function windowLabel(window: string): string {
  return RETURN_WINDOW_OPTIONS.find((o) => o.value === window)?.label ?? window.toUpperCase();
}

export function returnOf(row: SectorHeatmapRowOut, window: string): number | null {
  const value = row.cells[window]?.return_pct;
  return value == null || !Number.isFinite(value) ? null : value;
}

/** Descending by one window's return. Sectors with no value always sink to the bottom;
 * ties keep the incoming (universe) order. */
export function sortByReturn(rows: SectorHeatmapRowOut[], window: string): SectorHeatmapRowOut[] {
  return rows
    .map((row, index) => ({ row, index, value: returnOf(row, window) }))
    .sort((a, b) => {
      if (a.value == null && b.value == null) return a.index - b.index;
      if (a.value == null) return 1;
      if (b.value == null) return -1;
      return b.value - a.value || a.index - b.index;
    })
    .map(({ row }) => row);
}

export interface ReturnAxis {
  min: number;
  max: number;
  ticks: number[];
  /** Decimal places for tick labels (a narrow range needs 1-2, a wide one 0). */
  decimals: number;
}

// Padding on each side of the data range, as a share of its span, so the longest
// bar never touches the plot edge and zero stays inside the axis even when every
// value has the same sign. Floor on the span so an all-zero chart still draws.
const AXIS_PAD = 0.06;
const MIN_SPAN_PP = 0.1;
const TARGET_TICKS = 4;

/** An axis fitted to ONE chart's own values (nulls ignored): always contains 0 and
 * every value, padded, with round-number ticks. */
export function computeReturnAxis(values: ReadonlyArray<number | null>): ReturnAxis {
  const present = values.filter((v): v is number => v != null && Number.isFinite(v));
  const lo0 = Math.min(0, ...present);
  const hi0 = Math.max(0, ...present);
  const span = Math.max(hi0 - lo0, MIN_SPAN_PP);
  const pad = span * AXIS_PAD;
  const lo = lo0 - pad;
  const hi = hi0 + pad;
  const step = niceStep((hi - lo) / TARGET_TICKS);
  const min = Math.floor(lo / step) * step;
  const max = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let i = 0, n = Math.round((max - min) / step); i <= n; i++) ticks.push(round(min + i * step));
  const decimals = step >= 1 ? 0 : step >= 0.1 ? 1 : 2;
  return { min: round(min), max: round(max), ticks, decimals };
}

function round(n: number): number {
  return Math.round(n * 1e9) / 1e9;
}

/** Position of a value along the axis, 0-100 (percent from the left). */
export function axisPercent(value: number, axis: ReturnAxis): number {
  return ((value - axis.min) / (axis.max - axis.min)) * 100;
}

export function fmtAxisTick(value: number, axis: ReturnAxis): string {
  return `${(Math.abs(value) < 1e-9 ? 0 : value).toFixed(axis.decimals)}%`;
}
