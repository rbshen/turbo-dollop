"use client";

import { ReversalCard } from "@/components/technical/ReversalCard";
import { fmtSwingDate } from "@/components/technical/ChecklistCard";
import { TrendContinuationCard } from "@/components/technical/TrendContinuationCard";
import { WeinsteinStageCard } from "@/components/technical/WeinsteinStageCard";
import { useTrendAnalysis } from "@/lib/hooks/useTrendAnalysis";
import { formatWeinsteinSince, WEINSTEIN_STAGE_LABEL, WEINSTEIN_STAGE_TEXT_CLASS } from "@/lib/weinsteinStage";
import type { TrendAnalysisOut } from "@/lib/api/types";

interface Props {
  ticker: string;
}

const TREND_STATE_LABEL: Record<TrendAnalysisOut["trend_state"], string> = {
  uptrend: "Uptrend",
  downtrend: "Downtrend",
};

const REGIME_LABEL: Record<string, string> = {
  trending: "Trending",
  "range-bound": "Range-bound",
};

function SummaryStat({ label, value, valueClassName }: { label: string; value: string; valueClassName?: string }) {
  return (
    <div className="min-w-[7rem] space-y-1">
      <p className="text-xs uppercase tracking-widest text-text-tertiary">{label}</p>
      <p className={`font-mono text-sm font-semibold tabular-nums ${valueClassName ?? "text-text-primary"}`}>{value}</p>
    </div>
  );
}

function SummaryStrip({ data }: { data: TrendAnalysisOut }) {
  return (
    <div className="flex flex-wrap gap-x-8 gap-y-4 rounded-lg border border-border-card bg-surface p-6">
      <SummaryStat
        label="Trend"
        value={TREND_STATE_LABEL[data.trend_state]}
        valueClassName={data.trend_state === "uptrend" ? "text-positive" : "text-negative"}
      />
      <SummaryStat label="Last confirmed swing" value={data.last_confirmed_swing ? fmtSwingDate(data.last_confirmed_swing.date) : "—"} />
      <SummaryStat label="Persistence" value={String(data.persistence_count)} />
      <SummaryStat label="Bars since confirmation" value={data.bars_since_confirmation != null ? String(data.bars_since_confirmation) : "—"} />
      <SummaryStat label="Regime" value={data.regime ? (REGIME_LABEL[data.regime] ?? data.regime) : "—"} />
      <SummaryStat
        label="Stage"
        value={data.weinstein_stage ? WEINSTEIN_STAGE_LABEL[data.weinstein_stage] : "—"}
        valueClassName={data.weinstein_stage ? WEINSTEIN_STAGE_TEXT_CLASS[data.weinstein_stage] : undefined}
      />
      <SummaryStat
        label="Since"
        value={
          data.weinstein_stage && data.weinstein_stage_since_date
            ? formatWeinsteinSince(data.weinstein_stage_since_date, data.weinstein_stage_since_is_lower_bound ?? false, fmtSwingDate)
            : "—"
        }
      />
    </div>
  );
}

export function TechnicalTab({ ticker }: Props) {
  const { data, error, isLoading } = useTrendAnalysis(ticker);

  if (error) {
    return <p className="py-6 text-sm text-negative">Couldn&apos;t load Technical — {error.message}</p>;
  }

  if (isLoading) {
    return <p className="py-6 text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }

  // Resolved (not still loading) but null: this ticker has never been
  // through the nightly trend-structure calculation (see
  // pipeline/nightly_trend_calculation.py) and Yahoo Finance had nothing to
  // compute from on demand either -- distinct from "still loading," so it
  // gets its own explanatory state rather than the same spinner forever.
  if (!data) {
    return <p className="py-6 text-sm text-text-tertiary">No technical analysis available for {ticker} yet.</p>;
  }

  return (
    <div className="space-y-4 py-6">
      <div>
        <h2 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">Technical</h2>
        <p className="mt-1 text-sm text-text-secondary">
          Price-structure analysis (swing highs/lows, break-of-structure, conviction) sourced from Yahoo Finance --
          entirely independent of Steps 1-5 / Overall Assessment. Informational only.
        </p>
      </div>

      <SummaryStrip data={data} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ReversalCard data={data} />
        <TrendContinuationCard data={data} />
      </div>

      <WeinsteinStageCard data={data} />
    </div>
  );
}
