import { MetricTile } from "@/components/ui/section";
import type { MarketBreadthPointOut } from "@/lib/api/types";
import { fmtBreadthPct, fmtSignedCount } from "@/lib/marketBreadth";
import { pnlClass } from "@/lib/format";

interface Props {
  latest: MarketBreadthPointOut;
}

// The latest session's four readings. The note lines carry the denominators so a percentage is never
// shown without what it is a percentage of.
export function MarketBreadthStats({ latest }: Props) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <MetricTile
        label="Above 20-day SMA"
        value={fmtBreadthPct(latest.pct_above_sma20)}
        note={latest.sma20_eligible == null ? "Not computed yet" : `${latest.sma20_above} of ${latest.sma20_eligible} stocks`}
      />
      <MetricTile
        label="Above 50-day SMA"
        value={fmtBreadthPct(latest.pct_above_sma50)}
        note={`${latest.sma50_above} of ${latest.sma50_eligible} stocks`}
      />
      <MetricTile
        label="Above 200-day SMA"
        value={fmtBreadthPct(latest.pct_above_sma200)}
        note={`${latest.sma200_above} of ${latest.sma200_eligible} stocks`}
      />
      <MetricTile
        label="Net new 52-week highs"
        value={<span className={pnlClass(latest.net_new_highs)}>{fmtSignedCount(latest.net_new_highs)}</span>}
        note={`${latest.new_highs} highs · ${latest.new_lows} lows`}
      />
    </div>
  );
}
