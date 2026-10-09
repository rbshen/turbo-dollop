import type { LikelyTotal } from "@/lib/api/types";

export interface LatestPeriod {
  year: string | null;
  values: Record<string, number | null>;
}

/** Slices out the most recent year from one side (product or geographic)
 * of a SegmentationOut payload -- years/values arrays are oldest-first (see
 * backend/segmentation_data.py::_build_segment_series), so the latest
 * disclosed period is always the last element. Returns year: null when the
 * ticker doesn't disclose that breakdown at all. */
export function getLatestPeriod(
  years: string[],
  segments: string[] | null,
  values: Record<string, (number | null)[]>
): LatestPeriod {
  if (!segments || segments.length === 0 || years.length === 0) {
    return { year: null, values: {} };
  }
  const lastIndex = years.length - 1;
  const latestValues: Record<string, number | null> = {};
  for (const name of segments) {
    latestValues[name] = values[name]?.[lastIndex] ?? null;
  }
  return { year: years[lastIndex], values: latestValues };
}

/** "FY2022-2023", "FY2025", "FY2019, FY2021-2023": consecutive fiscal years
 * collapse to a range, in the order given (oldest-first). */
export function formatFiscalYears(years: string[]): string {
  const runs: string[][] = [];
  for (const year of years) {
    const run = runs[runs.length - 1];
    if (run && Number(year) === Number(run[run.length - 1]) + 1) run.push(year);
    else runs.push([year]);
  }
  return runs.map((run) => (run.length === 1 ? `FY${run[0]}` : `FY${run[0]}-${run[run.length - 1]}`)).join(", ");
}

/** One warning sentence per likely-total segment. `noun` is the plural of what
 * is overstated ("bars" on the trend chart, "shares" on the snapshot donut). */
export function likelyTotalMessages(items: LikelyTotal[], noun: "bars" | "shares"): string[] {
  return items
    .filter((item) => item.years.length > 0)
    .map((item) => {
      const singular = noun === "bars" ? "bar" : "share";
      const these = item.years.length === 1 ? `that ${singular}` : `those ${noun}`;
      return `${item.segment} looks like a total in ${formatFiscalYears(item.years)}, so ${these} may be overstated.`;
    });
}
