import type { PeHistoryLatest, PeHistoryPoint } from "@/lib/api/types";
import { computeNiceTicksRange } from "@/lib/charts";

// The y-axis ceiling is 1.15 x the 95th percentile of the VISIBLE values (never more than the largest value), so a
// few outlier days cannot flatten the ticker line. Points above it are clipped by the axis (the tooltip still shows
// the true value) and counted so the chart can say so.
const CEILING_PERCENTILE = 0.95;
const CEILING_HEADROOM = 1.15;

export interface PeYRange {
  ticks: number[];
  domain: [number, number];
  clippedCount: number;
}

export function peYRange(values: number[]): PeYRange {
  const finite = values.filter((v) => Number.isFinite(v) && v > 0).sort((a, b) => a - b);
  if (finite.length === 0) return { ticks: [0, 1], domain: [0, 1], clippedCount: 0 };
  const p95 = finite[Math.min(finite.length - 1, Math.floor(finite.length * CEILING_PERCENTILE))];
  const top = Math.min(finite[finite.length - 1], p95 * CEILING_HEADROOM);
  const ticks = computeNiceTicksRange(0, top);
  const ceiling = ticks[ticks.length - 1] ?? top;
  return {
    ticks,
    domain: [0, ceiling],
    clippedCount: finite.filter((v) => v > ceiling).length,
  };
}

export function fmtPe(latest: PeHistoryLatest | null | undefined): string {
  return latest ? latest.value.toFixed(1) : "n/a";
}

/** "Stock 28.4 · Sector 22.1 · Industry 24.7"; a missing value reads "n/a". */
export function peHeadline(
  latestStock: PeHistoryLatest | null,
  latestSector: PeHistoryLatest | null,
  latestIndustry: PeHistoryLatest | null
): string {
  return `Stock ${fmtPe(latestStock)} · Sector ${fmtPe(latestSector)} · Industry ${fmtPe(latestIndustry)}`;
}

/** Every plotted value of the shown series, for the y-range. */
export function visibleValues(points: PeHistoryPoint[], showSector: boolean, showIndustry: boolean): number[] {
  const out: number[] = [];
  for (const p of points) {
    if (p.stock != null) out.push(p.stock);
    if (showSector && p.sector != null) out.push(p.sector);
    if (showIndustry && p.industry != null) out.push(p.industry);
  }
  return out;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-03-14" -> "Mar 26" (axis tick). */
export function fmtPeMonth(isoDate: string): string {
  const month = Number(isoDate.slice(5, 7));
  return `${MONTHS[month - 1] ?? ""} ${isoDate.slice(2, 4)}`;
}
