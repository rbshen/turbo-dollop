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
