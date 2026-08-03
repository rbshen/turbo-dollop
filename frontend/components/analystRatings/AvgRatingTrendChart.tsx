import { MiniBarChart } from "@/components/charts/MiniBarChart";
import type { RatingHistoryPoint } from "@/lib/api/types";
import { fmtNumber } from "@/lib/format";

interface Props {
  history: RatingHistoryPoint[];
}

// "Average Rating Trend" -- weighted 1 (Strong Sell) - 5 (Strong Buy) score
// per grades-historical month. Unlike avg_price_target (PriceTargetTrendChart),
// this comes straight off FMP's own ready-made monthly series, so it's
// populated from the first load rather than waiting on the snapshot cron.
export function AvgRatingTrendChart({ history }: Props) {
  const hasHistory = history.length > 0;

  if (!hasHistory) {
    return <p className="text-sm text-text-tertiary">No rating history available for this ticker.</p>;
  }

  return (
    <MiniBarChart
      categories={history.map((point) => point.date.slice(0, 7))}
      values={history.map((point) => point.avg_rating)}
      valueFormat={fmtNumber}
      height={140}
    />
  );
}
