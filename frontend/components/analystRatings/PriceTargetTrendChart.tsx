import { MiniBarChart } from "@/components/charts/MiniBarChart";
import type { RatingHistoryPoint } from "@/lib/api/types";
import { fmtMoney } from "@/lib/format";

interface Props {
  history: RatingHistoryPoint[];
}

// "Average Price Target Trend" bar chart -- one x (period) to one y
// (avg_price_target) value per bar, so it follows the same MiniBarChart
// house style as the Financials tab's Historical Trends grid (thick bars,
// no axis, hover tooltip) rather than a bespoke chart.
export function PriceTargetTrendChart({ history }: Props) {
  const hasPriceTargetHistory = history.some((point) => point.avg_price_target != null);

  if (!hasPriceTargetHistory) {
    return (
      <p className="text-sm text-text-tertiary">
        Price target history hasn&apos;t accumulated yet — this fills in as the monthly snapshot job runs.
      </p>
    );
  }

  return (
    <MiniBarChart
      categories={history.map((point) => point.date.slice(0, 7))}
      values={history.map((point) => point.avg_price_target)}
      valueFormat={fmtMoney}
      height={140}
    />
  );
}
