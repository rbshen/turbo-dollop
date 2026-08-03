"use client";

import { TrendCardsGrid, type TrendCard } from "@/components/charts/TrendCardsGrid";
import { useStep1 } from "@/lib/hooks/useStep1";
import { useStep4 } from "@/lib/hooks/useStep4";
import { fmtPct, fmtPlainPct } from "@/lib/format";

interface Props {
  ticker: string;
}

// Margin/ROE/ROIC preview cards at the top of the Ratios tab -- same
// Step1/Step4 series and TrendCardsGrid house style as the Financials
// tab's own HistoricalTrendsGrid (moved here since they're profitability
// ratios, not raw financial-statement line items). No new data.
export function RatioTrendsGrid({ ticker }: Props) {
  const step1 = useStep1(ticker);
  const step4 = useStep4(ticker);

  if (!step1.data || !step4.data) {
    return <div className="h-24 animate-pulse rounded-lg border border-border-card bg-surface" />;
  }

  const s1 = step1.data;
  const s4 = step4.data;

  const cards: (TrendCard | null)[] = [
    { key: "gross_margin", label: "Gross Profit Margin", years: s1.years, values: s1.gross_margin, format: fmtPlainPct, tooltipFormat: fmtPct },
    { key: "net_margin", label: "Net Profit Margin", years: s1.years, values: s1.net_margin, format: fmtPlainPct, tooltipFormat: fmtPct },
    { key: "roe", label: "ROE", years: s4.years, values: s4.roe, format: fmtPlainPct, tooltipFormat: fmtPct },
    { key: "roic", label: "ROIC", years: s4.years, values: s4.roic ?? [], format: fmtPlainPct, tooltipFormat: fmtPct },
  ];

  return <TrendCardsGrid cards={cards} />;
}
