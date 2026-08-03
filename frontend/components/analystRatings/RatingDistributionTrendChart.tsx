import { ChartLegend } from "@/components/charts/ChartLegend";
import { RechartsStackedChart, type ChartSeries } from "@/components/charts/RechartsStackedChart";
import { computeNiceTicks } from "@/lib/charts";
import type { RatingHistoryPoint } from "@/lib/api/types";
import { fmtPlainPct } from "@/lib/format";

interface Props {
  history: RatingHistoryPoint[];
}

// Same 3-bucket buy/hold/sell palette as ConsensusBanner and
// AnalystDistributionBar's own collapse -- kept in sync by convention (see
// ConsensusBanner's own comment), not a shared import.
const SERIES: ChartSeries[] = [
  { key: "buy_pct", label: "Buy", color: "var(--color-positive)" },
  { key: "hold_pct", label: "Hold", color: "var(--color-warn)" },
  { key: "sell_pct", label: "Sell", color: "var(--color-negative)" },
];

// "Recommendation Trend" -- buy/hold/sell % of analyst coverage per
// grades-historical month, stacked to 100%. Reads off the same
// RatingHistoryPoint history as AvgRatingTrendChart, just the 3-bucket
// distribution fields instead of the weighted score.
export function RatingDistributionTrendChart({ history }: Props) {
  if (history.length === 0) {
    return <p className="text-sm text-text-tertiary">No rating history available for this ticker.</p>;
  }

  const categories = history.map((point) => point.date.slice(0, 7));
  const values = {
    buy_pct: history.map((point) => point.buy_pct),
    hold_pct: history.map((point) => point.hold_pct),
    sell_pct: history.map((point) => point.sell_pct),
  };
  const yTicks = computeNiceTicks(100);

  return (
    <div className="space-y-3">
      <RechartsStackedChart
        categories={categories}
        series={SERIES}
        values={values}
        yTicks={yTicks}
        yTickFormat={(v) => fmtPlainPct(v, 0)}
        height={140}
      />
      <ChartLegend items={SERIES} layout="row" />
    </div>
  );
}
