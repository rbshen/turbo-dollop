import type { PriceTargetSummary } from "@/lib/api/types";
import { fmtMoney, fmtPct, pnlClass } from "@/lib/format";

interface Props {
  data: PriceTargetSummary;
}

function upsidePct(target: number | null, current: number | null): number | null {
  if (target == null || current == null || current === 0) return null;
  return (target / current - 1) * 100;
}

const ROWS: { key: "target_high" | "target_median" | "target_low"; label: string }[] = [
  { key: "target_high", label: "High" },
  { key: "target_median", label: "Median" },
  { key: "target_low", label: "Low" },
];

export function PriceTargetRangeCard({ data }: Props) {
  return (
    <div className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
      <p className="text-xs uppercase tracking-widest text-zinc-500">Price Target Range</p>
      <div className="grid grid-cols-3 gap-4">
        {ROWS.map((row) => {
          const value = data[row.key];
          const pct = upsidePct(value, data.current_price);
          return (
            <div key={row.key} className="space-y-1">
              <p className="text-xs text-zinc-500">{row.label}</p>
              <p className="font-mono text-lg font-semibold tabular-nums text-zinc-100">
                {value != null ? fmtMoney(value) : "—"}
              </p>
              {pct != null && <p className={`text-xs ${pnlClass(pct)}`}>{fmtPct(pct, 1)}</p>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
