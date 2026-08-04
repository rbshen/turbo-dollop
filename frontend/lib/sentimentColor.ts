import type { CSSProperties } from "react";

import type { SentimentDistribution } from "@/lib/api/types";

// Reuses the same 5 CSS custom properties AnalystDistributionBar.tsx
// already established as this app's full accent/semantic token set
// (positive/brand/warn/chart-purple/negative) -- no new colors invented.
// Bearish->Bullish is mapped onto the same negative->positive ordering
// that file already uses for Sell->Buy.
export const SENTIMENT_BUCKETS: { key: keyof SentimentDistribution; label: string; color: string }[] = [
  { key: "bearish", label: "Bearish", color: "var(--color-negative)" },
  { key: "somewhat_bearish", label: "Somewhat Bearish", color: "var(--color-chart-purple)" },
  { key: "neutral", label: "Neutral", color: "var(--color-warn)" },
  { key: "somewhat_bullish", label: "Somewhat Bullish", color: "var(--color-brand)" },
  { key: "bullish", label: "Bullish", color: "var(--color-positive)" },
];

const LABEL_TO_BUCKET_KEY: Record<string, keyof SentimentDistribution> = {
  Bearish: "bearish",
  "Somewhat-Bearish": "somewhat_bearish",
  Neutral: "neutral",
  "Somewhat-Bullish": "somewhat_bullish",
  Bullish: "bullish",
};

export function sentimentColorFor(label: string): string {
  const key = LABEL_TO_BUCKET_KEY[label] ?? "neutral";
  return SENTIMENT_BUCKETS.find((b) => b.key === key)!.color;
}

// chart-purple (Somewhat Bearish) has no precedent anywhere in this
// codebase as a Tailwind utility class -- AnalystDistributionBar.tsx only
// ever applies it via inline style. The other 4 buckets use the
// already-precedented bg-x/16 text-x utilities; chart-purple's badge uses
// inline style for both, to stay consistent with that one established
// usage rather than betting on an unverified utility class.
export function sentimentBadgeClass(label: string): string {
  switch (label) {
    case "Bearish":
      return "bg-negative/16 text-negative";
    case "Somewhat-Bullish":
      return "bg-brand/16 text-brand";
    case "Bullish":
      return "bg-positive/16 text-positive";
    case "Somewhat-Bearish":
      return ""; // styled via inline `style`, see sentimentBadgeStyle
    default:
      return "bg-warn/16 text-warn"; // Neutral
  }
}

export function sentimentBadgeStyle(label: string): CSSProperties | undefined {
  if (label !== "Somewhat-Bearish") return undefined;
  return { backgroundColor: "color-mix(in srgb, var(--color-chart-purple) 16%, transparent)", color: "var(--color-chart-purple)" };
}
