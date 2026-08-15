"use client";

import { useState } from "react";

import { PageContainer } from "@/components/layout/PageContainer";
import { AnalysisTab } from "@/components/ticker/AnalysisTab";
import { AnalystRatingsTab } from "@/components/ticker/AnalystRatingsTab";
import { EconomicMoatTab } from "@/components/ticker/EconomicMoatTab";
import { FinancialsTab } from "@/components/ticker/FinancialsTab";
import { RatiosTab } from "@/components/ticker/RatiosTab";
import { SummaryTab } from "@/components/ticker/SummaryTab";
import { TickerHeader } from "@/components/ticker/TickerHeader";
import { TickerNotFound } from "@/components/ticker/TickerNotFound";
import { TickerTabs } from "@/components/ticker/TickerTabs";
import { ValuationTab } from "@/components/ticker/ValuationTab";
import { useTickerSummary } from "@/lib/hooks/useTickerSummary";
import { DEFAULT_TICKER_TAB, type TickerTab } from "@/lib/tickerTabs";

interface Props {
  ticker: string;
}

export function TickerTabsContainer({ ticker }: Props) {
  const [tab, setTab] = useState<TickerTab>(DEFAULT_TICKER_TAB);
  const { data, error } = useTickerSummary(ticker);

  // Single gate for the whole page: every tab (Financials, Ratios,
  // Analysis, ...) is lazy-mounted below and only ever renders once this
  // resolves successfully, so a confirmed-invalid ticker never triggers
  // any of their own FMP fetches -- see the ticker-search UX investigation.
  // The 404 check is string-based (matching the existing `.includes("409")`
  // convention in lib/api/client.ts) since apiFetch throws a plain Error,
  // not one carrying a structured status code.
  if (error) {
    if (error.message.includes(": 404")) {
      return <TickerNotFound ticker={ticker} />;
    }
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-negative">Couldn&apos;t load {ticker} — {error.message}</span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-text-tertiary animate-pulse">Loading {ticker}…</span>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col">
      {/* Sticky ticker header (rows 1-3) + tab nav (row 4) -- persists
          across all tabs, sticks directly below the top nav bar. */}
      <div className="sticky top-12 z-20 border-b border-border-card bg-page/95 backdrop-blur">
        <PageContainer>
          <TickerHeader symbol={ticker} data={data} />
          <TickerTabs active={tab} onChange={setTab} />
        </PageContainer>
      </div>

      <PageContainer className="space-y-2 pb-12">
        {tab === "summary" && <SummaryTab ticker={ticker} />}
        {tab === "financials" && <FinancialsTab ticker={ticker} />}
        {tab === "ratios" && <RatiosTab ticker={ticker} />}
        {tab === "analysis" && <AnalysisTab ticker={ticker} />}
        {tab === "analystRatings" && <AnalystRatingsTab ticker={ticker} />}
        {tab === "valuation" && <ValuationTab ticker={ticker} />}
        {tab === "moat" && <EconomicMoatTab ticker={ticker} />}
      </PageContainer>
    </div>
  );
}
