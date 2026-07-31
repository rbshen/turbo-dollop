import type { PriceTargetSummary } from "@/lib/api/types";
import { fmtMoney, fmtPct, pnlClass } from "@/lib/format";

interface Props {
  data: PriceTargetSummary;
}

// Merges the old separate AvgTargetCard + PriceTargetRangeCard into the
// design handoff's single "Low/Average/High" card -- target_median isn't
// part of that 3-figure spec, so it's not shown here (still present in
// PriceTargetSummary/the API response, just not rendered on this card).
const ROWS: { key: "target_low" | "target_consensus" | "target_high"; label: string }[] = [
  { key: "target_low", label: "Low" },
  { key: "target_consensus", label: "Average" },
  { key: "target_high", label: "High" },
];

export function PriceTargetsCard({ data }: Props) {
  return (
    <div className="space-y-4 rounded-lg border border-border-card bg-surface p-6">
      <p className="text-xs uppercase tracking-widest text-text-tertiary">Price Targets</p>
      <div className="grid grid-cols-3 gap-4">
        {ROWS.map((row) => {
          const value = data[row.key];
          return (
            <div key={row.key} className="space-y-1">
              <p className="text-xs text-text-tertiary">{row.label}</p>
              <p className="font-mono text-lg font-semibold tabular-nums text-text-primary">
                {value != null ? fmtMoney(value) : "—"}
              </p>
              {row.key === "target_consensus" &&
                (data.upside_pct != null ? (
                  <p className={`text-xs ${pnlClass(data.upside_pct)}`}>{fmtPct(data.upside_pct, 1)} vs. current</p>
                ) : (
                  <p className="text-xs text-text-tertiary">Current price unavailable</p>
                ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
