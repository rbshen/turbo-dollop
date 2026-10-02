"use client";

import { AddToWatchlistButton } from "@/components/ticker/AddToWatchlistButton";
import { FairValuePill } from "@/components/ticker/FairValuePill";
import { IndexMembershipPill } from "@/components/ticker/IndexMembershipPill";
import { MoatPill } from "@/components/ticker/MoatPill";
import { PerfVsSpyPill } from "@/components/ticker/PerfVsSpyPill";
import { PriceChange } from "@/components/ticker/PriceChange";
import { RefreshButton } from "@/components/ticker/RefreshButton";
import { SpeculativeGrowthFakeGrowthWarning } from "@/components/ticker/SpeculativeGrowthFakeGrowthWarning";
import { SpeculativeGrowthInfoIcon } from "@/components/ticker/SpeculativeGrowthInfoIcon";
import { SpeculativeGrowthPill } from "@/components/ticker/SpeculativeGrowthPill";
import { WeinsteinStagePill } from "@/components/ticker/WeinsteinStagePill";
import { Status } from "@/components/ui/status";
import { useSpeculativeGrowth } from "@/lib/hooks/useSpeculativeGrowth";
import { useTickerMoat } from "@/lib/hooks/useTickerMoat";
import { useTickerScore } from "@/lib/hooks/useTickerScore";
import { useTrendAnalysis } from "@/lib/hooks/useTrendAnalysis";
import { fmtMoney } from "@/lib/format";
import { toneForNullable, pillLabel } from "@/lib/tierColor";
import type { ReactNode } from "react";
import type { MoatValue } from "@/lib/overallScore";
import type { SpeculativeGrowthOut, TickerSummaryOut, TrendAnalysisOut } from "@/lib/api/types";

// Reads the precomputed TickerScore row (same source as Screener/Watchlist)
// instead of useOverallAssessment's live /step1,2,4,5 fetch + client-side
// blend -- that hook stays as-is for OverallAssessmentCard (Analysis tab),
// which needs the full live per-step breakdown this chip doesn't show.
// `data === null` covers a ticker with no cached profile at all (even the
// endpoint's own cache-only fallback couldn't produce a row) -- same
// "nothing to show yet" case as the loading state below.
function AssessmentChip({ symbol }: { symbol: string }) {
  const { data } = useTickerScore(symbol);
  if (!data || data.overall_score == null || data.overall_verdict == null) return null;

  return (
    <Status tone={toneForNullable(data.overall_score, data.overall_verdict)} title={`As of ${new Date(data.computed_at).toLocaleString()}`}>
      {pillLabel(data.overall_verdict)}
    </Status>
  );
}

type HeaderData = Pick<
  TickerSummaryOut,
  | "ticker"
  | "company_name"
  | "exchange"
  | "sector"
  | "industry"
  | "index_memberships"
  | "price"
  | "change"
  | "change_percent"
  | "quote_currency"
  | "reported_currency"
  | "fair_value_verdict"
  | "fair_value_price"
  | "fair_value_method"
  | "valuation_source"
  | "fair_value_reported_currency"
  | "perf_5y_vs_spy_status"
  | "perf_5y_insufficient_history"
  | "next_earnings_date"
>;

interface ViewProps {
  data: HeaderData;
  /** The Overall Assessment verdict pill (hook-driven in the app). */
  assessment: ReactNode;
  /** The Add-to-watchlist / Refresh buttons (hook-driven in the app). */
  actions: ReactNode;
  moat: MoatValue | null | undefined;
  specGrowth: SpeculativeGrowthOut | null | undefined;
  trend: TrendAnalysisOut | null | undefined;
}

// Presentational header -- all data arrives as props, so /styleguide can
// render the real layout (including the wrapping pill row) from mock data.
export function TickerHeaderView({ data, assessment, actions, moat, specGrowth, trend }: ViewProps) {
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
            <h1 className="font-heading text-2xl font-medium text-text-primary">{data.company_name ?? data.ticker}</h1>
            <span className="font-mono text-sm text-text-secondary">
              {data.ticker}
              {data.exchange && <> · {data.exchange}</>}
            </span>
            <IndexMembershipPill memberships={data.index_memberships} />
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">{actions}</div>
      </div>

      {/* Row 2: price + change, then the Assessment/Valuation/Moat/etc. status
          pills beside them -- six wide when everything applies. Whole pills
          wrap onto the next line (never break inside one), 8px apart both
          ways; the price + change group wraps as a unit, and the Speculative
          growth pill's icons sit in a nowrap group with it so they never
          split. `relative` is the anchor the two icon tooltips use below md. */}
      <div className="relative flex flex-wrap items-center gap-2">
        <div className="mr-1 flex items-center gap-3">
          {data.price != null && (
            <span className="font-mono text-xl font-bold tabular-nums text-text-primary">
              {fmtMoney(data.price, data.quote_currency)}
            </span>
          )}
          <PriceChange change={data.change} changePercent={data.change_percent} currency={data.quote_currency} />
        </div>
        {assessment}
        <MoatPill moat={moat} />
        <FairValuePill
          verdict={data.fair_value_verdict}
          price={data.fair_value_price}
          currency={data.quote_currency}
          method={data.fair_value_method}
          source={data.valuation_source}
          reportedCurrency={data.fair_value_reported_currency}
        />
        <span className="inline-flex items-center gap-1 whitespace-nowrap">
          <SpeculativeGrowthPill data={specGrowth} currency={data.reported_currency ?? "USD"} />
          {specGrowth?.qualifies && <SpeculativeGrowthInfoIcon />}
          {specGrowth?.qualifies && specGrowth.potential_fake_growth && <SpeculativeGrowthFakeGrowthWarning />}
        </span>
        <PerfVsSpyPill
          status={data.perf_5y_vs_spy_status}
          insufficientHistory={data.perf_5y_insufficient_history}
        />
        <WeinsteinStagePill data={trend} />
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

interface Props {
  symbol: string;
  data: TickerSummaryOut;
}

export function TickerHeader({ symbol, data }: Props) {
  const { data: moatData } = useTickerMoat(symbol);
  const { data: specGrowthData } = useSpeculativeGrowth(symbol);
  const { data: trendData } = useTrendAnalysis(symbol);

  return (
    <TickerHeaderView
      data={data}
      assessment={<AssessmentChip symbol={symbol} />}
      actions={
        <>
          <AddToWatchlistButton tickers={[data.ticker]} />
          <RefreshButton ticker={data.ticker} />
        </>
      }
      moat={moatData?.moat}
      specGrowth={specGrowthData}
      trend={trendData}
    />
  );
}
