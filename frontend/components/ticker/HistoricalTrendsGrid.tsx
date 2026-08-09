"use client";

import { TrendCardsGrid, type TrendCard } from "@/components/charts/TrendCardsGrid";
import { useStep1 } from "@/lib/hooks/useStep1";
import { useStep4 } from "@/lib/hooks/useStep4";
import { useStep5 } from "@/lib/hooks/useStep5";
import { fmtCompactMoney, fmtDays, fmtTableMoney } from "@/lib/format";

interface Props {
  ticker: string;
}

// The "Historical Trends" grid at the top of the Financials tab -- sources
// straight from the same raw Step1/Step4 series (revenue/net income/CFO/
// FCF, AR/CCC) that back the Analysis tab's own scoring, just re-surfaced
// here as small preview cards. No new data. Margins/ROE/ROIC moved to the
// Ratios tab's own RatioTrendsGrid, alongside the rest of that tab's ratio
// figures. Also reads Step 5 (Debt) purely to gate the Total Debt card
// (below) -- not otherwise used here.
export function HistoricalTrendsGrid({ ticker }: Props) {
  const step1 = useStep1(ticker);
  const step4 = useStep4(ticker);
  const step5 = useStep5(ticker);

  if (!step1.data || !step4.data || !step5.data) {
    return <div className="h-24 animate-pulse rounded-lg border border-border-card bg-surface" />;
  }

  const s1 = step1.data;
  const s4 = step4.data;
  const s5 = step5.data;

  const ccc2 = (v: number) => fmtDays(v, 2);

  // Total Debt is only meaningful alongside Step 5's own debt verdict, so
  // it's suppressed for any ticker Step 5 didn't evaluate via its 3
  // ratios (Bank/Insurance/REIT company types, or a Standard/Utility
  // ticker missing required inputs -- see Step5Out.debt_ratios_evaluated)
  // -- same "empty values -> TrendCardsGrid drops the card" mechanism
  // ROIC/CCC already use for their own exempt-company-type cases below.
  //
  // Long-term + short-term combined into one stacked bar per period --
  // null only when BOTH sides are null for that period (a genuine data
  // gap), otherwise a missing side is treated as 0 so the other side still
  // renders as a normal (non-stacked-looking) full bar.
  const totalDebt = s5.debt_ratios_evaluated
    ? s4.years.map((_, i) => {
        const lt = s4.long_term_debt[i] ?? null;
        const st = s4.short_term_debt[i] ?? null;
        if (lt == null && st == null) return null;
        return (lt ?? 0) + (st ?? 0);
      })
    : [];

  const cards: (TrendCard | null)[] = [
    { key: "cfo", label: "Net Operating Cash Flow", years: s1.years, values: s1.cfo ?? [], format: fmtTableMoney, tooltipFormat: fmtCompactMoney },
    { key: "net_income", label: "Net Income", years: s1.years, values: s1.net_income, format: fmtTableMoney, tooltipFormat: fmtCompactMoney },
    { key: "operating_income", label: "Operating Income", years: s1.years, values: s1.operating_income, format: fmtTableMoney, tooltipFormat: fmtCompactMoney },
    { key: "revenue", label: s1.revenue_label, years: s1.years, values: s1.revenue, format: fmtTableMoney, tooltipFormat: fmtCompactMoney },
    { key: "fcf", label: "Free Cash Flow", years: s1.years, values: s1.fcf ?? [], format: fmtTableMoney, tooltipFormat: fmtCompactMoney },
    { key: "accounts_receivable", label: "Accounts Receivable", years: s4.years, values: s4.accounts_receivable, format: fmtTableMoney, tooltipFormat: fmtCompactMoney },
    { key: "ccc", label: "Cash Conversion Cycle", years: s4.years, values: s4.ccc ?? [], format: (v: number) => fmtDays(v, 0), tooltipFormat: ccc2 },
    {
      key: "total_debt",
      label: "Total Debt",
      years: s4.years,
      values: totalDebt,
      segments: [
        { key: "long_term_debt", label: "Long-Term Debt", color: "var(--color-brand)", values: s5.debt_ratios_evaluated ? s4.long_term_debt : [] },
        { key: "short_term_debt", label: "Short-Term Debt", color: "var(--color-chart-orange)", values: s5.debt_ratios_evaluated ? s4.short_term_debt : [] },
      ],
      format: fmtTableMoney,
      tooltipFormat: fmtCompactMoney,
    },
  ];

  return <TrendCardsGrid cards={cards} />;
}
