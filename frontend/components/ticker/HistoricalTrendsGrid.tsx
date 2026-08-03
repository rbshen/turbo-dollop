"use client";

import { TrendCardsGrid, type TrendCard } from "@/components/charts/TrendCardsGrid";
import { useStep1 } from "@/lib/hooks/useStep1";
import { useStep4 } from "@/lib/hooks/useStep4";
import { fmtCompactMoney, fmtDays, fmtTableMoney } from "@/lib/format";

interface Props {
  ticker: string;
}

// The "Historical Trends" grid at the top of the Financials tab -- sources
// straight from the same raw Step1/Step4 series (revenue/net income/CFO/
// FCF, AR/CCC) that back the Analysis tab's own scoring, just re-surfaced
// here as small preview cards. No new data. Margins/ROE/ROIC moved to the
// Ratios tab's own RatioTrendsGrid, alongside the rest of that tab's ratio
// figures.
export function HistoricalTrendsGrid({ ticker }: Props) {
  const step1 = useStep1(ticker);
  const step4 = useStep4(ticker);

  if (!step1.data || !step4.data) {
    return <div className="h-24 animate-pulse rounded-lg border border-border-card bg-surface" />;
  }

  const s1 = step1.data;
  const s4 = step4.data;

  const ccc2 = (v: number) => fmtDays(v, 2);

  const cards: (TrendCard | null)[] = [
    { key: "cfo", label: "Net Operating Cash Flow", years: s1.years, values: s1.cfo ?? [], format: fmtTableMoney, tooltipFormat: fmtCompactMoney },
    { key: "net_income", label: "Net Income", years: s1.years, values: s1.net_income, format: fmtTableMoney, tooltipFormat: fmtCompactMoney },
    { key: "operating_income", label: "Operating Income", years: s1.years, values: s1.operating_income, format: fmtTableMoney, tooltipFormat: fmtCompactMoney },
    { key: "revenue", label: s1.revenue_label, years: s1.years, values: s1.revenue, format: fmtTableMoney, tooltipFormat: fmtCompactMoney },
    { key: "fcf", label: "Free Cash Flow", years: s1.years, values: s1.fcf ?? [], format: fmtTableMoney, tooltipFormat: fmtCompactMoney },
    { key: "accounts_receivable", label: "Accounts Receivable", years: s4.years, values: s4.accounts_receivable, format: fmtTableMoney, tooltipFormat: fmtCompactMoney },
    { key: "ccc", label: "Cash Conversion Cycle", years: s4.years, values: s4.ccc ?? [], format: (v: number) => fmtDays(v, 0), tooltipFormat: ccc2 },
  ];

  return <TrendCardsGrid cards={cards} />;
}
