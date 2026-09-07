"use client";

import { CollapsedTechnicalCard } from "@/components/technical/CollapsedTechnicalCard";
import { LongTermCard } from "@/components/technical/LongTermCard";
import { NearTermCard } from "@/components/technical/NearTermCard";
import { ReversalCard, reversalStatus } from "@/components/technical/ReversalCard";
import { resolutionStatus, TrendContinuationCard } from "@/components/technical/TrendContinuationCard";
import { WeinsteinStageCard } from "@/components/technical/WeinsteinStageCard";
import { useTrendAnalysis } from "@/lib/hooks/useTrendAnalysis";
import { technicalCardScope } from "@/lib/technicalCardScope";
import { buildInterpretation } from "@/lib/technicalInterpretation";

interface Props {
  ticker: string;
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

  const interpretation = buildInterpretation({
    weinsteinStage: data.weinstein_stage,
    trendState: data.trend_state,
    regime: data.regime,
    reversalStatus: reversalStatus(data),
    continuationStatus: resolutionStatus(data),
  });

  const scope = technicalCardScope(data.trend_state);

  return (
    <div className="space-y-4 py-6">
      <div>
        <h2 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">Technical</h2>
        <p className="mt-1 text-sm text-text-secondary">
          Price-structure analysis (swing highs/lows, break-of-structure, conviction). Informational only.
        </p>
        <p className="mt-3 text-sm text-text-primary">{interpretation.join(" ")}</p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <LongTermCard data={data} />
        <NearTermCard data={data} />
      </div>

      <div className="space-y-2">
        {scope.fullCard === "reversal" ? <ReversalCard data={data} /> : <TrendContinuationCard data={data} />}
        <CollapsedTechnicalCard label={scope.collapsedLabel} subline={scope.collapsedSubline} />
      </div>

      <WeinsteinStageCard data={data} />
    </div>
  );
}
