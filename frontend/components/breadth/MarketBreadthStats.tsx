import type { MarketBreadthPointOut } from "@/lib/api/types";
import { fmtBreadthPct, fmtSignedCount } from "@/lib/marketBreadth";
import { pnlClass } from "@/lib/format";

interface Props {
  latest: MarketBreadthPointOut;
}

function Stat({ label, value, valueClass, detail }: { label: string; value: string; valueClass?: string; detail: string }) {
  return (
    <div className="space-y-1 rounded-lg border border-border-card bg-surface p-6">
      <p className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">{label}</p>
      <p className={`font-mono text-2xl font-semibold tabular-nums ${valueClass ?? "text-text-primary"}`}>{value}</p>
      <p className="text-xs text-text-tertiary">{detail}</p>
    </div>
  );
}

// The latest session's four readings. The detail lines carry the denominators so a percentage is never
// shown without what it is a percentage of.
export function MarketBreadthStats({ latest }: Props) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <Stat
        label="Above 20-day SMA"
        value={fmtBreadthPct(latest.pct_above_sma20)}
        detail={latest.sma20_eligible == null ? "Not computed yet" : `${latest.sma20_above} of ${latest.sma20_eligible} stocks`}
      />
      <Stat
        label="Above 50-day SMA"
        value={fmtBreadthPct(latest.pct_above_sma50)}
        detail={`${latest.sma50_above} of ${latest.sma50_eligible} stocks`}
      />
      <Stat
        label="Above 200-day SMA"
        value={fmtBreadthPct(latest.pct_above_sma200)}
        detail={`${latest.sma200_above} of ${latest.sma200_eligible} stocks`}
      />
      <Stat
        label="Net new 52-week highs"
        value={fmtSignedCount(latest.net_new_highs)}
        valueClass={pnlClass(latest.net_new_highs)}
        detail={`${latest.new_highs} highs · ${latest.new_lows} lows`}
      />
    </div>
  );
}
