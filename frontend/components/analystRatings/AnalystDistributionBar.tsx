import { ChartLegend } from "@/components/charts/ChartLegend";
import type { RecommendationDetailsColumn } from "@/lib/api/types";

interface Props {
  /** The "Current" column -- a snapshot, not a time series. */
  column: RecommendationDetailsColumn;
}

// Buy/Outperform/Hold/Underperform/Sell are this app's own established
// relabel of FMP's 5 rating buckets (strongBuy/buy/hold/sell/strongSell --
// see RecommendationDetailsTable's own comment), reused here rather than
// inventing "Strong Buy"/"Strong Sell" text just because the design
// handoff's own mockup happened to use those generic placeholder labels.
// 5 distinct hues from the token set (positive/brand/warn/chart-purple/
// negative) since the palette only defines 3 semantic + 2 accent colors --
// no new colors invented.
const SEGMENTS: { key: "buy" | "outperform" | "hold" | "underperform" | "sell"; label: string; color: string }[] = [
  { key: "buy", label: "Buy", color: "var(--color-positive)" },
  { key: "outperform", label: "Outperform", color: "var(--color-brand)" },
  { key: "hold", label: "Hold", color: "var(--color-warn)" },
  { key: "underperform", label: "Underperform", color: "var(--color-chart-purple)" },
  { key: "sell", label: "Sell", color: "var(--color-negative)" },
];

export function AnalystDistributionBar({ column }: Props) {
  const total = SEGMENTS.reduce((sum, s) => sum + column[s.key], 0);

  return (
    <div className="space-y-3">
      <div className="flex h-3 overflow-hidden rounded-full bg-surface-2">
        {SEGMENTS.map((s) => {
          const count = column[s.key];
          const pct = total > 0 ? (count / total) * 100 : 0;
          return pct > 0 ? <div key={s.key} style={{ width: `${pct}%`, backgroundColor: s.color }} /> : null;
        })}
      </div>
      <ChartLegend layout="row" items={SEGMENTS.map((s) => ({ key: s.key, label: `${s.label} (${column[s.key]})`, color: s.color }))} />
    </div>
  );
}
