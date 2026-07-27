import type { PriceTargetSummary } from "@/lib/api/types";
import { fmtMoney, fmtPct, pnlClass } from "@/lib/format";

interface Props {
  data: PriceTargetSummary;
}

export function AvgTargetCard({ data }: Props) {
  return (
    <div className="space-y-1 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
      <p className="text-xs uppercase tracking-widest text-zinc-500">Average Price Target</p>
      <p className="font-mono text-3xl font-bold tabular-nums text-zinc-100">
        {data.target_consensus != null ? fmtMoney(data.target_consensus) : "—"}
      </p>
      {data.upside_pct != null ? (
        <p className={`text-sm ${pnlClass(data.upside_pct)}`}>{fmtPct(data.upside_pct, 1)} vs. current price</p>
      ) : (
        <p className="text-sm text-zinc-600">Current price unavailable</p>
      )}
    </div>
  );
}
