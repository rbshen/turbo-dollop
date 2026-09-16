import { PriceTargetRecencyCard } from "@/components/analystRatings/PriceTargetRecencyCard";
import { PriceTargetTrendChart } from "@/components/analystRatings/PriceTargetTrendChart";
import type { PriceTargetRecencyBucket, RatingHistoryPoint } from "@/lib/api/types";
import { fmtMoney } from "@/lib/format";

interface Props {
  history: RatingHistoryPoint[];
  recency: PriceTargetRecencyBucket[];
  currency?: string;
}

// A gap under this is noise (rounding/small-sample wobble between adjacent
// recency windows), not a genuine long-run-vs-recent divergence worth
// calling out.
const RECENCY_ANNOTATION_THRESHOLD_PCT = 3;

// Explains a genuine All-Time vs. recent-window divergence so All-Time
// doesn't read as a data error sitting next to Last Year/Last Month --
// compares against Last Year first (closer in size/shape to a genuine
// long-run baseline), falling back to Last Month only if Last Year itself
// has no data.
function recencyAnnotation(data: PriceTargetRecencyBucket[], currency: string): string | null {
  const byLabel = Object.fromEntries(data.map((b) => [b.label, b]));
  const allTime = byLabel["All Time"];
  const recent = byLabel["Last Year"]?.avg_price_target != null ? byLabel["Last Year"] : byLabel["Last Month"];
  if (allTime?.avg_price_target == null || recent?.avg_price_target == null) return null;

  const diffPct = ((allTime.avg_price_target - recent.avg_price_target) / recent.avg_price_target) * 100;
  if (Math.abs(diffPct) < RECENCY_ANNOTATION_THRESHOLD_PCT) return null;

  const recentLabel = recent.label.toLowerCase();
  const allTimeFmt = fmtMoney(allTime.avg_price_target, currency);
  return diffPct < 0
    ? `Reading this together: the long-run average (${allTimeFmt}) is pulled down by early lower estimates, not a recent downgrade — ${recentLabel}'s analysts are more optimistic than the All-Time figure alone suggests.`
    : `Reading this together: the long-run average (${allTimeFmt}) is pulled up by early higher estimates, not a recent upgrade — ${recentLabel}'s analysts are more conservative than the All-Time figure alone suggests.`;
}

// Merges the old separate "Average Price Target Trend" chart card and
// "Price Target by Recency" card into one -- the recency strip sits below
// the chart, separated by a top border only rather than its own bordered
// card.
export function PriceTargetTrendCard({ history, recency, currency = "USD" }: Props) {
  const annotation = recencyAnnotation(recency, currency);
  return (
    <div className="space-y-3 rounded-lg border border-border-card bg-surface p-6">
      <h2 className="font-heading text-sm font-semibold text-text-primary">Average Price Target Trend</h2>
      <PriceTargetTrendChart history={history} currency={currency} />
      <div className="border-t border-border-card pt-4">
        <PriceTargetRecencyCard data={recency} currency={currency} />
        {annotation && <p className="mt-3 text-xs text-text-tertiary">{annotation}</p>}
      </div>
    </div>
  );
}
