import { ChartLegend } from "@/components/charts/ChartLegend";
import { SENTIMENT_BUCKETS } from "@/lib/sentimentColor";
import type { SentimentDistribution } from "@/lib/api/types";

interface Props {
  distribution: SentimentDistribution;
}

export function SentimentDistributionBar({ distribution }: Props) {
  const total = SENTIMENT_BUCKETS.reduce((sum, b) => sum + distribution[b.key], 0);

  return (
    <div className="space-y-3">
      <div className="flex h-3 overflow-hidden rounded-full bg-surface-2">
        {SENTIMENT_BUCKETS.map((b) => {
          const count = distribution[b.key];
          const pct = total > 0 ? (count / total) * 100 : 0;
          return pct > 0 ? <div key={b.key} style={{ width: `${pct}%`, backgroundColor: b.color }} /> : null;
        })}
      </div>
      <ChartLegend
        layout="row"
        items={SENTIMENT_BUCKETS.map((b) => ({ key: b.key, label: `${b.label} (${distribution[b.key]})`, color: b.color }))}
      />
    </div>
  );
}
