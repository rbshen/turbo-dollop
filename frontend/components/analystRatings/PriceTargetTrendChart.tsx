import { RechartsAreaChart } from "@/components/charts/RechartsAreaChart";
import type { RatingHistoryPoint } from "@/lib/api/types";
import { fmtMoney } from "@/lib/format";

interface Props {
  history: RatingHistoryPoint[];
  currency?: string;
}

// "Average Price Target Trend" -- one x (period) to one y (avg_price_target)
// value per point, rendered as a smooth line + gradient-area chart.
export function PriceTargetTrendChart({ history, currency = "USD" }: Props) {
  const hasPriceTargetHistory = history.some((point) => point.avg_price_target != null);

  if (!hasPriceTargetHistory) {
    return (
      <p className="text-sm text-text-tertiary">
        Price target history hasn&apos;t accumulated yet — this fills in as the monthly snapshot job runs.
      </p>
    );
  }

  return (
    <RechartsAreaChart
      categories={history.map((point) => point.date.slice(0, 7))}
      values={history.map((point) => point.avg_price_target)}
      valueFormat={(v) => fmtMoney(v, currency)}
      height={216}
    />
  );
}
