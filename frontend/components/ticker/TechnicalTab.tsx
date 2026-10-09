"use client";

import { BbRsiEntrySignalCard } from "@/components/technical/BbRsiEntrySignalCard";
import { WarrenSignalCard } from "@/components/technical/WarrenSignalCard";
import { WeinsteinStageCard } from "@/components/technical/WeinsteinStageCard";
import { useEntrySignal } from "@/lib/hooks/useEntrySignal";
import { useTrendAnalysis } from "@/lib/hooks/useTrendAnalysis";
import { useWarrenSignal } from "@/lib/hooks/useWarrenSignal";

interface Props {
  ticker: string;
  /** The ETF page: the two watchlist-gated cards' "not tracked" copy points at the ETF watchlist. */
  isEtf?: boolean;
}

export function TechnicalTab({ ticker, isEtf }: Props) {
  const { data, error, isLoading } = useTrendAnalysis(ticker);
  // Independent fetch, independent table -- deliberately not gated on the
  // Weinstein load/error state above (see useEntrySignal's own
  // comment). Undefined while loading reads the same as null (not yet
  // available) to BbRsiEntrySignalCard, which has its own "not tracked"
  // empty state.
  const { data: entrySignalData } = useEntrySignal(ticker);
  // Same independent-fetch convention as entrySignalData above -- a
  // distinct signal_type on the same underlying table, undefined-while-
  // loading reads the same as null to WarrenSignalCard, which has its own
  // "not tracked" state.
  const { data: warrenSignalData } = useWarrenSignal(ticker);

  if (error) {
    return <p className="py-6 text-sm text-negative">Couldn&apos;t load Technical — {error.message}</p>;
  }

  if (isLoading) {
    return <p className="py-6 text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }

  // Resolved (not still loading) but null: this ticker has never been
  // through the nightly Weinstein calculation (see
  // pipeline/nightly_trend_calculation.py) and there were no cached bars to
  // compute from on demand either -- distinct from "still loading," so it
  // gets its own explanatory state rather than the same spinner forever.
  if (!data) {
    return <p className="py-6 text-sm text-text-tertiary">No technical analysis available for {ticker} yet.</p>;
  }

  return (
    <div className="space-y-4 py-6">
      <div>
        <h2 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">Technical</h2>
        <p className="mt-1 text-sm text-text-secondary">Weekly stage analysis and entry signals. Informational only.</p>
      </div>

      <WeinsteinStageCard data={data} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <BbRsiEntrySignalCard data={entrySignalData ?? null} isEtf={isEtf} />
        <WarrenSignalCard data={warrenSignalData ?? null} isEtf={isEtf} />
      </div>
    </div>
  );
}
