"use client";

import { useState } from "react";

import { PageContainer } from "@/components/layout/PageContainer";
import { GroupOffBadge } from "@/components/shared/GroupOffBadge";
import { ChartTab } from "@/components/ticker/ChartTab";
import { EtfHeader } from "@/components/ticker/EtfHeader";
import { EtfOverviewTab } from "@/components/ticker/EtfOverviewTab";
import { TechnicalTab } from "@/components/ticker/TechnicalTab";
import { TickerTabs } from "@/components/ticker/TickerTabs";
import type { TickerSummaryOut } from "@/lib/api/types";
import { TAB_GROUPS } from "@/lib/dataGroups";
import { DEFAULT_ETF_TICKER_TAB, ETF_TICKER_TABS, type TickerTab } from "@/lib/tickerTabs";

interface Props {
  ticker: string;
  data: TickerSummaryOut;
}

/** The ETF variant of the ticker page (docs/specs/etf-page.md), rendered by TickerTabsContainer when the
 * profile says isEtf/isFund. Same sticky header + tab bar shell as the stock page; Overview, Technical and
 * Chart only. Tabs are lazy-mounted, so a stock-only fetch (Financials, Moat, scores, ...) never fires. */
export function EtfTickerPage({ ticker, data }: Props) {
  const [tab, setTab] = useState<TickerTab>(DEFAULT_ETF_TICKER_TAB);

  return (
    <div className="flex flex-1 flex-col">
      <div className="sticky top-12 z-20 border-b border-border-card bg-page/95 backdrop-blur">
        <PageContainer>
          <EtfHeader data={data} />
          <TickerTabs active={tab} onChange={setTab} tabs={ETF_TICKER_TABS} />
        </PageContainer>
      </div>

      <PageContainer className="space-y-2 pb-12">
        <GroupOffBadge groups={TAB_GROUPS[tab] ?? []} />
        {tab === "overview" && <EtfOverviewTab ticker={ticker} />}
        {tab === "technical" && <TechnicalTab ticker={ticker} isEtf />}
        {tab === "chart" && <ChartTab ticker={ticker} isEtf />}
      </PageContainer>
    </div>
  );
}
