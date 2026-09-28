// Shared series-color constants for Recharts charts -- SVG-drawn, so these
// stay CSS var() strings (never resolved to a concrete color in JS; Safari
// cannot parse an oklch()/lab() string handed to a canvas API, which is why
// the lightweight-charts Chart tab has its own separate token-resolution
// path instead of this one).
export const SERIES_COLORS = [
  "var(--color-series-1)",
  "var(--color-series-2)",
  "var(--color-series-3)",
  "var(--color-series-4)",
  "var(--color-series-5)",
] as const;

export const NEGATIVE_COLOR = "var(--color-negative)";
