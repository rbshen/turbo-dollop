"use client";

import { useState } from "react";

import { PageContainer } from "@/components/layout/PageContainer";
import { AnalysisTab } from "@/components/ticker/AnalysisTab";
import { AnalystRatingsTab } from "@/components/ticker/AnalystRatingsTab";
import { EconomicMoatTab } from "@/components/ticker/EconomicMoatTab";
import { FinancialsTab } from "@/components/ticker/FinancialsTab";
import { NewsSentimentTab } from "@/components/ticker/NewsSentimentTab";
import { RatiosTab } from "@/components/ticker/RatiosTab";
import { SummaryTab } from "@/components/ticker/SummaryTab";
import { TickerHeader } from "@/components/ticker/TickerHeader";
import { TickerTabs } from "@/components/ticker/TickerTabs";
import { ValuationTab } from "@/components/ticker/ValuationTab";
import { DEFAULT_TICKER_TAB, type TickerTab } from "@/lib/tickerTabs";

interface Props {
  ticker: string;
}

export function TickerTabsContainer({ ticker }: Props) {
  const [tab, setTab] = useState<TickerTab>(DEFAULT_TICKER_TAB);

  return (
    <div className="flex flex-1 flex-col">
      {/* Sticky ticker header (rows 1-3) + tab nav (row 4) -- persists
          across all tabs, sticks directly below the top nav bar. */}
      <div className="sticky top-12 z-20 border-b border-border-card bg-page/95 backdrop-blur">
        <PageContainer>
          <TickerHeader symbol={ticker} />
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
        {tab === "newsSentiment" && <NewsSentimentTab />}
      </PageContainer>
    </div>
  );
}
