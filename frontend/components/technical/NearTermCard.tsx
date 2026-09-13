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

// "Trend started"/"Trending since at least" -- the same lower-bound framing
// Weinstein Stage Analysis already uses for its own stage_since_date (see
// lib/weinsteinStage.ts::formatWeinsteinSince and
// WEINSTEIN_LOWER_BOUND_CAVEAT), applied here to trend_started: a true
// isLowerBound means no genuine flip has occurred anywhere in this ticker's
// available cached history, so the date shown is the earliest we can see,
// not necessarily when the trend actually began.
export function trendStartedLabel(isLowerBound: boolean): string {
  return isLowerBound ? "Trending since at least" : "Trend started";
}

export const TREND_STARTED_LOWER_BOUND_CAVEAT =
  "Our price history starts here — the trend may have begun earlier than this date shows.";

function NearTermStat({ label, value, caption }: { label: string; value: string; caption?: string }) {
  return (
    <div className="min-w-[9rem] space-y-1">
      <p className="text-xs text-text-tertiary">{label}</p>
      <p className="font-mono text-sm font-semibold tabular-nums text-text-primary">{value}</p>
      {caption && <p className="max-w-[16rem] text-[11px] text-text-tertiary">{caption}</p>}
    </div>
  );
}

export function NearTermCard({ data }: Props) {
  const trendStarted = data.trend_started;
  const trendStartedIsLowerBound = data.trend_started_is_lower_bound === true;

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
          label={trendStartedLabel(trendStartedIsLowerBound)}
          value={trendStarted ? fmtSwingDate(trendStarted.date) : "—"}
          caption={trendStarted && trendStartedIsLowerBound ? TREND_STARTED_LOWER_BOUND_CAVEAT : undefined}
        />
        <NearTermStat
          label="Last confirming move"
          value={data.last_confirmed_swing ? fmtSwingDate(data.last_confirmed_swing.date) : "—"}
        />
        <NearTermStat label="Confirming moves so far" value={String(data.persistence_count)} />
        <NearTermStat label="Days since last move" value={data.bars_since_confirmation != null ? String(data.bars_since_confirmation) : "—"} />
      </div>
    </div>
  );
}
