import { fmtSwingDate } from "@/components/technical/ChecklistCard";
import type { TrendAnalysisOut } from "@/lib/api/types";

interface Props {
  data: TrendAnalysisOut;
}

const TREND_STATE_LABEL: Record<TrendAnalysisOut["trend_state"], string> = {
  uptrend: "Uptrend",
  downtrend: "Downtrend",
};

const TREND_STATE_BADGE_CLASS: Record<TrendAnalysisOut["trend_state"], string> = {
  uptrend: "border-positive/40 bg-positive/16 text-positive",
  downtrend: "border-negative/40 bg-negative/16 text-negative",
};

const REGIME_LABEL: Record<string, string> = {
  trending: "Trending",
  "range-bound": "Range-bound",
};

// "Turned up on"/"Turned down on" -- worded per trend direction so the date
// beneath it is never misread as measuring something it doesn't (this is
// last_confirmed_swing's own date, i.e. when the CURRENT trend direction was
// last confirmed or re-confirmed, not necessarily the original flip).
export function turnedOnLabel(trendState: TrendAnalysisOut["trend_state"]): string {
  return trendState === "uptrend" ? "Turned up on" : "Turned down on";
}

function NearTermStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-[9rem] space-y-1">
      <p className="text-xs text-text-tertiary">{label}</p>
      <p className="font-mono text-sm font-semibold tabular-nums text-text-primary">{value}</p>
    </div>
  );
}

export function NearTermCard({ data }: Props) {
  return (
    <div className="space-y-4 rounded-lg border border-border-card bg-surface p-6">
      <div className="space-y-1">
        <p className="text-sm text-text-secondary">Near-term (daily)</p>
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className={`shrink-0 rounded-full border px-3 py-1 text-xs font-semibold ${TREND_STATE_BADGE_CLASS[data.trend_state]}`}>
            {TREND_STATE_LABEL[data.trend_state]}
          </span>
          <span className="text-sm text-text-secondary">· {data.regime ? (REGIME_LABEL[data.regime] ?? data.regime) : "—"}</span>
        </div>
      </div>

      <div className="flex flex-wrap gap-x-8 gap-y-4 border-t border-border-subtle pt-4">
        <NearTermStat
          label={turnedOnLabel(data.trend_state)}
          value={data.last_confirmed_swing ? fmtSwingDate(data.last_confirmed_swing.date) : "—"}
        />
        <NearTermStat label="Confirming moves so far" value={String(data.persistence_count)} />
        <NearTermStat label="Days since last move" value={data.bars_since_confirmation != null ? String(data.bars_since_confirmation) : "—"} />
      </div>
    </div>
  );
}
