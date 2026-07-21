"use client";

import { useState } from "react";

import { AnalysisTab } from "@/components/ticker/AnalysisTab";
import { ComingSoonPanel } from "@/components/ticker/ComingSoonPanel";
import { SummaryTab } from "@/components/ticker/SummaryTab";
import { TickerTabs } from "@/components/ticker/TickerTabs";
import { DEFAULT_TICKER_TAB, type TickerTab } from "@/lib/tickerTabs";

interface Props {
  ticker: string;
}

export function TickerTabsContainer({ ticker }: Props) {
  const [tab, setTab] = useState<TickerTab>(DEFAULT_TICKER_TAB);

  return (
    <div>
      <TickerTabs active={tab} onChange={setTab} />
      {tab === "summary" && <SummaryTab ticker={ticker} />}
      {tab === "financials" && <ComingSoonPanel label="Financials" />}
      {tab === "companyMetrics" && <ComingSoonPanel label="Company Metrics" />}
      {tab === "analysis" && <AnalysisTab ticker={ticker} />}
      {tab === "valuation" && <ComingSoonPanel label="Valuation" />}
    </div>
  );
}
