"use client";

import { AddToWatchlistButton } from "@/components/ticker/AddToWatchlistButton";
import { FairValuePill } from "@/components/ticker/FairValuePill";
import { MoatPill } from "@/components/ticker/MoatPill";
import { PriceChange } from "@/components/ticker/PriceChange";
import { RefreshButton } from "@/components/ticker/RefreshButton";
import { useOverallAssessment } from "@/lib/hooks/useOverallAssessment";
import { useTickerMoat } from "@/lib/hooks/useTickerMoat";
import { useTickerSummary } from "@/lib/hooks/useTickerSummary";
import { fmtMoney } from "@/lib/format";
import { flatChipClassFor } from "@/lib/tierColor";

interface Props {
  symbol: string;
}

// Flat (borderless) styling to match ScreenerCard/WatchlistTable's chip
// row -- same treatment FairValuePill/MoatPill get below via variant="flat".
function AssessmentChip({ symbol }: { symbol: string }) {
  const result = useOverallAssessment(symbol);
  if (result.status !== "complete" || result.score == null || result.verdict == null) return null;

  return (
    <span className={`inline-flex items-center rounded-md px-2 py-1 text-xs font-semibold ${flatChipClassFor(result.score, result.verdict)}`}>
      {result.verdict}
    </span>
  );
}

export function TickerHeader({ symbol }: Props) {
  const { data, error } = useTickerSummary(symbol);
  const { data: moatData } = useTickerMoat(symbol);

  if (error) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-negative">Couldn&apos;t load {symbol} — {error.message}</span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-text-tertiary animate-pulse">Loading {symbol}…</span>
      </div>
    );
  }

  return (
    <div className="space-y-3 pt-4">
      {/* Row 1: eyebrow + name/ticker/exchange, action buttons right-aligned */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          {(data.sector || data.industry) && (
            <p className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
              {data.sector}
              {data.sector && data.industry && " · "}
              {data.industry}
            </p>
          )}
          <div className="mt-1 flex flex-wrap items-baseline gap-3">
            <h1 className="font-heading text-2xl font-bold tracking-tight text-text-primary">{data.company_name ?? data.ticker}</h1>
            <span className="font-mono text-sm text-text-secondary">
              {data.ticker}
              {data.exchange && <> · {data.exchange}</>}
            </span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <AddToWatchlistButton tickers={[data.ticker]} />
          <RefreshButton ticker={data.ticker} />
        </div>
      </div>

      {/* Row 2: price + change + Assessment/Valuation/Moat chips */}
      <div className="flex flex-wrap items-center gap-3">
        {data.price != null && (
          <span className="font-mono text-xl font-bold tabular-nums text-text-primary">{fmtMoney(data.price)}</span>
        )}
        <PriceChange change={data.change} changePercent={data.change_percent} />
        <AssessmentChip symbol={symbol} />
        <FairValuePill verdict={data.fair_value_verdict} price={data.fair_value_price} method={data.fair_value_method} variant="flat" />
        <MoatPill moat={moatData?.moat} variant="flat" />
      </div>

      {/* Row 3: next earnings -- always shown so a null date reads as
          "not yet announced" rather than a silently missing row. */}
      <p className="text-xs text-text-tertiary">
        Next earnings:{" "}
        <span className="font-bold text-text-primary">{data.next_earnings_date ?? "Not yet announced"}</span>
      </p>
    </div>
  );
}
