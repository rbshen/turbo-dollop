import { SERIES_COLORS } from "@/lib/chartSeries";

// Shared design-system series palette used by the Summary tab's segmentation
// charts (both the historical trend view and the latest-FY snapshot view),
// hoisted here so the two share one segment-name -> color mapping instead
// of drifting from two hardcoded copies. Assigned in descending-contribution
// rank so the most prominent segment always lands on the same hue. Segments
// are dynamic per-company free text, so unlike fixed-metric charts there can
// be more series than fit the 5-color palette -- segmentation_data.py caps
// real segments at 7, cycling back through the 5 series colors for the 6th
// and 7th, and folds any remainder into "Other", which always renders in
// this fixed muted gray rather than a cycled series hue.
export const SEGMENT_COLORS: readonly string[] = SERIES_COLORS;
export const OTHER_COLOR = "#71717a";
export const OTHER_LABEL = "Other";
