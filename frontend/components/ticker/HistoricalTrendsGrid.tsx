"use client";

import { TrendCardsGrid, type TrendCard } from "@/components/charts/TrendCardsGrid";
import { useStep1 } from "@/lib/hooks/useStep1";
import { useStep4 } from "@/lib/hooks/useStep4";
import { useStep5 } from "@/lib/hooks/useStep5";
import { useFinancials } from "@/lib/hooks/useFinancials";
import { fmtCompactMoney, fmtDays, fmtTableMoney } from "@/lib/format";
import type { FinancialsPeriodOut } from "@/lib/api/types";

interface Props {
  ticker: string;
}

// Looks up a single Financials-tab line item by its exact label within one
// statement's annual period -- mirrors RatioTrendsGrid's own ratioValues
// helper. Callers pass the specific statement (income_statement/balance_
// sheet/cash_flow) rather than searching across all three, since a label
// like "Net Income" appears in more than one statement (the cash flow
// statement's own reconciliation-start line) with an identical value but
// no reason to risk picking the wrong one.
function financialsValues(period: FinancialsPeriodOut, label: string): (number | null)[] {
  for (const group of period.groups) {
    const item = group.items.find((i) => i.label === label);
    if (item) return item.values;
  }
  return [];
}

// FinancialsOut's own annual labels prefer the full filing date ("2018-09-
// 29") over the bare fiscal year, and label its TTM column "TTM (date)" --
// unlike Step1/Step4's own _annual_years, which prefer the bare fiscalYear
// and label TTM's slot just "TTM". Converts to that shorter convention so
// the repointed cards' tooltip/headline period text reads the same as
// before (a cosmetic label normalization only -- never touches values).
// "—" (a short-history pad slot) passes through unchanged.
function shortYearLabel(period: string): string {
  if (period === "—") return "—";
  if (period.startsWith("TTM")) return "TTM";
  return period.slice(0, 4);
}

export function HistoricalTrendsGrid({ ticker }: Props) {
  const step1 = useStep1(ticker);
  const step4 = useStep4(ticker);
  const step5 = useStep5(ticker);
  const financials = useFinancials(ticker);

  if (!step1.data || !step4.data || !step5.data || !financials.data) {
    return <div className="h-24 animate-pulse rounded-lg border border-border-card bg-surface" />;
  }

  const s1 = step1.data;
  const s4 = step4.data;
  const s5 = step5.data;
  const fin = financials.data;

  const incYears = fin.income_statement.annual.periods.map(shortYearLabel);
  const cfYears = fin.cash_flow.annual.periods.map(shortYearLabel);
  const bsYears = fin.balance_sheet.annual.periods.map(shortYearLabel);

  // CFO/FCF stay suppressed for CFO-exempt company types (Bank/Insurance/
  // Property Developer/Commodity Company -- see Step1Out.cfo_exempt_reason)
  // same as before this repoint: s1.cfo/s1.fcf still read null (the whole
  // field, not just de-weighted) for those types, even though FinancialsOut
  // itself has no such exemption and would otherwise happily show a real
  // CFO trend for them. The exemption is a Step1-scoring concept (CFO is
  // noisy/de-emphasized for these business models), not a data gap -- worth
  // continuing to hide the card rather than silently starting to show a
  // trend the app has never surfaced for these company types before.
  const cfoExempt = s1.cfo == null;

  // Accounts Receivable stays suppressed for company types Step 4 exempts
  // from the Revenue-vs-AR check (Bank/Insurance/Utility/REIT -- see
  // Step4Out.revenue_vs_ar_exempt_reason) -- same "FinancialsOut has no
  // notion of this exemption" reasoning as cfoExempt above: the raw balance
  // sheet always has an Accounts Receivable line, but it isn't a trend
  // worth showing for these business models.
  const arExempt = s4.revenue_vs_ar_exempt_reason != null;

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
    {
      key: "cfo",
      label: "Net Operating Cash Flow",
      years: cfYears,
      values: cfoExempt ? [] : financialsValues(fin.cash_flow.annual, "Net Cash from Operating Activities"),
      format: fmtTableMoney,
      tooltipFormat: fmtCompactMoney,
    },
    {
      key: "net_income",
      label: "Net Income",
      years: incYears,
      values: financialsValues(fin.income_statement.annual, "Net Income"),
      format: fmtTableMoney,
      tooltipFormat: fmtCompactMoney,
    },
    {
      key: "operating_income",
      label: "Operating Income",
      years: incYears,
      values: financialsValues(fin.income_statement.annual, "Operating Income"),
      format: fmtTableMoney,
      tooltipFormat: fmtCompactMoney,
    },
    {
      key: "revenue",
      // Value comes from the data-fetching pipeline; the Bank-aware
      // "Net Interest Income" vs "Revenue" label choice stays Step1's own
      // (see s1.revenue_label's own docs) -- FinancialsOut has no notion
      // of company-type-driven relabeling, it's a Step1-scoring concept.
      label: s1.revenue_label,
      years: incYears,
      values: financialsValues(fin.income_statement.annual, s1.revenue_label === "Revenue" ? "Revenue" : "Net Interest Income"),
      format: fmtTableMoney,
      tooltipFormat: fmtCompactMoney,
    },
    {
      key: "fcf",
      label: "Free Cash Flow",
      years: cfYears,
      values: cfoExempt ? [] : financialsValues(fin.cash_flow.annual, "Free Cash Flow"),
      format: fmtTableMoney,
      tooltipFormat: fmtCompactMoney,
    },
    {
      key: "accounts_receivable",
      label: "Accounts Receivable",
      years: bsYears,
      values: arExempt ? [] : financialsValues(fin.balance_sheet.annual, "Accounts Receivable"),
      format: fmtTableMoney,
      tooltipFormat: fmtCompactMoney,
    },
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
