import { PriceTargetRecencyCard } from "@/components/analystRatings/PriceTargetRecencyCard";
import { PriceTargetTrendChart } from "@/components/analystRatings/PriceTargetTrendChart";
import type { PriceTargetRecencyBucket, RatingHistoryPoint } from "@/lib/api/types";

interface Props {
  history: RatingHistoryPoint[];
  recency: PriceTargetRecencyBucket[];
  currency?: string;
}

// Merges the old separate "Average Price Target Trend" chart card and
// "Price Target by Recency" card into one -- the recency strip sits below
// the chart, separated by a top border only rather than its own bordered
// card.
export function PriceTargetTrendCard({ history, recency, currency = "USD" }: Props) {
  return (
    <div className="space-y-3 rounded-lg border border-border-card bg-surface p-6">
      <h2 className="font-heading text-sm font-semibold text-text-primary">Average Price Target Trend</h2>
      <PriceTargetTrendChart history={history} currency={currency} />
      <div className="border-t border-border-card pt-4">
        <PriceTargetRecencyCard data={recency} currency={currency} />
      </div>
    </div>
  );
}
