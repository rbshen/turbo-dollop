import { ChartLegend } from "@/components/charts/ChartLegend";
import { RechartsStackedChart, type ChartSeries } from "@/components/charts/RechartsStackedChart";
import { computeNiceTicks } from "@/lib/charts";
import type { RatingHistoryPoint } from "@/lib/api/types";
import { fmtPlainPct } from "@/lib/format";

interface Props {
  history: RatingHistoryPoint[];
}

// Same 5-bucket Buy/Outperform/Hold/Underperform/Sell palette as
// CurrentDistributionList's own breakdown -- kept in sync by convention
// (see that component's own comment), not a shared import. Not collapsed
// to 3 buckets the way ConsensusBanner's own summary is -- see
// RatingHistoryPoint's schema comment for why.
const SERIES: ChartSeries[] = [
  { key: "buy_pct", label: "Buy", color: "var(--color-positive)" },
  { key: "outperform_pct", label: "Outperform", color: "var(--color-brand)" },
  { key: "hold_pct", label: "Hold", color: "var(--color-warn)" },
  { key: "underperform_pct", label: "Underperform", color: "var(--color-chart-purple)" },
  { key: "sell_pct", label: "Sell", color: "var(--color-negative)" },
];

// "Recommendation Trend" -- Buy/Outperform/Hold/Underperform/Sell % of
// analyst coverage per grades-historical month, stacked to 100%.
export function RatingDistributionTrendChart({ history }: Props) {
  if (history.length === 0) {
    return <p className="text-sm text-text-tertiary">No rating history available for this ticker.</p>;
  }

  const categories = history.map((point) => point.date.slice(0, 7));
  const values = {
    buy_pct: history.map((point) => point.buy_pct),
    outperform_pct: history.map((point) => point.outperform_pct),
    hold_pct: history.map((point) => point.hold_pct),
    underperform_pct: history.map((point) => point.underperform_pct),
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
