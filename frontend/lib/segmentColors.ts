// Same 8-hue categorical palette used by the Summary tab's segmentation
// charts (both the historical trend view and the latest-FY snapshot view),
// hoisted here so the two share one segment-name -> color mapping instead
// of drifting from two hardcoded copies. Validated dataviz-skill reference
// order, assigned in descending-contribution rank so the most prominent
// segment always lands on the same hue. Segments are dynamic per-company
// free text, so unlike fixed-metric charts there can be more series than
// fit the palette -- segmentation_data.py caps real segments at 7 and folds
// any remainder into "Other", which always renders in this fixed muted gray
// rather than a "generated" 8th/9th hue.
export const SEGMENT_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7"];
export const OTHER_COLOR = "#71717a";
export const OTHER_LABEL = "Other";
