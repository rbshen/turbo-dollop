import type { SectorHeatmapRowOut } from "@/lib/api/types";

export type SortDirection = "asc" | "desc";

export interface HeatmapSort {
  window: string;
  direction: SortDirection;
}

// Leaders first on the mid-term window: 3M is neither as noisy as 1W nor as
// lagging as 1Y. Open to revision -- header clicks re-sort on any window.
export const DEFAULT_HEATMAP_SORT: HeatmapSort = { window: "3m", direction: "desc" };

const WINDOW_LABELS: Record<string, string> = { "1w": "1W", "1m": "1M", "3m": "3M", "6m": "6M", "9m": "9M", ytd: "YTD", "1y": "1Y" };

export function windowLabel(window: string): string {
  return WINDOW_LABELS[window] ?? window.toUpperCase();
}

// Each column is colored against its OWN largest move, so a quiet 1W column
// is as legible as a wide 1Y one (a single fixed clamp can't serve both).
// The floor keeps a near-flat column from painting noise at full intensity.
export const MIN_COLUMN_SCALE_PP = 1;

// Tint strength (percent of the token color over transparent) at the
// smallest visible move and at the column's largest.
const MIN_TINT_PCT = 12;
const MAX_TINT_PCT = 62;

/** The magnitude (percentage points) that maps to full tint in `window`'s column. */
export function columnScale(rows: SectorHeatmapRowOut[], window: string): number {
  let max = 0;
  for (const row of rows) {
    const value = row.cells[window]?.return_pct;
    if (value != null && Math.abs(value) > max) max = Math.abs(value);
  }
  return Math.max(max, MIN_COLUMN_SCALE_PP);
}

/** Inline background for one cell, or undefined for a null/flat value (left untinted).
 * Positive/negative tokens, alpha proportional to |value| / scale. */
export function cellBackground(value: number | null, scale: number): string | undefined {
  if (value == null || Math.abs(value) < 0.05) return undefined;
  const intensity = Math.min(1, Math.abs(value) / scale);
  const tint = Math.round(MIN_TINT_PCT + (MAX_TINT_PCT - MIN_TINT_PCT) * intensity);
  const token = value > 0 ? "--color-positive-strong" : "--color-negative";
  return `color-mix(in oklab, var(${token}) ${tint}%, transparent)`;
}

/** Sorts by one window's return. Cells with no value always sink to the bottom,
 * whichever direction; ties keep the incoming (universe) order. */
export function sortHeatmapRows(rows: SectorHeatmapRowOut[], sort: HeatmapSort): SectorHeatmapRowOut[] {
  const sign = sort.direction === "desc" ? -1 : 1;
  return rows
    .map((row, index) => ({ row, index, value: row.cells[sort.window]?.return_pct ?? null }))
    .sort((a, b) => {
      if (a.value == null && b.value == null) return a.index - b.index;
      if (a.value == null) return 1;
      if (b.value == null) return -1;
      return sign * (a.value - b.value) || a.index - b.index;
    })
    .map(({ row }) => row);
}

/** Header click: the active column flips direction; any other column starts descending (best first). */
export function nextSort(current: HeatmapSort, clicked: string): HeatmapSort {
  if (current.window === clicked) return { window: clicked, direction: current.direction === "desc" ? "asc" : "desc" };
  return { window: clicked, direction: "desc" };
}
