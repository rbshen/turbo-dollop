import type { RecommendationDetailsColumn } from "@/lib/api/types";

interface Props {
  /** The "Current" column -- a snapshot, not a time series. */
  column: RecommendationDetailsColumn;
}

// Buy/Outperform/Hold/Underperform/Sell are this app's own established
// relabel of FMP's 5 rating buckets (strongBuy/buy/hold/sell/strongSell --
// see RecommendationDetailsTable's own comment). 5 distinct hues from the
// token set (positive/brand/warn/chart-purple/negative) since the palette
// only defines 3 semantic + 2 accent colors -- no new colors invented.
const SEGMENTS: { key: "buy" | "outperform" | "hold" | "underperform" | "sell"; label: string; color: string }[] = [
  { key: "buy", label: "Buy", color: "var(--color-positive)" },
  { key: "outperform", label: "Outperform", color: "var(--color-brand)" },
  { key: "hold", label: "Hold", color: "var(--color-warn)" },
  { key: "underperform", label: "Underperform", color: "var(--color-chart-purple)" },
  { key: "sell", label: "Sell", color: "var(--color-negative)" },
];

// Plain label/value rows rather than a proportion bar -- precision matters
// more than visual proportion for a 5-bucket breakdown where several
// buckets are commonly 0. Identity color stays on the swatch, never the
// text, matching ChartLegend's own convention.
export function CurrentDistributionList({ column }: Props) {
  return (
    <div className="divide-y divide-border-card">
      {SEGMENTS.map((s) => (
        <div key={s.key} className="flex items-center justify-between py-1.5 text-sm">
          <span className="flex items-center gap-2 text-text-secondary">
            <span className="inline-block size-2.5 shrink-0 rounded-[2px]" style={{ backgroundColor: s.color }} />
            {s.label}
          </span>
          <span className="font-mono font-semibold tabular-nums text-text-primary">{column[s.key]}</span>
        </div>
      ))}
    </div>
  );
}
