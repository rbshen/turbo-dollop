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

// Room beyond the longest bar on each side, as a share of that side's extent.
const AXIS_PAD = 0.06;
// Floor on the axis extent so an all-zero / all-n/a chart still draws.
const MIN_EXTENT_PP = 0.1;
const TARGET_TICKS = 4;
/** Where the shared zero line may sit, as a fraction of the plot width: never jammed against an edge. */
export const ZERO_MIN = 0.12;
export const ZERO_MAX = 0.88;
const ZERO_DEFAULT = 0.5;

function present(values: ReadonlyArray<number | null>): number[] {
  return values.filter((v): v is number => v != null && Number.isFinite(v));
}

/** L = size of the most negative value (0 if none), R = the most positive (0 if none). */
function extents(values: ReadonlyArray<number | null>): { left: number; right: number } {
  const v = present(values);
  return { left: Math.max(0, ...v.map((x) => -x)), right: Math.max(0, ...v) };
}

/** The ONE zero position (fraction of plot width, 0-1) shared by every chart on the page:
 * max over the charts of L / (L + R), clamped to [ZERO_MIN, ZERO_MAX]. A chart with nothing
 * to draw (all n/a or all zero, L + R = 0) puts no constraint on it; with no chart drawing
 * anything the zero is centred. All-positive charts contribute 0, all-negative 1. */
export function computeSharedZero(charts: ReadonlyArray<ReadonlyArray<number | null>>): number {
  const fractions = charts
    .map(extents)
    .filter(({ left, right }) => left + right > 0)
    .map(({ left, right }) => left / (left + right));
  if (fractions.length === 0) return ZERO_DEFAULT;
  return Math.min(ZERO_MAX, Math.max(ZERO_MIN, Math.max(...fractions)));
}

/** One chart's axis, with zero fixed at `zero` (the shared fraction): its own scale
 * (percentage points across the plot) is the smallest that fits the longest negative bar
 * in the `zero` share to the left and the longest positive bar in the rest, plus padding.
 * Ticks are round numbers (1/2/5 steps) on both sides of zero. A small-range chart gets a
 * tight scale; zero does not move. */
export function computeReturnAxis(values: ReadonlyArray<number | null>, zero: number): ReturnAxis {
  const z = Math.min(ZERO_MAX, Math.max(ZERO_MIN, Number.isFinite(zero) ? zero : ZERO_DEFAULT));
  const { left, right } = extents(values);
  const total = Math.max(MIN_EXTENT_PP, Math.max(left / z, right / (1 - z)) * (1 + AXIS_PAD));
  const min = -z * total;
  const max = (1 - z) * total;
  const step = tickStep(total, min, max, left > 0, right > 0);
  const ticks: number[] = [];
  for (let k = Math.ceil(min / step - 1e-9); k <= Math.floor(max / step + 1e-9); k++) ticks.push(round(k * step));
  const decimals = step >= 1 ? 0 : step >= 0.1 ? 1 : 2;
  return { min, max, ticks, decimals };
}

// The step below `step` on the 1/2/5 ladder (5 -> 2 -> 1 -> 0.5 ...).
function lowerStep(step: number): number {
  const magnitude = Math.pow(10, Math.floor(Math.log10(step) + 1e-9));
  const residual = Math.round(step / magnitude);
  if (residual >= 5) return 2 * magnitude;
  if (residual >= 2) return magnitude;
  return 5 * (magnitude / 10);
}

const MAX_TICKS = 10;

/** About TARGET_TICKS round steps across the axis; if a side that has data would get no tick
 * (a coarse step on the short side of an off-centre zero), step down the 1/2/5 ladder until it
 * does, unless that would crowd the axis past MAX_TICKS (then keep the coarser step). */
function tickStep(total: number, min: number, max: number, hasLeft: boolean, hasRight: boolean): number {
  let step = niceStep(total / TARGET_TICKS);
  while ((hasLeft && -min < step) || (hasRight && max < step)) {
    const next = lowerStep(step);
    if (total / next + 1 > MAX_TICKS) break;
    step = next;
  }
  return step;
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
