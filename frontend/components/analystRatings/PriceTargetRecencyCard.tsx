import type { PriceTargetRecencyBucket } from "@/lib/api/types";
import { fmtMoney } from "@/lib/format";

interface Props {
  data: PriceTargetRecencyBucket[];
  currency?: string;
}

// FMP's /price-target-summary -- a ready-made recency-bucketed average
// target, independent of the reconstructed monthly history feeding
// PriceTargetTrendChart. Purely informational, same styling convention as
// PriceTargetsCard.
export function PriceTargetRecencyCard({ data, currency = "USD" }: Props) {
  return (
    <div className="space-y-4 rounded-lg border border-border-card bg-surface p-6">
      <p className="text-xs uppercase tracking-widest text-text-tertiary">Price Target by Recency</p>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {data.map((bucket) => (
          <div key={bucket.label} className="space-y-1">
            <p className="text-xs text-text-tertiary">{bucket.label}</p>
            <p className="font-mono text-lg font-semibold tabular-nums text-text-primary">
              {bucket.avg_price_target != null ? fmtMoney(bucket.avg_price_target, currency) : "—"}
            </p>
            <p className="text-xs text-text-tertiary">
              {bucket.analyst_count} analyst{bucket.analyst_count === 1 ? "" : "s"}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
